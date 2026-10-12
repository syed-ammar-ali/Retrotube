"""User action routes: comments, favorites, channel profile customization, and watch history."""
from datetime import datetime, timezone
import re
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.rate_limit import rate_limit
from core.security import check_csrf, current_user, require_user, safe_bg_url
from database import get_db
from models import Favorite, LocalComment, WatchHistory
from services.youtube import VIDEO_ID_RE

router = APIRouter(tags=["user_actions"])

COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


@router.post("/comment")
async def post_comment(
    request: Request,
    csrf: str = Form(""),
    video_id: str = Form(""),
    body: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Post a local comment on a video."""
    check_csrf(request, csrf)
    user = require_user(await current_user(request, db))
    await rate_limit(request, "comment", 10, 60, ident=user.id)
    body = body.strip()
    if not VIDEO_ID_RE.match(video_id) or not (1 <= len(body) <= 500):
        raise HTTPException(400, "Comments must be 1-500 characters")

    db.add(LocalComment(user_id=user.id, video_id=video_id, body=body))
    await db.commit()
    return RedirectResponse(f"/watch?v={video_id}#comments", status_code=303)


@router.post("/favorite")
async def toggle_favorite(
    request: Request,
    csrf: str = Form(""),
    video_id: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Toggle adding or removing a video from personal favorites."""
    import main
    check_csrf(request, csrf)
    user = require_user(await current_user(request, db))
    if not VIDEO_ID_RE.match(video_id):
        raise HTTPException(400, "Bad video id")

    existing = (
        await db.execute(
            select(Favorite).where(
                Favorite.user_id == user.id, Favorite.video_id == video_id
            )
        )
    ).scalar_one_or_none()

    if existing:
        await db.execute(delete(Favorite).where(Favorite.id == existing.id))
    else:
        vids = await main.fetch_videos(request.app, [video_id])
        if not vids:
            raise HTTPException(404, "Video not found")
        v = vids[0]
        db.add(
            Favorite(
                user_id=user.id,
                video_id=video_id,
                title=v["title"][:300],
                channel=v["channel"][:200],
                thumbnail=v["thumb"][:500],
            )
        )
    await db.commit()
    return RedirectResponse(f"/watch?v={video_id}", status_code=303)


@router.post("/profile/theme")
async def update_theme(
    request: Request,
    csrf: str = Form(""),
    bg_color: str = Form(""),
    bg_url: str = Form(""),
    about: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Update personal channel theme background and about text."""
    check_csrf(request, csrf)
    user = require_user(await current_user(request, db))
    theme = {}
    if bg_color.strip():
        if not COLOR_RE.match(bg_color.strip()):
            raise HTTPException(400, "Color must look like #A1B2C3")
        theme["bg_color"] = bg_color.strip()
    if bg_url.strip():
        clean = safe_bg_url(bg_url.strip())
        if not clean:
            raise HTTPException(400, "Wallpaper must be a plain https:// image URL")
        theme["bg_url"] = clean

    user.profile_theme = theme
    user.about = about.strip()[:1000]
    await db.commit()
    return RedirectResponse(f"/profile/{user.username}", status_code=303)


@router.post("/profile/bulletin")
async def post_bulletin(
    request: Request,
    csrf: str = Form(""),
    body: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Post an announcement bulletin on user's channel."""
    check_csrf(request, csrf)
    user = require_user(await current_user(request, db))
    body = body.strip()
    if not (1 <= len(body) <= 500):
        raise HTTPException(400, "Bulletins must be 1-500 characters")

    entry = {
        "body": body,
        "created_at": datetime.now(timezone.utc).strftime("%b %d, %Y"),
    }
    user.bulletins = [entry] + list(user.bulletins or [])[:9]
    await db.commit()
    return RedirectResponse(f"/profile/{user.username}", status_code=303)


@router.post("/history/clear")
async def clear_history(
    request: Request, csrf: str = Form(""), db: AsyncSession = Depends(get_db)
):
    """Clear all personal watch history."""
    check_csrf(request, csrf)
    user = require_user(await current_user(request, db))
    await db.execute(delete(WatchHistory).where(WatchHistory.user_id == user.id))
    await db.commit()
    return RedirectResponse("/history", status_code=303)
