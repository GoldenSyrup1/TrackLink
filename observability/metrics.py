"""
Prometheus metrics.

Call `setup_metrics(app)` from the FastAPI lifespan to attach the HTTP
instrumentation middleware and expose /metrics.

Call `start_metrics_server()` from background services (scraper, extractor,
scoring engines) to expose metrics on a dedicated port without FastAPI.

Available metric objects are importable directly:

    from observability.metrics import SCRAPE_JOBS, EXTRACTION_DURATION
"""
from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    start_http_server,
)
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.routing import Match

from shared.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

SCRAPE_JOBS = Counter(
    "tracklink_scrape_jobs_total",
    "Total scrape jobs by source and terminal status",
    ["source", "status"],
)

EXTRACTION_DURATION = Histogram(
    "tracklink_extraction_duration_seconds",
    "Time to run a LangGraph extraction agent",
    ["entity_type", "source"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120],
)

SCORING_DURATION = Histogram(
    "tracklink_scoring_duration_seconds",
    "Time to compute a trajectory or landscape score",
    ["score_type"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60],
)

QDRANT_SEARCH_DURATION = Histogram(
    "tracklink_qdrant_search_duration_seconds",
    "Qdrant vector search latency",
    ["collection"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2],
)

HTTP_REQUESTS = Counter(
    "tracklink_http_requests_total",
    "HTTP requests by method, route template, and status code",
    ["method", "route", "status_code"],
)

HTTP_DURATION = Histogram(
    "tracklink_http_request_duration_seconds",
    "HTTP request latency by method and route template",
    ["method", "route"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5],
)

REDIS_STREAM_LAG = Gauge(
    "tracklink_redis_stream_consumer_lag",
    "Approximate pending message count for a consumer group",
    ["stream", "group"],
)


# ---------------------------------------------------------------------------
# FastAPI middleware
# ---------------------------------------------------------------------------

class PrometheusMiddleware(BaseHTTPMiddleware):
    """Record HTTP_REQUESTS and HTTP_DURATION for every request."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        route = _matched_route(request)
        HTTP_REQUESTS.labels(
            method=request.method,
            route=route,
            status_code=str(response.status_code),
        ).inc()
        HTTP_DURATION.labels(method=request.method, route=route).observe(duration)

        return response


def _matched_route(request: Request) -> str:
    """Return the route template (e.g. '/persons/{canonical_id}') or the raw path."""
    for route in request.app.routes:
        match, _ = route.matches(request.scope)
        if match == Match.FULL:
            return getattr(route, "path", request.url.path)
    return request.url.path


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------

def setup_metrics(app: FastAPI) -> None:
    """
    Attach Prometheus middleware and expose a /metrics endpoint on the
    FastAPI app.  Call once from the application factory or lifespan.
    """
    app.add_middleware(PrometheusMiddleware)

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint() -> Response:
        data = generate_latest()
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)

    logger.info("Prometheus /metrics endpoint registered")


def start_metrics_server(port: int | None = None) -> None:
    """
    Start a standalone Prometheus HTTP server for background services that
    don't run FastAPI.  Safe to call multiple times — duplicates are ignored
    by prometheus_client.
    """
    p = port or settings.prometheus_port
    try:
        start_http_server(p)
        logger.info("Prometheus metrics server started on :%d", p)
    except OSError as exc:
        # Port already bound (e.g. called twice in tests) — not fatal
        logger.debug("Prometheus metrics server not started: %s", exc)
