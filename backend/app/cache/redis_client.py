import json
from typing import Any
import redis.asyncio as aioredis
from app.config import settings

class RedisClient:
    def __init__(self):
        self._client: aioredis.Redis | None = None

    async def connect(self):
        self._client = aioredis.from_url(settings.redis_url, decode_responses=True)

    async def disconnect(self):
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> aioredis.Redis:
        if not self._client:
            raise RuntimeError("Redis not connected")
        return self._client

    async def set(self, key: str, value: Any, ttl: int | None = None):
        data = json.dumps(value) if not isinstance(value, str) else value
        if ttl:
            await self.client.setex(key, ttl, data)
        else:
            await self.client.set(key, data)

    async def get(self, key: str) -> Any | None:
        data = await self.client.get(key)
        if data is None:
            return None
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return data

    async def delete(self, key: str):
        await self.client.delete(key)

    async def exists(self, key: str) -> bool:
        return bool(await self.client.exists(key))

    async def publish(self, channel: str, message: Any):
        data = json.dumps(message) if not isinstance(message, str) else message
        await self.client.publish(channel, data)

    async def incr(self, key: str) -> int:
        return await self.client.incr(key)

    async def expire(self, key: str, seconds: int):
        await self.client.expire(key, seconds)

    async def keys(self, pattern: str) -> list[str]:
        return await self.client.keys(pattern)

    async def rpush(self, key: str, *values: str) -> int:
        return await self.client.rpush(key, *values)

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        return await self.client.lrange(key, start, end)

    async def acquire_lock(self, key: str, ttl: int = 240) -> bool:
        return bool(await self.client.set(key, "1", nx=True, ex=ttl))

    async def release_lock(self, key: str):
        await self.client.delete(key)

redis_client = RedisClient()
