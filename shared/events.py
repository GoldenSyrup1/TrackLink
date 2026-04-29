"""
Redis Streams event schemas for TrackLink.

Streams:
  scrape.raw      — raw HTML/JSON from a scraper run
  entity.updated  — normalised entity written to Postgres/Qdrant
  score.computed  — trajectory/landscape score ready for output
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class StreamName(str, Enum):
    SCRAPE_RAW = "scrape.raw"
    ENTITY_UPDATED = "entity.updated"
    SCORE_COMPUTED = "score.computed"


class EntityType(str, Enum):
    PERSON = "person"
    STARTUP = "startup"


class ScrapeSource(str, Enum):
    LINKEDIN = "linkedin"
    TWITTER = "twitter"
    GITHUB = "github"
    CRUNCHBASE = "crunchbase"


class ScrapeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class _BaseEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_dict(self) -> dict[str, str]:
        """Flatten to str→str map for XADD."""
        return {k: str(v) for k, v in self.model_dump().items()}

    @classmethod
    def from_redis_dict(cls, data: dict[bytes | str, bytes | str]) -> "_BaseEvent":
        decoded = {
            (k.decode() if isinstance(k, bytes) else k): (
                v.decode() if isinstance(v, bytes) else v
            )
            for k, v in data.items()
        }
        return cls.model_validate(decoded)


# ---------------------------------------------------------------------------
# scrape.raw
# ---------------------------------------------------------------------------

class ScrapeRawEvent(_BaseEvent):
    """Emitted by the scraper after each successful page fetch."""
    stream: StreamName = StreamName.SCRAPE_RAW
    job_id: str
    entity_type: EntityType
    source: ScrapeSource
    canonical_id: str
    target_url: str
    raw_content: str  # HTML or JSON string — extractors own parsing
    content_type: str = "text/html"  # or "application/json"
    span_id: str = ""  # OTel trace propagation


# ---------------------------------------------------------------------------
# entity.updated
# ---------------------------------------------------------------------------

class PersonUpdatedPayload(BaseModel):
    canonical_id: str
    name: str | None = None
    headline: str | None = None
    sources: dict[str, Any] = Field(default_factory=dict)


class StartupUpdatedPayload(BaseModel):
    canonical_id: str
    name: str | None = None
    domain: str | None = None
    category: str | None = None
    signals: dict[str, Any] = Field(default_factory=dict)


class EntityUpdatedEvent(_BaseEvent):
    """Emitted by extractors after writing to Postgres + Qdrant."""
    stream: StreamName = StreamName.ENTITY_UPDATED
    entity_type: EntityType
    entity_id: str  # UUID of the Postgres row (same key in Qdrant)
    canonical_id: str
    source: ScrapeSource
    span_id: str = ""

    def to_redis_dict(self) -> dict[str, str]:
        return {k: str(v) for k, v in self.model_dump().items()}


# ---------------------------------------------------------------------------
# score.computed
# ---------------------------------------------------------------------------

class ScoreComputedEvent(_BaseEvent):
    """Emitted by scoring engines after trajectory/landscape scores are written."""
    stream: StreamName = StreamName.SCORE_COMPUTED
    entity_type: EntityType
    entity_id: str
    canonical_id: str
    score_type: str  # "trajectory" | "landscape"
    score_version: int = 1
    span_id: str = ""

    def to_redis_dict(self) -> dict[str, str]:
        return {k: str(v) for k, v in self.model_dump().items()}


# ---------------------------------------------------------------------------
# Registry: stream → event class (for consumers)
# ---------------------------------------------------------------------------

EVENT_REGISTRY: dict[StreamName, type[_BaseEvent]] = {
    StreamName.SCRAPE_RAW: ScrapeRawEvent,
    StreamName.ENTITY_UPDATED: EntityUpdatedEvent,
    StreamName.SCORE_COMPUTED: ScoreComputedEvent,
}
