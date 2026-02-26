"""Dhruva — Redis Stream Manager with In-Memory Fallback."""

import asyncio
import json
import logging
from collections import deque
from datetime import datetime
from typing import Optional

logger = logging.getLogger("dhruva.redis")


class InMemoryStream:
    """Fallback event stream when Redis is unavailable."""

    def __init__(self, maxlen: int = 5000):
        self._events: deque = deque(maxlen=maxlen)
        self._subscribers: list[asyncio.Queue] = []

    async def publish(self, event_data: dict):
        self._events.append(event_data)
        for q in self._subscribers:
            try:
                q.put_nowait(event_data)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self._subscribers:
            self._subscribers.remove(q)

    def get_recent(self, count: int = 100) -> list[dict]:
        items = list(self._events)
        return items[-count:]


class RedisStreamManager:
    """Manages event publishing and subscribing via Redis Streams or in-memory fallback."""

    def __init__(self, redis_url: str = "redis://localhost:6379", stream_key: str = "dhruva:events", use_redis: bool = False):
        self._redis_url = redis_url
        self._stream_key = stream_key
        self._use_redis = use_redis
        self._redis = None
        self._memory_stream = InMemoryStream()

    async def connect(self):
        if self._use_redis:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
                await self._redis.ping()
                logger.info("Connected to Redis at %s", self._redis_url)
            except Exception as e:
                logger.warning("Redis unavailable (%s), falling back to in-memory stream", e)
                self._redis = None
                self._use_redis = False
        else:
            logger.info("Using in-memory event stream (Redis disabled)")

    async def publish_event(self, event: dict):
        """Publish an event to the stream."""
        event_json = json.dumps(event, default=str)

        if self._redis:
            try:
                await self._redis.xadd(
                    self._stream_key,
                    {"data": event_json},
                    maxlen=5000,
                )
            except Exception as e:
                logger.error("Redis publish error: %s", e)
                await self._memory_stream.publish(event)
        else:
            await self._memory_stream.publish(event)

    async def publish_batch(self, events: list[dict]):
        """Publish a batch of events."""
        for event in events:
            await self.publish_event(event)

    def subscribe(self) -> asyncio.Queue:
        """Get a subscription queue for real-time events."""
        return self._memory_stream.subscribe()

    def unsubscribe(self, q: asyncio.Queue):
        self._memory_stream.unsubscribe(q)

    async def get_recent_events(self, count: int = 200) -> list[dict]:
        """Get recent events from the stream."""
        if self._redis:
            try:
                entries = await self._redis.xrevrange(self._stream_key, count=count)
                events = []
                for _id, data in entries:
                    events.append(json.loads(data["data"]))
                return list(reversed(events))
            except Exception:
                pass
        return self._memory_stream.get_recent(count)

    async def close(self):
        if self._redis:
            await self._redis.close()
