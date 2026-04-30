"""
Semantic and filter-based search routes.

POST /search/persons   — vector similarity search over persons
POST /search/startups  — vector similarity search over startups

Both endpoints accept a free-text query, embed it via Ollama, and search
Qdrant.  Optional filter_by params are passed as Qdrant payload filters.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from infra.qdrant import client as qdrant_client
from infra.qdrant.embeddings import embed
from shared.config import settings

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=50)
    score_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    filter_by: dict[str, Any] | None = None   # e.g. {"category": "fintech"}


class SearchHit(BaseModel):
    entity_id: uuid.UUID
    score: float
    payload: dict[str, Any]


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/persons", response_model=SearchResponse)
async def search_persons(body: SearchRequest) -> SearchResponse:
    """
    Embed `query` and find the closest person vectors in Qdrant.
    Returns entity_id + Qdrant payload (canonical_id, name, headline).
    """
    vector = await _embed(body.query)
    hits = await qdrant_client.search(
        collection=settings.qdrant_collection_persons,
        query_vector=vector,
        limit=body.limit,
        score_threshold=body.score_threshold,
        filter_by=body.filter_by,
    )
    return SearchResponse(
        query=body.query,
        hits=[
            SearchHit(
                entity_id=uuid.UUID(str(h.id)),
                score=h.score,
                payload=h.payload or {},
            )
            for h in hits
        ],
    )


@router.post("/startups", response_model=SearchResponse)
async def search_startups(body: SearchRequest) -> SearchResponse:
    """
    Embed `query` and find the closest startup vectors in Qdrant.
    Supports optional payload filter_by for e.g. category or maturity.
    """
    vector = await _embed(body.query)
    hits = await qdrant_client.search(
        collection=settings.qdrant_collection_startups,
        query_vector=vector,
        limit=body.limit,
        score_threshold=body.score_threshold,
        filter_by=body.filter_by,
    )
    return SearchResponse(
        query=body.query,
        hits=[
            SearchHit(
                entity_id=uuid.UUID(str(h.id)),
                score=h.score,
                payload=h.payload or {},
            )
            for h in hits
        ],
    )


async def _embed(query: str) -> list[float]:
    try:
        return await embed(query)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service unavailable: {exc}",
        )
