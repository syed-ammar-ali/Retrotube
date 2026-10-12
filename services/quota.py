"""Pacific Time YouTube Quota Engine and circuit breaker."""
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException

# Quota unit weights enforced by YouTube Data API v3
QUOTA_COSTS = {
    "search": 100,
    "videos": 1,
}


def quota_cost(endpoint: str) -> int:
    """Return the YouTube quota unit cost for a given API endpoint."""
    return QUOTA_COSTS.get(endpoint, 1)


def quota_key(dt: datetime = None) -> str:
    """Generate quota key based on Pacific Time date (matching Google's midnight reset)."""
    if dt is None:
        try:
            dt = datetime.now(ZoneInfo("America/Los_Angeles"))
        except Exception:
            from datetime import timedelta, timezone
            dt = datetime.now(timezone(timedelta(hours=-8)))
    return f"quota:{dt.strftime('%Y-%m-%d')}"


async def quota_used(redis: Any) -> int:
    """Get the total YouTube quota units spent so far today in Pacific Time."""
    if not redis:
        return 0
    try:
        val = await redis.get(quota_key())
        return int(val or 0)
    except Exception:
        return 0


async def spend_quota(redis: Any, cost: int, budget: int) -> int:
    """Atomically record quota usage and trip circuit breaker if exceeding daily budget."""
    if not redis:
        return cost
    key = quota_key()
    try:
        used = int(await redis.incrby(key, cost))
        await redis.expire(key, 172800)  # 48 hours TTL
    except Exception:
        return cost

    if used > budget:
        # Roll back the increment so repeated failed queries don't artificially inflate count
        try:
            await redis.decrby(key, cost)
        except Exception:
            pass
        raise HTTPException(
            status_code=503,
            detail=(
                "RetroTube has reached today's YouTube API budget allowance. "
                "Pages you've already visited continue to work from cache; "
                "new searches become available after midnight Pacific Time."
            ),
        )
    return used
