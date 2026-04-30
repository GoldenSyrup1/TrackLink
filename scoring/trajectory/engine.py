"""
Trajectory scoring engine — people pipeline.

Consumes entity.updated (entity_type=person), loads the Person row from
Postgres, computes trajectory_score / direction_vector / alignment_index,
writes them back, then publishes ScoreComputedEvent.

Score components
----------------
trajectory_score (JSONB, 0-100 sub-scores + composite):
  - career_momentum  : role seniority progression over time
  - github_activity  : repo count, followers, streak
  - social_reach     : Twitter followers / engagement
  - llm_assessment   : Ollama holistic narrative score

direction_vector (float, -1 → 1):
  -1.0  declining  (gaps, demotion, inactivity)
   0.0  stable
  +1.0  ascending  (recent promotion, growing GitHub, increasing reach)

alignment_index (float, 0 → 1):
  Overlap between person's skills/stack and high-signal emerging tech.
  Computed heuristically; LLM refines the final value.

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
from shared.models import Person

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

_OLLAMA_GENERATE = "/api/generate"

# High-signal tech keywords used for alignment_index
_EMERGING_TECH = {
    "llm", "llms", "ai", "machine learning", "ml", "deep learning",
    "transformer", "langchain", "langgraph", "vector database", "rag",
    "rust", "wasm", "webassembly", "kubernetes", "k8s", "platform engineering",
    "distributed systems", "data engineering", "dbt", "duckdb", "kafka",
    "stream processing", "graph neural", "reinforcement learning",
}

_SENIORITY_RANKS = {
    "intern": 0, "junior": 1, "associate": 2, "mid": 3, "": 3,
    "senior": 4, "staff": 5, "principal": 6, "lead": 5,
    "manager": 5, "director": 6, "vp": 7, "cto": 8, "ceo": 8, "founder": 8,
}

_SCORE_PROMPT = """\
You are evaluating a professional's career trajectory.
Given the following profile data, return ONLY valid JSON with:
{
  "llm_score": <integer 0-100>,
  "direction": <"ascending" | "stable" | "declining">,
  "alignment_boost": <float 0.0-0.3>,
  "rationale": <one sentence>
}

llm_score: overall career momentum (100 = exceptional upward trajectory)
direction: recent trend
alignment_boost: extra alignment with cutting-edge tech (0 if none)

Profile:
"""


class TrajectoryEngine(StreamConsumer):
    stream = StreamName.ENTITY_UPDATED
    group = "scoring.trajectory"

    def __init__(self, consumer_name: str = "trajectory-engine-1") -> None:
        super().__init__(consumer_name)
        self._producer = StreamProducer()

    async def handle(self, event: _BaseEvent) -> None:
        if not isinstance(event, EntityUpdatedEvent):
            return
        if event.entity_type != EntityType.PERSON:
            return

        with tracer.start_as_current_span("score.trajectory") as span:
            span.set_attribute("entity_id", event.entity_id)
            span.set_attribute("canonical_id", event.canonical_id)
            span_id = format(span.get_span_context().span_id, "016x")

            person = await _load_person(uuid.UUID(event.entity_id))
            if person is None:
                logger.warning("person %s not found in Postgres", event.entity_id)
                return

            scores = await _compute_scores(person)
            await _write_scores(person.id, scores)
            await self._producer.publish(
                ScoreComputedEvent(
                    entity_type=EntityType.PERSON,
                    entity_id=event.entity_id,
                    canonical_id=event.canonical_id,
                    score_type="trajectory",
                    span_id=span_id,
                )
            )
            logger.info(
                "trajectory scored %s: composite=%.1f direction=%.2f alignment=%.2f",
                event.canonical_id,
                scores["trajectory_score"].get("composite", 0),
                scores["direction_vector"],
                scores["alignment_index"],
            )


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

async def _load_person(entity_id: uuid.UUID) -> Person | None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Person).where(Person.id == entity_id)
        )
        return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------

async def _compute_scores(person: Person) -> dict:
    sources: dict = person.sources or {}
    linkedin = sources.get("linkedin", {})
    github = sources.get("github", {})
    twitter = sources.get("twitter", {})

    career_momentum = _score_career_momentum(linkedin)
    github_score = _score_github(github)
    social_score = _score_social(twitter)

    heuristic_composite = (
        career_momentum * 0.50
        + github_score * 0.30
        + social_score * 0.20
    )

    direction = _direction_from_heuristics(linkedin, github)
    alignment = _alignment_index(linkedin, github)

    llm = await _llm_assess(person, heuristic_composite, direction, alignment)

    llm_score = llm.get("llm_score", heuristic_composite)
    llm_direction = llm.get("direction", "stable")
    alignment_boost = float(llm.get("alignment_boost", 0.0))

    composite = heuristic_composite * 0.6 + llm_score * 0.4
    composite = max(0.0, min(100.0, composite))

    direction_map = {"ascending": 1.0, "stable": 0.0, "declining": -1.0}
    direction_val = direction_map.get(llm_direction, direction)

    alignment_val = min(1.0, alignment + alignment_boost)

    return {
        "trajectory_score": {
            "composite": round(composite, 1),
            "career_momentum": round(career_momentum, 1),
            "github_activity": round(github_score, 1),
            "social_reach": round(social_score, 1),
            "llm_score": llm_score,
            "rationale": llm.get("rationale", ""),
            "scored_at": datetime.now(timezone.utc).isoformat(),
        },
        "direction_vector": round(direction_val, 3),
        "alignment_index": round(alignment_val, 3),
    }


def _score_career_momentum(linkedin: dict) -> float:
    """0-100 based on role seniority progression and recency."""
    if not linkedin:
        return 30.0

    work = linkedin.get("work_history", [])
    if not work:
        return 30.0

    # Score current role seniority
    current = work[0]
    title = (current.get("title") or "").lower()
    rank = 3  # default mid
    for keyword, r in _SENIORITY_RANKS.items():
        if keyword and keyword in title:
            rank = max(rank, r)

    seniority_score = min(100.0, rank * 12.5)

    # Progression bonus: is rank higher than 2 jobs ago?
    if len(work) >= 2:
        prev_title = (work[1].get("title") or "").lower()
        prev_rank = max(
            (r for kw, r in _SENIORITY_RANKS.items() if kw and kw in prev_title),
            default=3,
        )
        progression_bonus = 10.0 if rank > prev_rank else 0.0
    else:
        progression_bonus = 0.0

    # Recency bonus: current role started within 3 years
    current_year = datetime.now().year
    start_year = current.get("start_year") or 0
    recency_bonus = 10.0 if (current_year - start_year) <= 3 else 0.0

    return min(100.0, seniority_score + progression_bonus + recency_bonus)


def _score_github(github: dict) -> float:
    """0-100 from repos, followers, streak."""
    if not github:
        return 0.0
    repos = github.get("public_repos", 0) or 0
    followers = github.get("followers", 0) or 0
    streak = github.get("contribution_streak", 0) or 0

    repo_score = min(40.0, math.log1p(repos) * 8)
    follower_score = min(40.0, math.log1p(followers) * 9)
    streak_score = min(20.0, streak * 0.5)
    return repo_score + follower_score + streak_score


def _score_social(twitter: dict) -> float:
    """0-100 from Twitter followers and tweet count."""
    if not twitter:
        return 0.0
    followers = twitter.get("followers", 0) or 0
    tweets = twitter.get("tweet_count", 0) or 0

    follower_score = min(70.0, math.log1p(followers) * 10)
    tweet_score = min(30.0, math.log1p(tweets) * 5)
    return follower_score + tweet_score


def _direction_from_heuristics(linkedin: dict, github: dict) -> float:
    """Quick heuristic direction before LLM confirmation."""
    signals = 0
    work = linkedin.get("work_history", [])
    if work:
        current_year = datetime.now().year
        start = work[0].get("start_year") or 0
        if 0 < (current_year - start) <= 2:
            signals += 1  # recent role change = ascending
        if len(work) >= 2:
            cur_title = (work[0].get("title") or "").lower()
            prev_title = (work[1].get("title") or "").lower()
            cur_rank = max((r for kw, r in _SENIORITY_RANKS.items() if kw and kw in cur_title), default=3)
            prv_rank = max((r for kw, r in _SENIORITY_RANKS.items() if kw and kw in prev_title), default=3)
            if cur_rank > prv_rank:
                signals += 1
            elif cur_rank < prv_rank:
                signals -= 1

    streak = (github.get("contribution_streak") or 0)
    if streak > 30:
        signals += 1
    elif streak == 0 and github:
        signals -= 1

    if signals >= 2:
        return 1.0
    elif signals <= -1:
        return -1.0
    return 0.0


def _alignment_index(linkedin: dict, github: dict) -> float:
    """Fraction of emerging-tech keywords present in skills + languages."""
    tokens: set[str] = set()

    skills = linkedin.get("skills", []) or []
    for s in skills:
        tokens.update(s.lower().split())

    langs = github.get("top_languages", []) or []
    for lang in langs:
        tokens.add(lang.lower())

    if not tokens:
        return 0.0

    hits = len(tokens & _EMERGING_TECH)
    return min(1.0, hits / 5)  # 5 hits = full alignment


async def _llm_assess(
    person: Person,
    heuristic_score: float,
    direction: float,
    alignment: float,
) -> dict:
    """Ask Ollama to holistically assess the career trajectory."""
    sources = person.sources or {}
    linkedin = sources.get("linkedin", {})

    summary_parts = []
    if person.name:
        summary_parts.append(f"Name: {person.name}")
    if person.headline:
        summary_parts.append(f"Headline: {person.headline}")
    work = linkedin.get("work_history", [])[:3]
    for w in work:
        if w.get("title") and w.get("company"):
            summary_parts.append(f"- {w['title']} at {w['company']}")
    skills = linkedin.get("skills", [])[:10]
    if skills:
        summary_parts.append("Skills: " + ", ".join(skills))
    summary_parts.append(f"Heuristic score: {heuristic_score:.0f}/100")

    prompt = _SCORE_PROMPT + "\n".join(summary_parts)
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
        logger.warning("LLM assessment failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Write-back
# ---------------------------------------------------------------------------

async def _write_scores(entity_id: uuid.UUID, scores: dict) -> None:
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            await session.execute(
                update(Person)
                .where(Person.id == entity_id)
                .values(
                    trajectory_score=scores["trajectory_score"],
                    direction_vector=scores["direction_vector"],
                    alignment_index=scores["alignment_index"],
                    updated_at=datetime.now(timezone.utc),
                )
            )
