"""
Audit log writer.

Every privileged action (write, delete) is recorded to the `audit_logs`
Postgres table.  Reads are recorded only when `log_reads=True` is passed
(off by default to avoid write amplification).

`log_action` is a thin async function — call it directly from route
handlers or use `AuditMiddleware` to auto-log all requests.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from infra.postgres.session import get_session_factory
from shared.models import AuditLog

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core writer
# ---------------------------------------------------------------------------

async def log_action(
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    detail: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """
    Persist one audit record.  Failures are logged and swallowed — audit
    logging must never cause a user-facing error.
    """
    try:
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                session.add(AuditLog(
                    id=uuid.uuid4(),
                    actor=actor,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    detail=detail or {},
                    ip_address=ip_address,
                ))
    except Exception:
        logger.exception(
            "audit log write failed — actor=%s action=%s resource=%s/%s",
            actor, action, resource_type, resource_id,
        )


# ---------------------------------------------------------------------------
# Middleware (optional — logs every HTTP request automatically)
# ---------------------------------------------------------------------------

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Routes that don't need audit entries
_SKIP_PATHS = frozenset({"/health", "/metrics", "/docs", "/openapi.json", "/redoc"})


class AuditMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that writes an audit record for every mutating HTTP
    request that carries a valid Authorization header.

    The actor is extracted from the `X-Actor` header set by the JWT
    dependency in auth/jwt.py (wire it in api/main.py via a request hook),
    or falls back to the raw Authorization token prefix.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)

        if request.url.path in _SKIP_PATHS:
            return response

        if request.method not in _WRITE_METHODS:
            return response

        actor = (
            request.headers.get("X-Actor")
            or _actor_from_auth(request.headers.get("Authorization", ""))
        )
        if not actor:
            return response

        resource_type, resource_id = _parse_path(request.url.path)
        await log_action(
            actor=actor,
            action=request.method.lower(),
            resource_type=resource_type,
            resource_id=resource_id,
            detail={"path": str(request.url), "status_code": response.status_code},
            ip_address=_client_ip(request),
        )

        return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _actor_from_auth(auth_header: str) -> str:
    """Return first 16 chars of a Bearer token as an anonymous actor hint."""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        return f"token:{token[:16]}…" if len(token) > 16 else f"token:{token}"
    return ""


def _parse_path(path: str) -> tuple[str, str | None]:
    """
    Best-effort extraction of resource type and id from URL path.
    /persons/linkedin.com/foo  →  ("person", "linkedin.com/foo")
    /startups/example.com      →  ("startup", "example.com")
    """
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        return ("unknown", None)
    resource_map = {
        "persons": "person",
        "startups": "startup",
        "relationships": "relationship",
        "search": "search",
    }
    resource_type = resource_map.get(parts[0], parts[0])
    resource_id = "/".join(parts[1:]) if len(parts) > 1 else None
    return resource_type, resource_id


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None
