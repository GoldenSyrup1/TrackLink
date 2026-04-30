"""
Startup routes.

GET  /startups/{canonical_id}          — startup card
GET  /startups/{canonical_id}/score    — landscape / compatibility score
POST /startups/                        — enqueue scrape for a new startup
POST /startups/{canonical_id}/rescrape — re-enqueue scrape
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.postgres.session import get_session
from shared.events import EntityType, ScrapeSource, ScrapeStatus
from shared.models import ScrapeJob, Startup

router = APIRouter()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class ScoreComponents(BaseModel):
    funding: float | None = None
    github: float | None = None
    maturity: float | None = None
    tech: float | None = None
    llm: float | None = None


class LandscapeScoreOut(BaseModel):
    compatibility_score: float | None
    market_size_signal: str | None
    competitive_moat: str | None
    innovation_score: float | None
    llm_rationale: str | None
    score_components: ScoreComponents | None
    scored_at: str | None


class StartupCard(BaseModel):
    id: uuid.UUID
    canonical_id: str
    name: str | None
    domain: str | None
    category: str | None
    maturity: str | None
    compatibility_score: float | None
    problem_space: dict[str, Any]
    signals: dict[str, Any]
    scraped_at: datetime | None
    updated_at: datetime


class ScrapeJobOut(BaseModel):
    job_id: uuid.UUID
    status: str


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class CreateStartupRequest(BaseModel):
    canonical_id: str           # normalised domain, e.g. "example.com"
    crunchbase_slug: str | None = None
    github_org: str | None = None


class RescrapeRequest(BaseModel):
    sources: list[str] = ["crunchbase", "github"]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/{canonical_id}", response_model=StartupCard)
async def get_startup(
    canonical_id: str,
    session: AsyncSession = Depends(get_session),
) -> StartupCard:
    result = await session.execute(
        select(Startup).where(Startup.canonical_id == canonical_id)
    )
    startup = result.scalar_one_or_none()
    if startup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Startup not found")

    return StartupCard(
        id=startup.id,
        canonical_id=startup.canonical_id,
        name=startup.name,
        domain=startup.domain,
        category=startup.category,
        maturity=startup.maturity,
        compatibility_score=startup.compatibility_score,
        problem_space=startup.problem_space or {},
        signals=startup.signals or {},
        scraped_at=startup.scraped_at,
        updated_at=startup.updated_at,
    )


@router.get("/{canonical_id}/score", response_model=LandscapeScoreOut)
async def get_landscape_score(
    canonical_id: str,
    session: AsyncSession = Depends(get_session),
) -> LandscapeScoreOut:
    result = await session.execute(
        select(Startup.compatibility_score, Startup.problem_space)
        .where(Startup.canonical_id == canonical_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Startup not found")

    compat, ps = row
    ps = ps or {}
    components = ps.get("score_components") or {}

    return LandscapeScoreOut(
        compatibility_score=compat,
        market_size_signal=ps.get("market_size_signal"),
        competitive_moat=ps.get("competitive_moat"),
        innovation_score=ps.get("innovation_score"),
        llm_rationale=ps.get("llm_rationale"),
        score_components=ScoreComponents(**components) if components else None,
        scored_at=ps.get("scored_at"),
    )


@router.post("/", response_model=ScrapeJobOut, status_code=status.HTTP_202_ACCEPTED)
async def create_startup(
    body: CreateStartupRequest,
    session: AsyncSession = Depends(get_session),
) -> ScrapeJobOut:
    existing = await session.execute(
        select(Startup.id).where(Startup.canonical_id == body.canonical_id)
    )
    if existing.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Startup {body.canonical_id!r} already exists. Use /rescrape.",
        )

    source_map = {
        ScrapeSource.CRUNCHBASE: (
            f"https://www.crunchbase.com/organization/{body.crunchbase_slug}"
            if body.crunchbase_slug else None
        ),
        ScrapeSource.GITHUB: (
            f"https://github.com/{body.github_org}"
            if body.github_org else None
        ),
    }

    jobs: list[ScrapeJob] = []
    for src, url in source_map.items():
        if not url:
            continue
        job = ScrapeJob(
            id=uuid.uuid4(),
            entity_type=EntityType.STARTUP.value,
            source=src.value,
            target_url=url,
            status=ScrapeStatus.PENDING.value,
        )
        session.add(job)
        jobs.append(job)

    if not jobs:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least one of: crunchbase_slug, github_org.",
        )

    await session.flush()
    return ScrapeJobOut(job_id=jobs[0].id, status=ScrapeStatus.PENDING.value)


@router.post("/{canonical_id}/rescrape", response_model=ScrapeJobOut, status_code=status.HTTP_202_ACCEPTED)
async def rescrape_startup(
    canonical_id: str,
    body: RescrapeRequest,
    session: AsyncSession = Depends(get_session),
) -> ScrapeJobOut:
    result = await session.execute(
        select(Startup).where(Startup.canonical_id == canonical_id)
    )
    startup = result.scalar_one_or_none()
    if startup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Startup not found")

    sigs = startup.signals or {}
    jobs: list[ScrapeJob] = []

    for src_name in body.sources:
        url = _infer_url(src_name, canonical_id, sigs)
        if not url:
            continue
        job = ScrapeJob(
            id=uuid.uuid4(),
            entity_id=startup.id,
            entity_type=EntityType.STARTUP.value,
            source=src_name,
            target_url=url,
            status=ScrapeStatus.PENDING.value,
        )
        session.add(job)
        jobs.append(job)

    if not jobs:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No valid sources to rescrape.")

    await session.flush()
    return ScrapeJobOut(job_id=jobs[0].id, status=ScrapeStatus.PENDING.value)


def _infer_url(source: str, canonical_id: str, signals: dict) -> str | None:
    cb = signals.get("crunchbase") or {}
    gh = signals.get("github") or {}
    if source == "crunchbase" and canonical_id:
        return f"https://www.crunchbase.com/organization/{canonical_id.replace('.', '-')}"
    if source == "github" and gh.get("org"):
        return f"https://github.com/{gh['org']}"
    return None
