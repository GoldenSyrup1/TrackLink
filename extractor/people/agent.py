"""
People extraction LangGraph agent.

Graph:  parse_raw → llm_extract → validate → done

Each node receives and returns `ExtractionState`.  The LLM node calls
Ollama (llama3.2) with a structured prompt and expects JSON back.
Every run is wrapped in an OTel span from the caller.
"""
from __future__ import annotations

import json
import logging
from typing import Annotated, Any, TypedDict

import httpx
from langgraph.graph import END, StateGraph

from extractor.people.signals import (
    Education,
    GitHubActivity,
    PersonSignals,
    TwitterActivity,
    WorkExperience,
)
from shared.config import settings
from shared.events import ScrapeSource

logger = logging.getLogger(__name__)

_OLLAMA_GENERATE = "/api/generate"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class ExtractionState(TypedDict):
    canonical_id: str
    source: str
    content_type: str
    raw_content: str
    extracted: dict[str, Any]   # intermediate LLM output
    signals: PersonSignals | None
    error: str | None


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_LINKEDIN_PROMPT = """\
Extract structured information from the following LinkedIn profile HTML.
Return ONLY valid JSON with these fields (use null for missing values):
{
  "name": string,
  "headline": string,
  "location": string,
  "summary": string,
  "skills": [string],
  "work_history": [{"title": string, "company": string, "start_year": int, "end_year": int|null, "description": string}],
  "education": [{"institution": string, "degree": string, "field": string, "end_year": int|null}]
}

HTML (first 8000 chars):
"""

_TWITTER_PROMPT = """\
Extract structured information from the following Twitter/X profile HTML.
Return ONLY valid JSON with these fields (use null for missing values):
{
  "username": string,
  "bio": string,
  "followers": int,
  "following": int,
  "tweet_count": int,
  "recent_topics": [string]
}

HTML (first 8000 chars):
"""

_GITHUB_PROMPT = """\
Extract structured information from the following GitHub API JSON response.
Return ONLY valid JSON with these fields (use null for missing values):
{
  "username": string,
  "public_repos": int,
  "followers": int,
  "top_languages": [string],
  "recent_push_repos": [string],
  "contribution_streak": int
}

JSON:
"""


def _prompt_for_source(source: str) -> str:
    if source == ScrapeSource.LINKEDIN.value:
        return _LINKEDIN_PROMPT
    if source == ScrapeSource.TWITTER.value:
        return _TWITTER_PROMPT
    if source == ScrapeSource.GITHUB.value:
        return _GITHUB_PROMPT
    return "Extract key information as JSON.\n\nContent:\n"


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

async def _parse_raw(state: ExtractionState) -> ExtractionState:
    """Truncate content to fit LLM context and attach prompt."""
    max_chars = 8000
    state["raw_content"] = state["raw_content"][:max_chars]
    return state


async def _llm_extract(state: ExtractionState) -> ExtractionState:
    """Call Ollama and parse the JSON response."""
    prompt = _prompt_for_source(state["source"]) + state["raw_content"]
    url = settings.ollama_base_url.rstrip("/") + _OLLAMA_GENERATE

    try:
        async with httpx.AsyncClient(timeout=settings.ollama_timeout_s) as client:
            resp = await client.post(
                url,
                json={
                    "model": settings.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
            )
            resp.raise_for_status()
        raw_json = resp.json().get("response", "{}")
        state["extracted"] = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        state["error"] = f"LLM returned invalid JSON: {exc}"
        state["extracted"] = {}
    except Exception as exc:
        state["error"] = f"LLM call failed: {exc}"
        state["extracted"] = {}

    return state


async def _validate(state: ExtractionState) -> ExtractionState:
    """Map raw LLM dict into a validated PersonSignals."""
    if state.get("error"):
        return state

    extracted = state["extracted"]
    source = state["source"]
    cid = state["canonical_id"]

    try:
        if source == ScrapeSource.LINKEDIN.value:
            signals = _build_from_linkedin(cid, extracted)
        elif source == ScrapeSource.TWITTER.value:
            signals = _build_from_twitter(cid, extracted)
        elif source == ScrapeSource.GITHUB.value:
            signals = _build_from_github(cid, extracted)
        else:
            signals = PersonSignals(canonical_id=cid, extra=extracted)
        state["signals"] = signals
    except Exception as exc:
        state["error"] = f"validation failed: {exc}"

    return state


def _build_from_linkedin(cid: str, d: dict) -> PersonSignals:
    return PersonSignals(
        canonical_id=cid,
        name=d.get("name"),
        headline=d.get("headline"),
        location=d.get("location"),
        summary=d.get("summary"),
        skills=d.get("skills") or [],
        work_history=[WorkExperience(**w) for w in (d.get("work_history") or [])],
        education=[Education(**e) for e in (d.get("education") or [])],
    )


def _build_from_twitter(cid: str, d: dict) -> PersonSignals:
    return PersonSignals(
        canonical_id=cid,
        twitter=TwitterActivity(
            username=d.get("username"),
            bio=d.get("bio"),
            followers=d.get("followers") or 0,
            following=d.get("following") or 0,
            tweet_count=d.get("tweet_count") or 0,
            recent_topics=d.get("recent_topics") or [],
        ),
    )


def _build_from_github(cid: str, d: dict) -> PersonSignals:
    return PersonSignals(
        canonical_id=cid,
        github=GitHubActivity(
            username=d.get("username"),
            public_repos=d.get("public_repos") or 0,
            followers=d.get("followers") or 0,
            top_languages=d.get("top_languages") or [],
            recent_push_repos=d.get("recent_push_repos") or [],
            contribution_streak=d.get("contribution_streak") or 0,
        ),
    )


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def _build_graph() -> Any:
    g: StateGraph = StateGraph(ExtractionState)
    g.add_node("parse_raw", _parse_raw)
    g.add_node("llm_extract", _llm_extract)
    g.add_node("validate", _validate)
    g.set_entry_point("parse_raw")
    g.add_edge("parse_raw", "llm_extract")
    g.add_edge("llm_extract", "validate")
    g.add_edge("validate", END)
    return g.compile()


_graph = _build_graph()


async def run(
    canonical_id: str,
    source: str,
    content_type: str,
    raw_content: str,
) -> PersonSignals | None:
    """
    Entry point for the consumer.  Returns `PersonSignals` or None on error.
    Caller is responsible for the OTel span.
    """
    state: ExtractionState = {
        "canonical_id": canonical_id,
        "source": source,
        "content_type": content_type,
        "raw_content": raw_content,
        "extracted": {},
        "signals": None,
        "error": None,
    }
    result = await _graph.ainvoke(state)
    if result.get("error"):
        logger.error(
            "people agent error for %s/%s: %s",
            source, canonical_id, result["error"],
        )
        return None
    return result.get("signals")
