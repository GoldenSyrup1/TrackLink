"""
Relationship routes — network graph edges between persons and startups.

GET  /relationships/                   — list relationships (filterable)
GET  /relationships/{id}               — single relationship
POST /relationships/                   — create a relationship edge
GET  /relationships/network/{entity_id} — ego-network for an entity
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.postgres.session import get_session
from shared.models import Relationship

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RelationshipOut(BaseModel):
    id: uuid.UUID
    from_entity_id: uuid.UUID
    from_type: str
    to_entity_id: uuid.UUID
    to_type: str
    kind: str | None
    strength: float | None
    observed_at: datetime


class CreateRelationshipRequest(BaseModel):
    from_entity_id: uuid.UUID
    from_type: Literal["person", "startup"]
    to_entity_id: uuid.UUID
    to_type: Literal["person", "startup"]
    kind: str | None = None       # e.g. "worked_at", "invested_in", "co-founder"
    strength: float | None = None  # 0.0 – 1.0


class NetworkNode(BaseModel):
    entity_id: uuid.UUID
    entity_type: str


class NetworkEdge(BaseModel):
    relationship_id: uuid.UUID
    from_entity_id: uuid.UUID
    to_entity_id: uuid.UUID
    kind: str | None
    strength: float | None


class EgoNetwork(BaseModel):
    root: uuid.UUID
    nodes: list[NetworkNode]
    edges: list[NetworkEdge]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[RelationshipOut])
async def list_relationships(
    entity_id: uuid.UUID | None = Query(default=None),
    kind: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[RelationshipOut]:
    q = select(Relationship)
    if entity_id is not None:
        q = q.where(
            or_(
                Relationship.from_entity_id == entity_id,
                Relationship.to_entity_id == entity_id,
            )
        )
    if kind is not None:
        q = q.where(Relationship.kind == kind)
    q = q.order_by(Relationship.observed_at.desc()).limit(limit)
    result = await session.execute(q)
    rows = result.scalars().all()
    return [_rel_out(r) for r in rows]


@router.get("/network/{entity_id}", response_model=EgoNetwork)
async def get_ego_network(
    entity_id: uuid.UUID,
    depth: int = Query(default=1, le=2),
    session: AsyncSession = Depends(get_session),
) -> EgoNetwork:
    """Return all relationships within `depth` hops from `entity_id`."""
    visited_entities: set[uuid.UUID] = {entity_id}
    all_edges: list[Relationship] = []
    frontier: set[uuid.UUID] = {entity_id}

    for _ in range(depth):
        if not frontier:
            break
        result = await session.execute(
            select(Relationship).where(
                or_(
                    Relationship.from_entity_id.in_(frontier),
                    Relationship.to_entity_id.in_(frontier),
                )
            )
        )
        rels = result.scalars().all()
        new_frontier: set[uuid.UUID] = set()
        for rel in rels:
            all_edges.append(rel)
            for eid in (rel.from_entity_id, rel.to_entity_id):
                if eid not in visited_entities:
                    visited_entities.add(eid)
                    new_frontier.add(eid)
        frontier = new_frontier

    # Deduplicate edges (same rel can appear from both ends)
    seen_ids: set[uuid.UUID] = set()
    unique_edges: list[Relationship] = []
    for rel in all_edges:
        if rel.id not in seen_ids:
            seen_ids.add(rel.id)
            unique_edges.append(rel)

    nodes = [
        NetworkNode(entity_id=eid, entity_type="unknown")
        for eid in visited_entities
    ]
    edges = [
        NetworkEdge(
            relationship_id=r.id,
            from_entity_id=r.from_entity_id,
            to_entity_id=r.to_entity_id,
            kind=r.kind,
            strength=r.strength,
        )
        for r in unique_edges
    ]
    return EgoNetwork(root=entity_id, nodes=nodes, edges=edges)


@router.get("/{relationship_id}", response_model=RelationshipOut)
async def get_relationship(
    relationship_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> RelationshipOut:
    result = await session.execute(
        select(Relationship).where(Relationship.id == relationship_id)
    )
    rel = result.scalar_one_or_none()
    if rel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relationship not found")
    return _rel_out(rel)


@router.post("/", response_model=RelationshipOut, status_code=status.HTTP_201_CREATED)
async def create_relationship(
    body: CreateRelationshipRequest,
    session: AsyncSession = Depends(get_session),
) -> RelationshipOut:
    rel = Relationship(
        id=uuid.uuid4(),
        from_entity_id=body.from_entity_id,
        from_type=body.from_type,
        to_entity_id=body.to_entity_id,
        to_type=body.to_type,
        kind=body.kind,
        strength=body.strength,
    )
    session.add(rel)
    await session.flush()
    return _rel_out(rel)


def _rel_out(r: Relationship) -> RelationshipOut:
    return RelationshipOut(
        id=r.id,
        from_entity_id=r.from_entity_id,
        from_type=r.from_type,
        to_entity_id=r.to_entity_id,
        to_type=r.to_type,
        kind=r.kind,
        strength=r.strength,
        observed_at=r.observed_at,
    )
