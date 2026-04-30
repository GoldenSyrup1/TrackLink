"""
Landscape scoring engine — startup pipeline.

Consumes entity.updated (entity_type=startup), loads the Startup row from
Postgres, computes compatibility_score and enriches problem_space, writes
them back, then publishes ScoreComputedEvent.

Score components
----------------
compatibility_score (float 0-1, stored on startups row):
  Weighted combination of:
  - funding_signal   : log-scaled total funding + recency of last round
  - github_signal    : stars, contributors, active repos
  - maturity_fit     : preference for early-stage but de-risked (seed/mvp/growth)
  - tech_signal      : alignment of stack with high-signal languages/frameworks
  - llm_assessment   : Ollama holistic startup quality score

problem_space (JSONB, enriched in-place):
  Adds: market_size_signal, competitive_moat, innovation_score, llm_rationale

Every scoring run has an OTel span.
"""
from __future__ import annotations

import json
import logging
import math
import uuid
from datetime import datetime, timezone

import httpx
from opentelemetry import trace
from sqlalchemy import select, update

from infra.postgres.session import get_session_factory
from infra.redis.streams import StreamConsumer, StreamProducer
from shared.config import settings
from shared.events import (
    EntityType,
    EntityUpdatedEvent,
    ScoreComputedEvent,
    StreamName,
    _BaseEvent,
)
from shared.models import Startup

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

_OLLAMA_GENERATE = "/api/generate"

_HIGH_SIGNAL_LANGUAGES = {
    "rust", "go", "typescript", "python", "zig", "c++",
    "kotlin", "swift", "elixir", "haskell",
}

_MATURITY_WEIGHTS = {
    "idea": 0.4,    # high risk, high upside
    "mvp": 0.7,     # sweet spot
    "growth": 0.9,  # de-risked, still opportunity
    "scaled": 0.6,  # less greenfield
}

_COMPAT_PROMPT = """\
You are a startup intelligence analyst. Evaluate the following startup data and return ONLY valid JSON:
{
  "llm_score": <float 0-1>,
  "market_size_signal": <"large" | "medium" | "niche">,
  "competitive_moat": <"strong" | "moderate" | "weak">,
  "innovation_score": <float 0-1>,
  "rationale": <one sentence>
}

llm_score: overall compatibility / investment interest (1.0 = exceptional)
market_size_signal: estimated addressable market size
competitive_moat: strength of defensibility
innovation_score: novelty of approach

Startup data:
"""


class LandscapeEngine(StreamConsumer):
    stream = StreamName.ENTITY_UPDATED
    group = "scoring.landscape"

    def __init__(self, consumer_name: str = "landscape-engine-1") -> None:
        super().__init__(consumer_name)
        self._producer = StreamProducer()

    async def handle(self, event: _BaseEvent) -> None:
        if not isinstance(event, EntityUpdatedEvent):
            return
        if event.entity_type != EntityType.STARTUP:
            return

        with tracer.start_as_current_span("score.landscape") as span:
            span.set_attribute("entity_id", event.entity_id)
            span.set_attribute("canonical_id", event.canonical_id)
            span_id = format(span.get_span_context().span_id, "016x")

            startup = await _load_startup(uuid.UUID(event.entity_id))
            if startup is None:
                logger.warning("startup %s not found in Postgres", event.entity_id)
                return

            result = await _compute_scores(startup)
            await _write_scores(startup.id, result)
            await self._producer.publish(
                ScoreComputedEvent(
                    entity_type=EntityType.STARTUP,
                    entity_id=event.entity_id,
                    canonical_id=event.canonical_id,
                    score_type="landscape",
                    span_id=span_id,
                )
            )
            logger.info(
                "landscape scored %s: compat=%.3f",
                event.canonical_id,
                result["compatibility_score"],
            )


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

async def _load_startup(entity_id: uuid.UUID) -> Startup | None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Startup).where(Startup.id == entity_id)
        )
        return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------

async def _compute_scores(startup: Startup) -> dict:
    sigs: dict = startup.signals or {}
    crunchbase = sigs.get("crunchbase", {})
    github = sigs.get("github", {})
    tech_stack = sigs.get("tech_stack", []) or []

    funding_sig = _score_funding(crunchbase)
    github_sig = _score_github(github)
    maturity_fit = _maturity_weight(startup.maturity)
    tech_sig = _score_tech(tech_stack)

    heuristic = (
        funding_sig * 0.30
        + github_sig * 0.25
        + maturity_fit * 0.25
        + tech_sig * 0.20
    )

    llm = await _llm_assess(startup, heuristic)
    llm_score = float(llm.get("llm_score", heuristic))

    compat = heuristic * 0.55 + llm_score * 0.45
    compat = max(0.0, min(1.0, compat))

    problem_space_patch = {
        "market_size_signal": llm.get("market_size_signal", "unknown"),
        "competitive_moat": llm.get("competitive_moat", "unknown"),
        "innovation_score": float(llm.get("innovation_score", 0.0)),
        "llm_rationale": llm.get("rationale", ""),
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "score_components": {
            "funding": round(funding_sig, 3),
            "github": round(github_sig, 3),
            "maturity": round(maturity_fit, 3),
            "tech": round(tech_sig, 3),
            "llm": round(llm_score, 3),
        },
    }

    return {
        "compatibility_score": round(compat, 4),
        "problem_space_patch": problem_space_patch,
    }


def _score_funding(crunchbase: dict) -> float:
    """0-1 from log-scaled total funding."""
    if not crunchbase:
        return 0.2  # unknown — neutral-ish

    total = crunchbase.get("funding_total_usd") or 0
    if total <= 0:
        return 0.15

    # log scale: $1M → ~0.43, $10M → ~0.57, $100M → ~0.71, $1B → ~0.86
    log_val = math.log10(total + 1)
    return min(1.0, log_val / 10)


def _score_github(github: dict) -> float:
    """0-1 from stars and contributor count."""
    if not github:
        return 0.0
    stars = github.get("stars_total", 0) or 0
    contributors = github.get("contributors_count", 0) or 0
    repos = github.get("public_repos", 0) or 0

    star_score = min(0.5, math.log1p(stars) / 14)    # ~10k stars → 0.5
    contrib_score = min(0.3, math.log1p(contributors) / 17)
    repo_score = min(0.2, math.log1p(repos) / 20)
    return star_score + contrib_score + repo_score


def _maturity_weight(maturity: str | None) -> float:
    return _MATURITY_WEIGHTS.get((maturity or "").lower(), 0.5)


def _score_tech(tech_stack: list[str]) -> float:
    """Fraction of high-signal languages in the stack, capped at 1.0."""
    if not tech_stack:
        return 0.0
    hits = sum(1 for t in tech_stack if t.lower() in _HIGH_SIGNAL_LANGUAGES)
    return min(1.0, hits / max(1, min(len(tech_stack), 5)))


async def _llm_assess(startup: Startup, heuristic: float) -> dict:
    parts = []
    if startup.name:
        parts.append(f"Name: {startup.name}")
    if startup.category:
        parts.append(f"Category: {startup.category}")
    if startup.maturity:
        parts.append(f"Maturity: {startup.maturity}")

    sigs = startup.signals or {}
    cb = sigs.get("crunchbase", {})
    if cb.get("tagline"):
        parts.append(f"Tagline: {cb['tagline']}")
    if cb.get("description"):
        parts.append(f"Description: {cb['description'][:400]}")
    if cb.get("funding_total_usd"):
        parts.append(f"Total funding: ${cb['funding_total_usd']:,}")
    if cb.get("employee_count"):
        parts.append(f"Employees: {cb['employee_count']}")

    gh = sigs.get("github", {})
    if gh.get("stars_total"):
        parts.append(f"GitHub stars: {gh['stars_total']}")
    if gh.get("top_languages"):
        parts.append("Tech: " + ", ".join(gh["top_languages"][:5]))

    parts.append(f"Heuristic compat score: {heuristic:.2f}")

    prompt = _COMPAT_PROMPT + "\n".join(parts)
    url = settings.ollama_base_url.rstrip("/") + _OLLAMA_GENERATE

    try:
        async with httpx.AsyncClient(timeout=settings.ollama_timeout_s) as client:
            resp = await client.post(
                url,
                json={"model": settings.ollama_model, "prompt": prompt, "stream": False, "format": "json"},
            )
            resp.raise_for_status()
        return json.loads(resp.json().get("response", "{}"))
    except Exception as exc:
        logger.warning("LLM landscape assessment failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Write-back
# ---------------------------------------------------------------------------

async def _write_scores(entity_id: uuid.UUID, result: dict) -> None:
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            # Merge problem_space patch into existing JSONB via || operator
            await session.execute(
                update(Startup)
                .where(Startup.id == entity_id)
                .values(
                    compatibility_score=result["compatibility_score"],
                    problem_space=Startup.problem_space.op("||")(
                        result["problem_space_patch"]
                    ),
                    updated_at=datetime.now(timezone.utc),
                )
            )
