"""
Startup extraction consumer.

Listens to scrape.raw, filters entity_type=startup, runs the LangGraph
extraction agent, writes to Postgres + Qdrant, then publishes
entity.updated.

Independent consumer group — never shared with the people pipeline.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from opentelemetry import trace
from sqlalchemy.dialects.postgresql import insert as pg_insert

from extractor.startup import agent
from infra.postgres.session import get_session_factory
from infra.qdrant import client as qdrant_client
from infra.qdrant.embeddings import embed
from infra.redis.streams import StreamConsumer, StreamProducer
from shared.config import settings
from shared.events import (
    EntityType,
    EntityUpdatedEvent,
    ScrapeRawEvent,
    StreamName,
    _BaseEvent,
)
from shared.models import Startup

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class StartupConsumer(StreamConsumer):
    stream = StreamName.SCRAPE_RAW
    group = "extractor.startup"          # unique to this pipeline

    def __init__(self, consumer_name: str = "startup-extractor-1") -> None:
        super().__init__(consumer_name)
        self._producer = StreamProducer()

    async def handle(self, event: _BaseEvent) -> None:
        if not isinstance(event, ScrapeRawEvent):
            return
        if event.entity_type != EntityType.STARTUP:
            return

        with tracer.start_as_current_span(
            f"extract.startup.{event.source.value}",
        ) as span:
            span.set_attribute("canonical_id", event.canonical_id)
            span.set_attribute("source", event.source.value)
            span_id = format(span.get_span_context().span_id, "016x")

            signals = await agent.run(
                canonical_id=event.canonical_id,
                source=event.source.value,
                content_type=event.content_type,
                raw_content=event.raw_content,
            )
            if signals is None:
                logger.warning("no signals extracted for startup %s", event.canonical_id)
                return

            entity_id = await _upsert_postgres(signals)
            await _upsert_qdrant(entity_id, signals)
            await self._producer.publish(
                EntityUpdatedEvent(
                    entity_type=EntityType.STARTUP,
                    entity_id=str(entity_id),
                    canonical_id=event.canonical_id,
                    source=event.source,
                    span_id=span_id,
                )
            )
            logger.info("startup updated: %s (%s)", event.canonical_id, entity_id)


async def _upsert_postgres(signals) -> uuid.UUID:
    factory = get_session_factory()
    now = datetime.now(timezone.utc)

    async with factory() as session:
        async with session.begin():
            stmt = (
                pg_insert(Startup)
                .values(
                    id=uuid.uuid4(),
                    canonical_id=signals.canonical_id,
                    name=signals.name,
                    domain=signals.domain,
                    category=signals.category,
                    maturity=signals.maturity,
                    problem_space=signals.to_problem_space_jsonb(),
                    signals=signals.to_signals_jsonb(),
                    scraped_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["canonical_id"],
                    set_={
                        "name": signals.name,
                        "domain": signals.domain,
                        "category": signals.category,
                        "maturity": signals.maturity,
                        "problem_space": Startup.problem_space.op("||")(
                            signals.to_problem_space_jsonb()
                        ),
                        "signals": Startup.signals.op("||")(signals.to_signals_jsonb()),
                        "scraped_at": now,
                        "updated_at": now,
                    },
                )
                .returning(Startup.id)
            )
            result = await session.execute(stmt)
            row = result.fetchone()
            return row[0]


async def _upsert_qdrant(entity_id: uuid.UUID, signals) -> None:
    text = _signals_to_text(signals)
    vector = await embed(text)
    payload = {
        "canonical_id": signals.canonical_id,
        "entity_type": "startup",
        "name": signals.name,
        "category": signals.category,
        "maturity": signals.maturity,
        "domain": signals.domain,
    }
    await qdrant_client.upsert(
        collection=settings.qdrant_collection_startups,
        entity_id=entity_id,
        vector=vector,
        payload=payload,
    )


def _signals_to_text(signals) -> str:
    parts = []
    if signals.name:
        parts.append(signals.name)
    if signals.tagline:
        parts.append(signals.tagline)
    if signals.description:
        parts.append(signals.description[:400])
    if signals.category:
        parts.append(f"Category: {signals.category}")
    if signals.tech_stack:
        parts.append("Tech: " + ", ".join(signals.tech_stack[:10]))
    return " | ".join(parts)
