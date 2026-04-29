import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

class Person(Base):
    __tablename__ = "persons"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_id = Column(String, unique=True, nullable=False)
    name = Column(String)
    headline = Column(Text)
    sources = Column(JSONB, default=dict)
    trajectory_score = Column(JSONB, default=dict)
    direction_vector = Column(Float)
    alignment_index = Column(Float)
    scraped_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)

class Startup(Base):
    __tablename__ = "startups"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_id = Column(String, unique=True, nullable=False)
    name = Column(String)
    domain = Column(String)
    category = Column(String)
    maturity = Column(String)
    problem_space = Column(JSONB, default=dict)
    compatibility_score = Column(Float)
    signals = Column(JSONB, default=dict)
    scraped_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)

class Relationship(Base):
    __tablename__ = "relationships"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_entity_id = Column(UUID(as_uuid=True), nullable=False)
    from_type = Column(String, nullable=False)
    to_entity_id = Column(UUID(as_uuid=True), nullable=False)
    to_type = Column(String, nullable=False)
    kind = Column(String)
    strength = Column(Float)
    observed_at = Column(DateTime(timezone=True), default=datetime.utcnow)

class ScrapeJob(Base):
    __tablename__ = "scrape_jobs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type = Column(String)
    source = Column(String)
    status = Column(String, default="pending")
    result = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
