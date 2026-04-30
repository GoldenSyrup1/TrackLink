"""
Scrape job scheduler.

Poll loop:
  1. Pull PENDING scrape_jobs rows from Postgres (oldest first, batch of N)
  2. Mark them RUNNING
  3. Dispatch to the appropriate source scraper
  4. Publish ScrapeRawEvent to scrape.raw Redis stream
  5. Mark DONE or FAILED, increment retry_count on failure

Every job execution is wrapped in an OTel span.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from opentelemetry import trace
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infra.postgres.session import get_session_factory
from infra.redis.streams import StreamProducer
from scraper.sources.crunchbase import CrunchbaseScraper
from scraper.sources.github import GitHubScraper
from scraper.sources.linkedin import LinkedInScraper
from scraper.sources.twitter import TwitterScraper
from scraper.playwright_client import StealthClient
from shared.config import settings
from shared.events import EntityType, ScrapeRawEvent, ScrapeSource, ScrapeStatus, StreamName
from shared.models import ScrapeJob

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

_DISPATCH: dict[str, type] = {
    ScrapeSource.LINKEDIN.value: LinkedInScraper,
    ScrapeSource.TWITTER.value: TwitterScraper,
    ScrapeSource.GITHUB.value: GitHubScraper,
    ScrapeSource.CRUNCHBASE.value: CrunchbaseScraper,
}

_POLL_INTERVAL_S = 5
_BATCH_SIZE = 5


class ScrapeScheduler:
    """
    Async background service — run one instance per process via `asyncio.create_task`.
    Stealth browser and Redis producer are shared across all jobs in a batch.
    """

    def __init__(self) -> None:
        self._producer = StreamProducer()
        self._client: StealthClient | None = None
        self._request_count = 0
        self._running = False

    async def start(self) -> None:
        self._client = StealthClient()
        await self._client.start()
        self._running = True
        logger.info("scrape scheduler started")
        await self._loop()

    async def stop(self) -> None:
        self._running = False
        if self._client:
            await self._client.stop()

    async def __aenter__(self) -> "ScrapeScheduler":
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.stop()

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._process_batch()
            except Exception:
                logger.exception("scheduler batch error")
            await asyncio.sleep(_POLL_INTERVAL_S)

    async def _process_batch(self) -> None:
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                jobs = await self._claim_pending(session)
                if not jobs:
                    return

        for job in jobs:
            await self._run_job(job)

    async def _claim_pending(self, session: AsyncSession) -> list[ScrapeJob]:
        """Atomically select and mark PENDING → RUNNING."""
        result = await session.execute(
            select(ScrapeJob)
            .where(ScrapeJob.status == ScrapeStatus.PENDING.value)
            .order_by(ScrapeJob.created_at)
            .limit(_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
        jobs = list(result.scalars().all())
        for job in jobs:
            job.status = ScrapeStatus.RUNNING.value
            job.updated_at = datetime.now(timezone.utc)
        return jobs

    # ------------------------------------------------------------------
    # Single job execution
    # ------------------------------------------------------------------

    async def _run_job(self, job: ScrapeJob) -> None:
        span_name = f"scrape.{job.source}.{job.entity_type}"
        with tracer.start_as_current_span(span_name) as span:
            span.set_attribute("job.id", str(job.id))
            span.set_attribute("job.source", job.source or "")
            span.set_attribute("job.entity_type", job.entity_type or "")
            span.set_attribute("job.target_url", job.target_url or "")
            span_ctx = span.get_span_context()
            span_id = format(span_ctx.span_id, "016x") if span_ctx else ""

            try:
                raw_content, content_type = await self._dispatch(job)
                await self._publish(job, raw_content, content_type, span_id)
                await self._mark_done(job)
                self._request_count += 1
                await self._maybe_rotate_context()
            except Exception as exc:
                span.record_exception(exc)
                await self._mark_failed(job, str(exc))

    async def _dispatch(self, job: ScrapeJob) -> tuple[str, str]:
        """Call the right source scraper and return (raw_content, content_type)."""
        assert self._client is not None
        source = job.source or ""
        url = job.target_url or ""

        if source == ScrapeSource.LINKEDIN.value:
            scraper = LinkedInScraper(self._client)
            return await scraper.fetch(url), "text/html"

        if source == ScrapeSource.TWITTER.value:
            scraper = TwitterScraper(self._client)
            return await scraper.fetch(url), "text/html"

        if source == ScrapeSource.GITHUB.value:
            scraper = GitHubScraper()
            content = await scraper.fetch(url)
            return content, "application/json"

        if source == ScrapeSource.CRUNCHBASE.value:
            scraper = CrunchbaseScraper(self._client)
            return await scraper.fetch(url), "text/html"

        raise ValueError(f"unknown source: {source!r}")

    async def _publish(
        self,
        job: ScrapeJob,
        raw_content: str,
        content_type: str,
        span_id: str,
    ) -> None:
        event = ScrapeRawEvent(
            job_id=str(job.id),
            entity_type=EntityType(job.entity_type),
            source=ScrapeSource(job.source),
            canonical_id=str(job.entity_id or ""),
            target_url=job.target_url or "",
            raw_content=raw_content,
            content_type=content_type,
            span_id=span_id,
        )
        await self._producer.publish(event)

    async def _mark_done(self, job: ScrapeJob) -> None:
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(ScrapeJob)
                    .where(ScrapeJob.id == job.id)
                    .values(
                        status=ScrapeStatus.DONE.value,
                        updated_at=datetime.now(timezone.utc),
                    )
                )

    async def _mark_failed(self, job: ScrapeJob, error: str) -> None:
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                new_retries = (job.retry_count or 0) + 1
                new_status = (
                    ScrapeStatus.FAILED.value
                    if new_retries >= settings.scraper_max_retries
                    else ScrapeStatus.PENDING.value  # re-queue for retry
                )
                await session.execute(
                    update(ScrapeJob)
                    .where(ScrapeJob.id == job.id)
                    .values(
                        status=new_status,
                        error=error[:2000],
                        retry_count=new_retries,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
        logger.warning(
            "job %s failed (retry %d/%d): %s",
            job.id, new_retries, settings.scraper_max_retries, error,
        )

    async def _maybe_rotate_context(self) -> None:
        rotate_after = settings.scraper_context_rotate_after
        if rotate_after and self._request_count % rotate_after == 0:
            assert self._client is not None
            await self._client.rotate_context()
