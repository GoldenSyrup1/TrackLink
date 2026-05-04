"""
OpenTelemetry tracing setup.

Call `setup_tracing()` once from the FastAPI lifespan before any spans
are created.  After that, every module can do:

    from opentelemetry import trace
    tracer = trace.get_tracer(__name__)

The OTLP exporter sends spans to whatever collector is running at
`settings.otel_endpoint` (default: localhost:4317, gRPC).
"""
from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

from shared.config import settings

logger = logging.getLogger(__name__)

_provider: TracerProvider | None = None


def setup_tracing(sample_rate: float = 1.0) -> None:
    """
    Configure the global OTel TracerProvider.
    Safe to call multiple times — subsequent calls are no-ops.

    `sample_rate` 1.0 = sample everything (default for development).
    Lower in high-throughput production (e.g. 0.1).
    """
    global _provider
    if _provider is not None:
        return

    resource = Resource.create({
        "service.name": settings.otel_service_name,
        "service.version": "0.1.0",
        "deployment.environment": "development",
    })

    sampler = ParentBased(root=TraceIdRatioBased(sample_rate))
    _provider = TracerProvider(resource=resource, sampler=sampler)

    # OTLP gRPC exporter → collector / Jaeger / Tempo
    try:
        otlp_exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint, insecure=True)
        _provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        logger.info("OTel OTLP exporter configured → %s", settings.otel_endpoint)
    except Exception as exc:
        # Collector not reachable at startup — fall back to console for dev
        logger.warning("OTLP exporter unavailable (%s) — using ConsoleSpanExporter", exc)
        _provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(_provider)
    logger.info("OTel tracing initialised (sample_rate=%.2f)", sample_rate)


def shutdown_tracing() -> None:
    """Flush pending spans.  Call from app lifespan shutdown."""
    global _provider
    if _provider is not None:
        _provider.shutdown()
        _provider = None


def get_tracer(name: str) -> trace.Tracer:
    """
    Convenience wrapper so callers don't need to import `opentelemetry.trace`
    directly.  Returns a no-op tracer if setup_tracing() hasn't been called.
    """
    return trace.get_tracer(name)
