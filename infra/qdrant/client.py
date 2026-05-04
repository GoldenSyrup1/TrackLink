"""
Async Qdrant client wrapper.

Rules enforced here:
- Vectors keyed by the same UUID as the Postgres row (no divergence).
- Collections are separate from ContextOS (different names, same server).
- Collection init is idempotent — safe to call on every startup.
- All public methods are async.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    ScoredPoint,
    VectorParams,
)

from shared.config import settings

logger = logging.getLogger(__name__)

_client: AsyncQdrantClient | None = None


def get_qdrant() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            timeout=30,
        )
    return _client


async def close_qdrant() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


# ---------------------------------------------------------------------------
# Collection schemas
# ---------------------------------------------------------------------------

_COLLECTIONS: dict[str, VectorParams] = {
    settings.qdrant_collection_persons: VectorParams(
        size=settings.qdrant_vector_size,
        distance=Distance.COSINE,
    ),
    settings.qdrant_collection_startups: VectorParams(
        size=settings.qdrant_vector_size,
        distance=Distance.COSINE,
    ),
}


async def init_collections() -> None:
    """
    Create tracklink_persons and tracklink_startups collections if they do not
    exist.  Safe to call repeatedly — existing collections are left untouched.
    """
    client = get_qdrant()
    existing = {c.name for c in (await client.get_collections()).collections}

    for name, vector_params in _COLLECTIONS.items():
        if name in existing:
            logger.debug("qdrant collection %r already exists — skipping", name)
            continue
        await client.create_collection(
            collection_name=name,
            vectors_config=vector_params,
        )
        logger.info("created qdrant collection %r (size=%d)", name, vector_params.size)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

async def upsert(
    collection: str,
    entity_id: uuid.UUID,
    vector: list[float],
    payload: dict[str, Any],
) -> None:
    """
    Upsert a single point.  The point ID is the same UUID used in Postgres.

    `payload` should include at minimum `canonical_id` and `entity_type`
    so search results can be correlated back to Postgres without an extra
    round-trip.
    """
    client = get_qdrant()
    point = PointStruct(
        id=str(entity_id),
        vector=vector,
        payload=payload,
    )
    await client.upsert(collection_name=collection, points=[point])
    logger.debug("upserted %s → %s", entity_id, collection)


async def upsert_batch(
    collection: str,
    points: list[tuple[uuid.UUID, list[float], dict[str, Any]]],
) -> None:
    """Batch upsert for bulk loads.  `points` is (entity_id, vector, payload)."""
    client = get_qdrant()
    structs = [
        PointStruct(id=str(eid), vector=vec, payload=pl)
        for eid, vec, pl in points
    ]
    await client.upsert(collection_name=collection, points=structs)
    logger.debug("batch upserted %d points → %s", len(structs), collection)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

async def search(
    collection: str,
    query_vector: list[float],
    limit: int = 10,
    score_threshold: float = 0.5,
    filter_by: dict[str, Any] | None = None,
) -> list[ScoredPoint]:
    """
    Vector similarity search.

    `filter_by` is an optional flat dict of payload field → exact match value,
    e.g. ``{"entity_type": "person"}``.  Extend to richer filters by building
    a `qdrant_client.models.Filter` directly and passing it as `filter_by`.
    """
    client = get_qdrant()

    qdrant_filter: Filter | None = None
    if filter_by:
        qdrant_filter = Filter(
            must=[
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in filter_by.items()
            ]
        )

    results: list[ScoredPoint] = await client.search(
        collection_name=collection,
        query_vector=query_vector,
        limit=limit,
        score_threshold=score_threshold,
        query_filter=qdrant_filter,
        with_payload=True,
    )
    return results


async def get_by_id(collection: str, entity_id: uuid.UUID) -> PointStruct | None:
    """Retrieve a single point by its UUID.  Returns None if not found."""
    client = get_qdrant()
    results = await client.retrieve(
        collection_name=collection,
        ids=[str(entity_id)],
        with_payload=True,
        with_vectors=False,
    )
    return results[0] if results else None


async def delete_by_id(collection: str, entity_id: uuid.UUID) -> None:
    """Remove a point.  No-op if the point does not exist."""
    from qdrant_client.models import PointIdsList

    client = get_qdrant()
    await client.delete(
        collection_name=collection,
        points_selector=PointIdsList(points=[str(entity_id)]),
    )
