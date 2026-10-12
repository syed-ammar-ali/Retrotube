"""Redis-backed sliding window rate limiter."""
from typing import Any

from fastapi import HTTPException, Request


async def rate_limit(
    request: Request,
    bucket: str,
    limit: int,
    window: int,
    ident: Any | None = None,
) -> None:
    """Enforce request limits within a time window per IP or user ID."""
    redis = getattr(request.app.state, "redis", None)
    if not redis:
        return
    client_ident = ident or (request.client.host if request.client else "anon")
    key = f"rl:{bucket}:{client_ident}"
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window)
        if count > limit:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Slow down a little.",
            )
    except HTTPException:
        raise
    except Exception:
        # If Redis encounters a transient failure, do not block the user
        pass
