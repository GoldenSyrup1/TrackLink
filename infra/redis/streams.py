"""
Redis Streams base producer and consumer.

Rules enforced here:
- Each consumer is independent — pipelines never share a consumer group.
- Streams are auto-created with MKSTREAM on first XADD.
- Dead-letter handling: messages pending > claim_after_ms are re-claimed by
  this consumer so a crashed peer does not block the pipeline forever.
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

import redis.asyncio as aioredis

from shared.config import settings
from shared.events import EVENT_REGISTRY, StreamName, _BaseEvent

logger = logging.getLogger(__name__)

_redis_pool: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(
            settings.redis_url,
            decode_responses=False,  # consumers decode bytes themselves
            max_connections=20,
        )
    return _redis_pool


async def close_redis() -> None:
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None


# ---------------------------------------------------------------------------
# Producer
# ---------------------------------------------------------------------------

class StreamProducer:
    """
    Thin wrapper around XADD.  One instance per service; thread-safe via asyncio.
    """

    def __init__(self, redis: aioredis.Redis | None = None) -> None:
        self._redis = redis or get_redis()

    async def publish(self, event: _BaseEvent) -> str:
        """
        Publish event to its stream.  Stream is auto-created on first call
        (MAXLEN ~ capped, approximate trim for speed).
        Returns the Redis message ID.
        """
        stream = event.stream.value  # type: ignore[attr-defined]
        fields = event.to_redis_dict()
        msg_id: bytes = await self._redis.xadd(
            stream,
            fields,  # type: ignore[arg-type]
            maxlen=settings.redis_stream_maxlen,
            approximate=True,
        )
        logger.debug("published %s → %s id=%s", type(event).__name__, stream, msg_id)
        return msg_id.decode()


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------

class StreamConsumer(ABC):
    """
    Base class for all stream consumers.

    Subclass must implement `handle(event)`.  Each subclass owns its own
    consumer group name — groups are never shared between pipelines.

    Dead-letter recovery: messages pending longer than `claim_after_ms` are
    re-claimed by this consumer instance on each poll cycle.
    """

    stream: StreamName           # override in subclass
    group: str                   # override in subclass — unique per pipeline
    claim_after_ms: int = 30_000 # reclaim stale PEL entries after 30 s

    def __init__(
        self,
        consumer_name: str,
        redis: aioredis.Redis | None = None,
    ) -> None:
        self._consumer_name = consumer_name
        self._redis = redis or get_redis()
        self._running = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Create group (idempotent) then enter the poll loop."""
        await self._ensure_group()
        self._running = True
        await self._poll_loop()

    def stop(self) -> None:
        self._running = False

    @abstractmethod
    async def handle(self, event: _BaseEvent) -> None:
        """Process a single event.  Raise to trigger a NACK (no ACK)."""

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(
                self.stream.value,
                self.group,
                id="0",
                mkstream=True,  # create stream if it does not exist
            )
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def _poll_loop(self) -> None:
        batch = settings.redis_consumer_batch_size
        block_ms = settings.redis_consumer_block_ms

        while self._running:
            await self._reclaim_stale(batch)

            results = await self._redis.xreadgroup(
                self.group,
                self._consumer_name,
                {self.stream.value: ">"},
                count=batch,
                block=block_ms,
            )

            if not results:
                continue

            for _stream_name, messages in results:
                for msg_id, fields in messages:
                    await self._dispatch(msg_id, fields)

    async def _dispatch(self, msg_id: bytes, fields: dict[bytes, bytes]) -> None:
        event_cls = EVENT_REGISTRY.get(self.stream)
        if event_cls is None:
            logger.error("no event class registered for stream %s", self.stream)
            await self._ack(msg_id)
            return

        try:
            event = event_cls.from_redis_dict(fields)
            await self.handle(event)
            await self._ack(msg_id)
        except Exception:
            logger.exception(
                "consumer %s failed on %s msg=%s — leaving in PEL for reclaim",
                self._consumer_name,
                self.stream.value,
                msg_id,
            )
            # Do NOT ack — message stays in PEL and will be re-claimed

    async def _ack(self, msg_id: bytes) -> None:
        await self._redis.xack(self.stream.value, self.group, msg_id)

    async def _reclaim_stale(self, count: int) -> None:
        """XAUTOCLAIM messages that have been idle > claim_after_ms."""
        try:
            result = await self._redis.xautoclaim(
                self.stream.value,
                self.group,
                self._consumer_name,
                min_idle_time=self.claim_after_ms,
                start_id="0-0",
                count=count,
            )
            # result: (next_start_id, [(msg_id, fields), ...], [deleted_ids])
            _next, claimed, _deleted = result
            for msg_id, fields in claimed:
                if fields:  # empty fields = deleted message
                    await self._dispatch(msg_id, fields)
        except aioredis.ResponseError:
            # XAUTOCLAIM requires Redis ≥ 7.0; skip silently on older instances
            pass
