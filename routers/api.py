"""JSON API routes for search, video metadata, and rating submission."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.rate_limit import rate_limit
from core.security import check_csrf, current_user, require_user
from database import get_db
from models import LocalRating
from services.youtube import VIDEO_ID_RE

router = APIRouter(prefix="/api", tags=["api"])


class RateIn(BaseModel):
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    stars: int = Field(ge=1, le=5)


@router.get("/search")
async def api_search(
    request: Request,
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1, le=5),
    year: Optional[int] = Query(None),
    order: str = Query("relevance"),
):
    """Search videos and return paginated JSON results."""
    # Import deferred to avoid circular dependency
    import main
    q = q.strip()
    if not q and not year:
        raise HTTPException(400, "Provide q and/or year")
    main.clean_era(year, order)
    await rate_limit(request, "search", 30, 60)
    return await main.do_search(request.app, q, page, year, order)


@router.get("/video/{video_id}")
async def api_video(
    video_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Retrieve full video metadata including calculated star scores."""
    import main
    if not VIDEO_ID_RE.match(video_id):
        raise HTTPException(404, "Video not found")
    user = await current_user(request, db)
    payload = await main.build_video_payload(request.app, db, video_id, user, log=True)
    return JSONResponse(payload)


@router.post("/rate")
async def api_rate(
    body: RateIn, request: Request, db: AsyncSession = Depends(get_db)
):
    """Submit a 1-5 star user rating for a video."""
    import main
    check_csrf(request, request.headers.get("X-CSRF-Token"))
    user = require_user(await current_user(request, db))
    await rate_limit(request, "rate", 60, 60, ident=user.id)
    if not await main.fetch_videos(request.app, [body.video_id]):
        raise HTTPException(404, "Video not found")

    stmt = pg_insert(LocalRating).values(
        user_id=user.id, video_id=body.video_id, stars=body.stars
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_rating_user_video",
        set_={"stars": stmt.excluded.stars, "updated_at": func.now()},
    )
    await db.execute(stmt)
    await db.commit()

    avg, cnt = (
        await db.execute(
            select(func.avg(LocalRating.stars), func.count(LocalRating.id)).where(
                LocalRating.video_id == body.video_id
            )
        )
    ).one()
    return {
        "ok": True,
        "stars": body.stars,
        "local_avg": round(float(avg), 2) if avg is not None else None,
        "local_count": cnt,
    }
