"""
Startup extraction LangGraph agent.

Graph:  parse_raw → llm_extract → validate → done

Handles Crunchbase HTML and GitHub org JSON.
"""
from __future__ import annotations

import json
import logging
from typing import Any, TypedDict

import httpx
from langgraph.graph import END, StateGraph

from extractor.startup.signals import (
    FundingRound,
    GitHubOrgActivity,
    StartupSignals,
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
    extracted: dict[str, Any]
    signals: StartupSignals | None
    error: str | None


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_CRUNCHBASE_PROMPT = """\
Extract structured startup information from the following Crunchbase HTML.
Return ONLY valid JSON with these fields (use null for missing values):
{
  "name": string,
  "tagline": string,
  "description": string,
  "category": string,
  "founded_year": int,
  "employee_count": string,
  "headquarters": string,
  "funding_total_usd": int,
  "funding_rounds": [{"round_type": string, "amount_usd": int, "date": string, "investors": [string]}],
  "investors": [string],
  "tech_stack": [string]
}

HTML (first 8000 chars):
"""

_GITHUB_ORG_PROMPT = """\
Extract structured startup GitHub activity from the following GitHub API JSON.
Return ONLY valid JSON with these fields (use null for missing values):
{
  "org": string,
  "public_repos": int,
  "stars_total": int,
  "top_languages": [string],
  "recent_push_repos": [string],
  "contributors_count": int
}

JSON:
"""

_MATURITY_PROMPT = """\
Based on the following startup data, classify its maturity stage as exactly one of:
idea | mvp | growth | scaled

Respond with ONLY valid JSON: {"maturity": "<stage>"}

Data:
"""


def _prompt_for_source(source: str) -> str:
    if source == ScrapeSource.CRUNCHBASE.value:
        return _CRUNCHBASE_PROMPT
    if source == ScrapeSource.GITHUB.value:
        return _GITHUB_ORG_PROMPT
    return "Extract key startup information as JSON.\n\nContent:\n"


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

async def _parse_raw(state: ExtractionState) -> ExtractionState:
    state["raw_content"] = state["raw_content"][:8000]
    return state


async def _llm_extract(state: ExtractionState) -> ExtractionState:
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


async def _infer_maturity(state: ExtractionState) -> ExtractionState:
    """Second LLM call to classify maturity stage from extracted data."""
    if state.get("error") or state["source"] != ScrapeSource.CRUNCHBASE.value:
        return state

    summary = json.dumps(state["extracted"])[:3000]
    url = settings.ollama_base_url.rstrip("/") + _OLLAMA_GENERATE

    try:
        async with httpx.AsyncClient(timeout=settings.ollama_timeout_s) as client:
            resp = await client.post(
                url,
                json={
                    "model": settings.ollama_model,
                    "prompt": _MATURITY_PROMPT + summary,
                    "stream": False,
                    "format": "json",
                },
            )
            resp.raise_for_status()
        maturity_json = json.loads(resp.json().get("response", "{}"))
        state["extracted"]["maturity"] = maturity_json.get("maturity")
    except Exception:
        pass  # maturity is optional; don't fail the whole extraction

    return state


async def _validate(state: ExtractionState) -> ExtractionState:
    if state.get("error"):
        return state

    extracted = state["extracted"]
    source = state["source"]
    cid = state["canonical_id"]

    try:
        if source == ScrapeSource.CRUNCHBASE.value:
            signals = _build_from_crunchbase(cid, extracted)
        elif source == ScrapeSource.GITHUB.value:
            signals = _build_from_github_org(cid, extracted)
        else:
            signals = StartupSignals(canonical_id=cid, extra=extracted)
        state["signals"] = signals
    except Exception as exc:
        state["error"] = f"validation failed: {exc}"

    return state


def _build_from_crunchbase(cid: str, d: dict) -> StartupSignals:
    return StartupSignals(
        canonical_id=cid,
        name=d.get("name"),
        tagline=d.get("tagline"),
        description=d.get("description"),
        category=d.get("category"),
        maturity=d.get("maturity"),
        founded_year=d.get("founded_year"),
        employee_count=d.get("employee_count"),
        headquarters=d.get("headquarters"),
        funding_total_usd=d.get("funding_total_usd"),
        funding_rounds=[FundingRound(**r) for r in (d.get("funding_rounds") or [])],
        investors=d.get("investors") or [],
        tech_stack=d.get("tech_stack") or [],
    )


def _build_from_github_org(cid: str, d: dict) -> StartupSignals:
    return StartupSignals(
        canonical_id=cid,
        github=GitHubOrgActivity(
            org=d.get("org"),
            public_repos=d.get("public_repos") or 0,
            stars_total=d.get("stars_total") or 0,
            top_languages=d.get("top_languages") or [],
            recent_push_repos=d.get("recent_push_repos") or [],
            contributors_count=d.get("contributors_count") or 0,
        ),
        tech_stack=d.get("top_languages") or [],
    )


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def _build_graph() -> Any:
    g: StateGraph = StateGraph(ExtractionState)
    g.add_node("parse_raw", _parse_raw)
    g.add_node("llm_extract", _llm_extract)
    g.add_node("infer_maturity", _infer_maturity)
    g.add_node("validate", _validate)
    g.set_entry_point("parse_raw")
    g.add_edge("parse_raw", "llm_extract")
    g.add_edge("llm_extract", "infer_maturity")
    g.add_edge("infer_maturity", "validate")
    g.add_edge("validate", END)
    return g.compile()


_graph = _build_graph()


async def run(
    canonical_id: str,
    source: str,
    content_type: str,
    raw_content: str,
) -> StartupSignals | None:
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
            "startup agent error for %s/%s: %s",
            source, canonical_id, result["error"],
        )
        return None
    return result.get("signals")
