"""
TrackLink FastAPI application entry point.

Lifespan: initialises Postgres tables, Qdrant collections, Redis pool on
startup; disposes connections on shutdown.
All routes are async. No sync route handlers anywhere.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import persons, relationships, search, startups
from infra.postgres.session import create_tables, dispose_engine
from infra.qdrant.client import close_qdrant, init_collections
from infra.redis.streams import close_redis
from shared.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    await init_collections()
    yield
    await dispose_engine()
    await close_qdrant()
    await close_redis()


app = FastAPI(
    title="TrackLink",
    description="Dual-pipeline trajectory intelligence platform.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(persons.router, prefix="/persons", tags=["persons"])
app.include_router(startups.router, prefix="/startups", tags=["startups"])
app.include_router(relationships.router, prefix="/relationships", tags=["relationships"])
app.include_router(search.router, prefix="/search", tags=["search"])


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok", "service": "tracklink"}
