"""
Person routes.

GET  /persons/{canonical_id}          — person card
GET  /persons/{canonical_id}/score    — trajectory score detail
POST /persons/                        — enqueue a scrape job for a new person
POST /persons/{canonical_id}/rescrape — enqueue re-scrape for existing person
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.postgres.session import get_session
from shared.events import EntityType, ScrapeSource, ScrapeStatus
from shared.models import Person, ScrapeJob

router = APIRouter()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class TrajectoryScoreOut(BaseModel):
    composite: float | None = None
    career_momentum: float | None = None
    github_activity: float | None = None
    social_reach: float | None = None
    llm_score: float | None = None
    rationale: str | None = None
    scored_at: str | None = None


class PersonCard(BaseModel):
    id: uuid.UUID
    canonical_id: str
    name: str | None
    headline: str | None
    direction_vector: float | None
    alignment_index: float | None
    trajectory_score: TrajectoryScoreOut | None
    sources: dict[str, Any]
    scraped_at: datetime | None
    updated_at: datetime


class ScrapeJobOut(BaseModel):
    job_id: uuid.UUID
    status: str


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class CreatePersonRequest(BaseModel):
    canonical_id: str           # normalised LinkedIn URL
    linkedin_url: str | None = None
    twitter_username: str | None = None
    github_username: str | None = None


class RescrapeRequest(BaseModel):
    sources: list[str] = ["linkedin", "github", "twitter"]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/{canonical_id}", response_model=PersonCard)
async def get_person(
    canonical_id: str,
    session: AsyncSession = Depends(get_session),
) -> PersonCard:
    result = await session.execute(
        select(Person).where(Person.canonical_id == canonical_id)
    )
    person = result.scalar_one_or_none()
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")

    ts_raw: dict = person.trajectory_score or {}
    return PersonCard(
        id=person.id,
        canonical_id=person.canonical_id,
        name=person.name,
        headline=person.headline,
        direction_vector=person.direction_vector,
        alignment_index=person.alignment_index,
        trajectory_score=TrajectoryScoreOut(**ts_raw) if ts_raw else None,
        sources=person.sources or {},
        scraped_at=person.scraped_at,
        updated_at=person.updated_at,
    )


@router.get("/{canonical_id}/score", response_model=TrajectoryScoreOut)
async def get_trajectory_score(
    canonical_id: str,
    session: AsyncSession = Depends(get_session),
) -> TrajectoryScoreOut:
    result = await session.execute(
        select(Person.trajectory_score).where(Person.canonical_id == canonical_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")
    ts: dict = row[0] or {}
    return TrajectoryScoreOut(**ts)


@router.post("/", response_model=ScrapeJobOut, status_code=status.HTTP_202_ACCEPTED)
async def create_person(
    body: CreatePersonRequest,
    session: AsyncSession = Depends(get_session),
) -> ScrapeJobOut:
    # Check dedup
    existing = await session.execute(
        select(Person.id).where(Person.canonical_id == body.canonical_id)
    )
    if existing.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Person with canonical_id {body.canonical_id!r} already exists. Use /rescrape.",
        )

    source_map = {
        ScrapeSource.LINKEDIN: body.linkedin_url,
        ScrapeSource.TWITTER: (
            f"https://mobile.x.com/{body.twitter_username}" if body.twitter_username else None
        ),
        ScrapeSource.GITHUB: (
            f"https://github.com/{body.github_username}" if body.github_username else None
        ),
    }

    # Enqueue one job per provided source URL
    jobs: list[ScrapeJob] = []
    for src, url in source_map.items():
        if not url:
            continue
        job = ScrapeJob(
            id=uuid.uuid4(),
            entity_type=EntityType.PERSON.value,
            source=src.value,
            target_url=url,
            status=ScrapeStatus.PENDING.value,
        )
        session.add(job)
        jobs.append(job)

    if not jobs:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one source URL must be provided.",
        )

    await session.flush()
    return ScrapeJobOut(job_id=jobs[0].id, status=ScrapeStatus.PENDING.value)


@router.post("/{canonical_id}/rescrape", response_model=ScrapeJobOut, status_code=status.HTTP_202_ACCEPTED)
async def rescrape_person(
    canonical_id: str,
    body: RescrapeRequest,
    session: AsyncSession = Depends(get_session),
) -> ScrapeJobOut:
    result = await session.execute(
        select(Person).where(Person.canonical_id == canonical_id)
    )
    person = result.scalar_one_or_none()
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")

    sources_data = person.sources or {}
    jobs: list[ScrapeJob] = []

    for src_name in body.sources:
        url = _infer_url(src_name, canonical_id, sources_data)
        if not url:
            continue
        job = ScrapeJob(
            id=uuid.uuid4(),
            entity_id=person.id,
            entity_type=EntityType.PERSON.value,
            source=src_name,
            target_url=url,
            status=ScrapeStatus.PENDING.value,
        )
        session.add(job)
        jobs.append(job)

    if not jobs:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No valid sources to scrape.")

    await session.flush()
    return ScrapeJobOut(job_id=jobs[0].id, status=ScrapeStatus.PENDING.value)


def _infer_url(source: str, canonical_id: str, sources: dict) -> str | None:
    if source == "linkedin":
        return canonical_id  # canonical_id IS the LinkedIn URL for persons
    gh = (sources.get("github") or {}).get("username")
    if source == "github" and gh:
        return f"https://github.com/{gh}"
    tw = (sources.get("twitter") or {}).get("username")
    if source == "twitter" and tw:
        return f"https://mobile.x.com/{tw}"
    return None
