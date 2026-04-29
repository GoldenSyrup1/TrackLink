import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Column, String, Float, DateTime, Text, Index,
    ForeignKey, func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Person(Base):
    __tablename__ = "persons"
    __table_args__ = (
        Index("ix_persons_canonical_id", "canonical_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    canonical_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str | None] = mapped_column(String)
    headline: Mapped[str | None] = mapped_column(Text)
    # sources/signals are always jsonb — never add columns for new sources
    sources: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    trajectory_score: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    direction_vector: Mapped[float | None] = mapped_column(Float)
    alignment_index: Mapped[float | None] = mapped_column(Float)
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )


class Startup(Base):
    __tablename__ = "startups"
    __table_args__ = (
        Index("ix_startups_canonical_id", "canonical_id", unique=True),
        Index("ix_startups_domain", "domain"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    canonical_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str | None] = mapped_column(String)
    domain: Mapped[str | None] = mapped_column(String)
    category: Mapped[str | None] = mapped_column(String)
    maturity: Mapped[str | None] = mapped_column(String)
    # problem_space and signals are always jsonb
    problem_space: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    compatibility_score: Mapped[float | None] = mapped_column(Float)
    signals: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )


class Relationship(Base):
    __tablename__ = "relationships"
    __table_args__ = (
        Index("ix_relationships_from", "from_entity_id"),
        Index("ix_relationships_to", "to_entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    from_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    from_type: Mapped[str] = mapped_column(String, nullable=False)
    to_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    to_type: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str | None] = mapped_column(String)
    strength: Mapped[float | None] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )


class ScrapeJob(Base):
    __tablename__ = "scrape_jobs"
    __table_args__ = (
        Index("ix_scrape_jobs_status", "status"),
        Index("ix_scrape_jobs_entity", "entity_type", "source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    entity_type: Mapped[str | None] = mapped_column(String)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source: Mapped[str | None] = mapped_column(String)
    target_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )
