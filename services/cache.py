"""Redis cache layer primitives and TTL constants."""
import json
from typing import Any

# TTL policies (YouTube policies cap stored API data at 30 days)
SEARCH_TTL: int = 3600              # Ordinary search queries (1 hour)
ERA_SEARCH_TTL: int = 7 * 86400     # Time Machine yearly searches (7 days)
VIDEO_TTL: int = 7 * 86400          # Individual video details (7 days)
RYD_FRESH: int = 3 * 86400          # Fresh Return YouTube Dislike stats (3 days)
RYD_KEEP: int = 30 * 86400          # Stale RYD fallback cache retention (30 days)


async def cache_get(redis: Any, key: str) -> Any | None:
    """Retrieve and deserialize a JSON-encoded value from Redis."""
    if not redis:
        return None
    try:
        raw = await redis.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def cache_set(redis: Any, key: str, value: Any, ttl: int) -> None:
    """Serialize and store a value in Redis with a specified TTL."""
    if not redis:
        return
    try:
        await redis.set(key, json.dumps(value), ex=ttl)
    except Exception:
        pass


async def cache_delete(redis: Any, key: str) -> None:
    """Delete a key from Redis."""
    if not redis:
        return
    try:
        await redis.delete(key)
    except Exception:
        pass
