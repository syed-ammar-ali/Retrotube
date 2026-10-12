"""Return YouTube Dislike (RYD) integration and 5-star rating converter."""
import time
from typing import Any

import httpx

from services.cache import RYD_FRESH, RYD_KEEP, cache_get, cache_set

RYD_URL = "https://returnyoutubedislikeapi.com/votes"
RYD_PER_MINUTE = 90
RYD_PER_DAY = 9000
RYD_PAGE_TIMEOUT = 6.0


def star_rating(likes: int | None, dislikes: int | None) -> float | None:
    """Convert likes and estimated dislikes into a classic 1.0 - 5.0 star score."""
    if likes is None or dislikes is None:
        return None
    total = likes + dislikes
    if total <= 0:
        return None
    ratio = likes / total
    score = 1.0 + 4.0 * ratio
    return round(max(1.0, min(5.0, score)), 1)


async def ryd_allowed(redis: Any) -> bool:
    """Check if client is within RYD rate limits (90/min, 9,000/day)."""
    if not redis:
        return True
    now = int(time.time())
    minute_key = f"ryd:m:{now // 60}"
    day_key = f"ryd:d:{now // 86400}"
    try:
        m = await redis.incr(minute_key)
        if m == 1:
            await redis.expire(minute_key, 70)
        d = await redis.incr(day_key)
        if d == 1:
            await redis.expire(day_key, 90000)
        return (m <= RYD_PER_MINUTE) and (d <= RYD_PER_DAY)
    except Exception:
        return True


async def fetch_ryd(http_client: httpx.AsyncClient, redis: Any, video_id: str) -> dict:
    """Fetch like/dislike counts from RYD, computing stars with fallback caching."""
    key = f"ryd:{video_id}"
    cached = await cache_get(redis, key) if redis else None
    now = time.time()

    # Serve fresh cache immediately (under 3 days old)
    if cached and (now - cached.get("at", 0) < RYD_FRESH):
        return cached

    # Check client-side rate limits before calling external service
    if not await ryd_allowed(redis):
        return cached or {}

    try:
        resp = await http_client.get(
            RYD_URL,
            params={"videoId": video_id},
            timeout=RYD_PAGE_TIMEOUT,
        )
    except httpx.HTTPError:
        return cached or {}

    if resp.status_code == 429:
        # Respect rate limit response from RYD; fall back to stale cache
        return cached or {}

    if resp.status_code >= 400:
        return cached or {}

    data = resp.json()
    likes = data.get("likes")
    dislikes = data.get("dislikes")
    score = star_rating(likes, dislikes)
    ratings_total = (likes or 0) + (dislikes or 0)

    payload = {
        "likes": likes,
        "dislikes": dislikes,
        "stars": score,
        "ratings_total": ratings_total,
        "at": now,
    }

    if redis:
        await cache_set(redis, key, payload, RYD_KEEP)

    return payload
