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


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
