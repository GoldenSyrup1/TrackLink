"""
People extraction consumer.

Listens to scrape.raw, filters entity_type=person, runs the LangGraph
extraction agent, writes to Postgres + Qdrant, then publishes
entity.updated.

Key rules enforced:
- canonical_id is the dedup key — uses ON CONFLICT DO UPDATE
- Qdrant vector keyed by same UUID as Postgres row
- Every extraction run has an OTel span
- Consumer group is independent (never shared with startup pipeline)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from opentelemetry import trace
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from extractor.people import agent
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
from shared.models import Person

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class PeopleConsumer(StreamConsumer):
    stream = StreamName.SCRAPE_RAW
    group = "extractor.people"           # unique to this pipeline

    def __init__(self, consumer_name: str = "people-extractor-1") -> None:
        super().__init__(consumer_name)
        self._producer = StreamProducer()

    async def handle(self, event: _BaseEvent) -> None:
        if not isinstance(event, ScrapeRawEvent):
            return
        if event.entity_type != EntityType.PERSON:
            return  # startup events pass through — acked, not processed

        with tracer.start_as_current_span(
            f"extract.person.{event.source.value}",
            context=_otel_context(event.span_id),
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
                logger.warning("no signals extracted for %s", event.canonical_id)
                return

            entity_id = await _upsert_postgres(signals)
            await _upsert_qdrant(entity_id, signals)
            await self._producer.publish(
                EntityUpdatedEvent(
                    entity_type=EntityType.PERSON,
                    entity_id=str(entity_id),
                    canonical_id=event.canonical_id,
                    source=event.source,
                    span_id=span_id,
                )
            )
            logger.info("person updated: %s (%s)", event.canonical_id, entity_id)


async def _upsert_postgres(signals) -> uuid.UUID:
    factory = get_session_factory()
    now = datetime.now(timezone.utc)

    async with factory() as session:
        async with session.begin():
            stmt = (
                pg_insert(Person)
                .values(
                    id=uuid.uuid4(),
                    canonical_id=signals.canonical_id,
                    name=signals.name,
                    headline=signals.headline,
                    sources=signals.to_sources_jsonb(),
                    scraped_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["canonical_id"],
                    set_={
                        "name": signals.name,
                        "headline": signals.headline,
                        "sources": Person.sources.op("||")(signals.to_sources_jsonb()),
                        "scraped_at": now,
                        "updated_at": now,
                    },
                )
                .returning(Person.id)
            )
            result = await session.execute(stmt)
            row = result.fetchone()
            return row[0]


async def _upsert_qdrant(entity_id: uuid.UUID, signals) -> None:
    text = _signals_to_text(signals)
    vector = await embed(text)
    payload = {
        "canonical_id": signals.canonical_id,
        "entity_type": "person",
        "name": signals.name,
        "headline": signals.headline,
    }
    await qdrant_client.upsert(
        collection=settings.qdrant_collection_persons,
        entity_id=entity_id,
        vector=vector,
        payload=payload,
    )


def _signals_to_text(signals) -> str:
    """Build a plain-text representation for embedding."""
    parts = []
    if signals.name:
        parts.append(signals.name)
    if signals.headline:
        parts.append(signals.headline)
    if signals.summary:
        parts.append(signals.summary)
    if signals.skills:
        parts.append("Skills: " + ", ".join(signals.skills))
    for w in signals.work_history[:3]:
        if w.title and w.company:
            parts.append(f"{w.title} at {w.company}")
    return " | ".join(parts)


def _otel_context(span_id_hex: str):
    """Reconstruct a minimal OTel context from a hex span_id for linking."""
    # Full distributed tracing would use W3C traceparent propagation;
    # this provides a best-effort link when the scraper passed a span_id.
    return None  # placeholder — extend with opentelemetry propagators
