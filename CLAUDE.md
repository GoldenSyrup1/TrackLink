# TrackLink

Dual-pipeline trajectory intelligence platform.

**Output 1 â€” People intelligence:** trajectory score, direction vector, alignment index from public social footprint (LinkedIn, Twitter/X, GitHub).
**Output 2 â€” Startup landscape:** category, maturity, problem space, compatibility score (Crunchbase, GitHub, news).

## Stack
FastAPI + LangGraph + Ollama (Llama3.2) + Playwright + Redis Streams + PostgreSQL + Qdrant (port 6333, shared with ContextOS, separate collections) + JWT/OAuth2 + OpenTelemetry + Prometheus

## Architecture
Sources â†’ Opsec (stealth + proxy + jitter) â†’ Redis Streams (scrape.raw | entity.updated | score.computed) â†’ People extractor / Startup extractor (independent consumers) â†’ Trajectory engine / Landscape engine â†’ PostgreSQL + Qdrant â†’ Auth/RBAC gateway â†’ Output (person card | startup card | network graph)

All internal calls use mTLS. AES-256 at rest. TLS 1.3 in transit.

## Key rules
- canonical_id is the dedup key (normalized LinkedIn URL or domain) â€” never duplicate
- sources/signals are always jsonb â€” never add columns for new sources
- Qdrant vectors keyed by same uuid as PostgreSQL row
- Redis consumers are always independent â€” pipelines never share a consumer group
- All async/await â€” no sync route handlers
- Every scrape job, extraction run, and scoring call must have an OTel span

## Build order
1. shared/ (config, models, events)
2. infra/ (redis streams, postgres session, qdrant client)
3. scraper/ (playwright stealth stub + scheduler)
4. extractor/ (consumers + LangGraph agents)
5. scoring/ (trajectory + landscape engines)
6. api/ (routes)
7. auth/ (jwt + rbac + audit)
8. observability/ (tracing + metrics)

## Environment
WSL2 Ubuntu 24.04, ARM64, no Docker. Services run natively in WSL2. Ollama on Windows side at http://172.17.0.1:11434.
