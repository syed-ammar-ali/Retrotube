"""RetroTube backend: FastAPI metadata proxy + local nostalgia engine.

Playback is the official YouTube IFrame embed. This server never proxies or
extracts streams; it only fetches metadata (YouTube Data API v3) and optional
dislike estimates (Return YouTube Dislike), caching both in Redis.
"""
import asyncio
import hashlib
import json
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo
from urllib.parse import urlencode, urlparse

import httpx
import redis.asyncio as aioredis
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import delete, desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from database import SessionLocal, engine
from models import (
    Base, Favorite, LocalComment, LocalRating, User, WatchHistory,
    VideoResponse, Playlist, PlaylistItem,
)
from services.milestones import get_milestone_ids, get_all_milestone_ids

# ----------------------------------------------------------------- config
from config import get_settings

_settings = get_settings()
BASE_DIR = Path(__file__).parent
YT_API_KEY = _settings.YT_API_KEY
SECRET_KEY = _settings.SECRET_KEY
REDIS_URL = _settings.REDIS_URL
FEATURED_REGION = _settings.FEATURED_REGION
ENABLE_RELATED = _settings.ENABLE_RELATED
HTTPS_ONLY = _settings.HTTPS_ONLY

YT_BASE = "https://www.googleapis.com/youtube/v3"
RYD_URL = "https://returnyoutubedislikeapi.com/votes"
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
TAG_RE = re.compile(r"^[\w\- ]{2,24}$")

# YouTube's policies (III.E.4) cap how long API data may be stored at 30 days,
# so every TTL on YouTube-sourced data stays well under that.
SEARCH_TTL = 3600                 # ordinary searches
ERA_SEARCH_TTL = 7 * 86400        # Time Machine pages barely change; refresh weekly
VIDEO_TTL = 7 * 86400
# Return YouTube Dislike (third party; its own limits are 100/minute and 10,000/day
# per client, and clients must back off on a 429). Estimates are refreshed after
# RYD_FRESH, but an older one is still served if RYD is slow or down.
RYD_FRESH = 3 * 86400
RYD_KEEP = 30 * 86400
RYD_PER_MINUTE = 90
RYD_PER_DAY = 9000
RYD_PAGE_TIMEOUT = 6              # never hold a page longer than this waiting for stars
# Stop spending quota past this many units per Pacific-time day (default quota: 10,000).
YT_DAILY_BUDGET = _settings.YT_DAILY_BUDGET
MAX_PAGES = 5
PAGE_SIZE = 10
SEARCH_FETCH = MAX_PAGES * PAGE_SIZE  # 50 = the most search.list returns per call
COMMENTS_PER_PAGE = 20
FAVS_PER_PAGE = 12
HISTORY_PER_PAGE = 20
ERAS = list(range(2006, 2017))  # Time Machine covers 2006-2016, nothing else
ORDERS = {  # search-result sort links, worded like the original site
    "relevance": "Relevance",
    "date": "Date Added",
    "viewCount": "View Count",
    "rating": "Rating",
}

# The 2006-2007 category list, mapped onto today's YouTube category ids.
CATEGORIES = [
    ("2", "Autos & Vehicles"), ("23", "Comedy"), ("24", "Entertainment"),
    ("1", "Film & Animation"), ("20", "Gadgets & Games"), ("26", "Howto & DIY"),
    ("10", "Music"), ("25", "News & Politics"), ("22", "People & Blogs"),
    ("15", "Pets & Animals"), ("17", "Sports"), ("19", "Travel & Places"),
]
BROWSE_CATEGORY_IDS = {cid for cid, _ in CATEGORIES}
# Blurb and tag links per category page entry.
CATEGORY_INFO = {
    "2": ("Cars, bikes, tuning and crashes: everything with an engine.", ["cars", "drift", "motorcycle", "racing"]),
    "23": ("Sketches, stand-up, pranks and the silly stuff you forward to friends.", ["funny", "prank", "standup", "sketch"]),
    "24": ("Trailers, TV clips, celebrities and pop culture.", ["tv", "trailer", "celebrity", "show"]),
    "1": ("Short films, cartoons, movie scenes and animation.", ["film", "cartoon", "anime", "short"]),
    "20": ("Game footage, walkthroughs, gadgets and tech toys.", ["games", "gadget", "console", "review"]),
    "26": ("Tutorials, tips and do-it-yourself projects.", ["howto", "diy", "tutorial", "tips"]),
    "10": ("Music videos, live shows, covers and bedroom bands.", ["music", "live", "cover", "band"]),
    "25": ("Headlines, speeches, debates and citizen reports.", ["news", "politics", "debate", "report"]),
    "22": ("Video blogs, everyday life and people being themselves.", ["vlog", "life", "friends", "blog"]),
    "15": ("Cats, dogs and every other animal doing something cute.", ["cat", "dog", "cute", "animals"]),
    "17": ("Highlights, tricks, matches and extreme stunts.", ["sports", "skate", "soccer", "stunts"]),
    "19": ("Trips, landmarks, cities and the road in between.", ["travel", "city", "beach", "trip"]),
}
# Names for the category shown on a watch page (includes ones added after 2007).
CATEGORY_NAMES = {
    **dict(CATEGORIES), "27": "Education", "28": "Science & Technology",
    "29": "Nonprofits & Activism", "30": "Movies", "21": "Videoblogging",
}
# /browse?s=<sort>&t=<time> mirrors the original site's URL scheme.
BROWSE_SORTS = {
    "mp": ("viewCount", "Most Viewed"),
    "tr": ("rating", "Top Rated"),
    "mr": ("date", "Most Recent"),
}
BROWSE_TIMES = {
    "t": ("Today", 1), "w": ("This Week", 7), "m": ("This Month", 30), "a": ("All Time", None),
}

SEED_TAGS = [
    "music", "funny", "cats", "skateboarding", "anime", "guitar", "news", "gaming",
    "dance", "comedy", "trailer", "tutorial", "science", "cars", "soccer",
    "animation", "live", "remix", "documentary", "cooking",
]

ph = PasswordHasher()


# ------------------------------------------------------------------- app
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    app.state.http = httpx.AsyncClient(timeout=10)
    async with engine.begin() as conn:  # dev convenience; use Alembic in production
        await conn.run_sync(Base.metadata.create_all)
    yield
    await app.state.http.aclose()
    await app.state.redis.aclose()
    await engine.dispose()


app = FastAPI(title="RetroTube", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    same_site="lax",
    https_only=HTTPS_ONLY,
    max_age=14 * 24 * 3600,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["commas"] = lambda n: f"{int(n or 0):,}"


def ago(iso: str) -> str:
    """'20 years ago' style relative date, like the original site."""
    try:
        dt = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    days = (datetime.now(timezone.utc) - dt).days
    if days >= 365:
        n = days // 365
        return f"{n} year{'s' if n != 1 else ''} ago"
    if days >= 30:
        n = days // 30
        return f"{n} month{'s' if n != 1 else ''} ago"
    if days >= 1:
        return f"{days} day{'s' if days != 1 else ''} ago"
    return "today"


templates.env.filters["ago"] = ago
# Stored favorites/history may hold larger thumbnails; always show the 120x90 one.
_THUMB_RE = re.compile(r"/(?:mq|hq|sd|maxres)?default(?:_live)?\.jpg")
templates.env.filters["thumb120"] = lambda u: _THUMB_RE.sub("/default.jpg", u or "")
templates.env.globals["ERAS"] = ERAS
templates.env.globals["CATEGORIES"] = CATEGORIES


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    return templates.TemplateResponse(
        request, "error.html",
        {"user": None, "csrf": "", "status": exc.status_code, "message": exc.detail, "active_tab": ""},
        status_code=exc.status_code, headers=exc.headers,
    )


async def get_db():
    async with SessionLocal() as session:
        yield session


# ------------------------------------------------------- session / csrf
async def current_user(request: Request, db: AsyncSession) -> Optional[User]:
    uid = request.session.get("uid")
    return await db.get(User, uid) if uid else None


def get_csrf(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    return request.session["csrf"]


def check_csrf(request: Request, token: Optional[str]) -> None:
    expected = request.session.get("csrf")
    if not expected or not token or not secrets.compare_digest(expected, token):
        raise HTTPException(403, "Invalid or missing CSRF token")


def require_user(user: Optional[User]) -> User:
    if user is None:
        raise HTTPException(401, "Please sign in first")
    return user


def render(request: Request, name: str, user: Optional[User], **ctx):
    skin = request.session.get("skin", "2006")
    ctx.update(user=user, csrf=get_csrf(request), skin=skin)
    return templates.TemplateResponse(request, name, ctx)


async def rate_limit(request: Request, bucket: str, limit: int, window: int, ident=None):
    ident = ident or (request.client.host if request.client else "anon")
    r = request.app.state.redis
    key = f"rl:{bucket}:{ident}"
    n = await r.incr(key)
    if n == 1:
        await r.expire(key, window)
    if n > limit:
        raise HTTPException(429, "Too many requests. Slow down a little.")


# ------------------------------------------------------------- cache utils
async def cache_get(app, key):
    raw = await app.state.redis.get(key)
    return json.loads(raw) if raw else None


async def cache_set(app, key, value, ttl):
    await app.state.redis.set(key, json.dumps(value), ex=ttl)


# ----------------------------------------------------------- YouTube layer
def quota_cost(endpoint: str) -> int:
    return 100 if endpoint == "search" else 1


def quota_key() -> str:
    # YouTube's daily quota resets at midnight Pacific time.
    return "quota:" + datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


async def quota_used(app) -> int:
    return int(await app.state.redis.get(quota_key()) or 0)


async def spend_quota(app, cost: int) -> None:
    r = app.state.redis
    key = quota_key()
    used = await r.incrby(key, cost)
    await r.expire(key, 172800)
    if used > YT_DAILY_BUDGET:
        await r.decrby(key, cost)
        raise HTTPException(
            503,
            "RetroTube has used up today's YouTube allowance. Pages you've already "
            "visited still work; new searches come back after midnight Pacific time.",
        )


async def yt_get(app, endpoint: str, params: dict) -> dict:
    await spend_quota(app, quota_cost(endpoint))
    try:
        resp = await app.state.http.get(
            f"{YT_BASE}/{endpoint}", params={**params, "key": YT_API_KEY}
        )
    except httpx.HTTPError:
        raise HTTPException(502, "Could not reach the YouTube API")
    if resp.status_code == 403:
        raise HTTPException(503, "YouTube API quota exhausted or key rejected")
    if resp.status_code >= 400:
        raise HTTPException(502, f"YouTube API error ({resp.status_code})")
    return resp.json()


def fmt_duration(iso: str) -> str:
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", iso or "")
    if not m:
        return ""
    d, h, mi, s = (int(x or 0) for x in m.groups())
    h += d * 24
    return f"{h}:{mi:02d}:{s:02d}" if h else f"{mi:02d}:{s:02d}"


def normalize_video(item: dict) -> dict:
    sn = item.get("snippet", {})
    st = item.get("statistics", {})
    thumbs = sn.get("thumbnails", {})
    # The 120x90 "default" thumbnail is 4:3 with black bars on widescreen videos,
    # which is exactly how thumbnails looked in 2006.
    thumb = (thumbs.get("default") or thumbs.get("medium") or {}).get("url", "")
    iso = sn.get("publishedAt", "")
    try:
        pub_dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        published, year = pub_dt.strftime("%B %d, %Y"), pub_dt.year
    except ValueError:
        published, year = "", None
    return {
        "id": item["id"],
        "title": sn.get("title", "(untitled)"),
        "channel": sn.get("channelTitle", ""),
        "channel_id": sn.get("channelId", ""),
        "description": re.sub(r"\n{3,}", "\n\n", (sn.get("description") or "").strip())[:500],
        "published": published,
        "published_iso": iso,
        "year": year,
        "duration": fmt_duration(item.get("contentDetails", {}).get("duration", "")),
        "views": int(st.get("viewCount", 0) or 0),
        "thumb": thumb,
        "tags": (sn.get("tags") or [])[:12],
        "category_id": sn.get("categoryId", ""),
        "category": CATEGORY_NAMES.get(sn.get("categoryId", ""), ""),
    }


async def fetch_videos(app, ids: list) -> list:
    """videos.list for many ids (1 quota unit per call), cached per video."""
    ids = [i for i in dict.fromkeys(ids) if VIDEO_ID_RE.match(i)]
    found, missing = {}, []
    for i in ids:
        cached = await cache_get(app, f"video2:{i}")
        if cached:
            found[i] = cached
        else:
            missing.append(i)
    for start in range(0, len(missing), 50):
        chunk = missing[start:start + 50]
        data = await yt_get(
            app, "videos",
            {"part": "snippet,contentDetails,statistics", "id": ",".join(chunk)},
        )
        for item in data.get("items", []):
            nv = normalize_video(item)
            found[nv["id"]] = nv
            await cache_set(app, f"video2:{nv['id']}", nv, VIDEO_TTL)
    return [found[i] for i in ids if i in found]


def search_cache_key(q: str, year, order: str, category=None, after=None) -> str:
    raw = f"{q.lower()}|{year}|{order}|{category}|{after}"
    return "search2:" + hashlib.sha1(raw.encode()).hexdigest()


async def fetch_search_results(
    app, q: str, year=None, order="relevance", category=None, after=None
) -> list:
    """One search.list call (100 units) returns up to 50 videos; do_search slices
    them into 5 pages of 10 locally. YouTube pages by token, so fetching page by
    page used to cost N calls for page N (page 5 = 500 units); now every page of
    a query costs the same single call, plus 1 unit for videos.list."""
    key = search_cache_key(q, year, order, category, after)
    cached = await cache_get(app, key)
    if cached is not None:
        return cached
    params = {
        "part": "snippet", "type": "video", "order": order,
        "maxResults": SEARCH_FETCH, "safeSearch": "moderate",
        "videoEmbeddable": "true",  # playback is via the official embed only
    }
    if q:
        params["q"] = q
    if year:  # Time Machine: only videos published during that calendar year
        params["publishedAfter"] = f"{year}-01-01T00:00:00Z"
        params["publishedBefore"] = f"{year + 1}-01-01T00:00:00Z"
    elif after:  # Today / This Week / This Month on the Videos tab (YYYY-MM-DD)
        params["publishedAfter"] = f"{after}T00:00:00Z"
    if category:
        params["videoCategoryId"] = category
    data = await yt_get(app, "search", params)
    ids = [i["id"]["videoId"] for i in data.get("items", [])]
    videos = await fetch_videos(app, ids)
    await cache_set(app, key, videos, ERA_SEARCH_TTL if year else SEARCH_TTL)
    return videos


async def peek_search_results(app, q, year, order="viewCount", category=None, after=None):
    """Cache-only lookup: never spends quota. Returns None if not cached."""
    return await cache_get(app, search_cache_key(q, year, order, category, after))


def clean_era(year, order):
    if year is not None and year not in ERAS:
        raise HTTPException(400, f"year must be one of {ERAS}")
    if order not in ORDERS:
        raise HTTPException(400, "unknown sort order")
    return year, order


async def do_search(
    app, q: str, page: int, year=None, order="relevance", category=None, after=None
) -> dict:
    everything = await fetch_search_results(app, q, year, order, category, after)
    total_pages = min(MAX_PAGES, max(1, -(-len(everything) // PAGE_SIZE)))
    start = (page - 1) * PAGE_SIZE
    chunk = everything[start:start + PAGE_SIZE]
    if q and page == 1 and not year and everything and TAG_RE.match(q.lower()):
        r = app.state.redis
        await r.zincrby("popular_searches", 1, q.lower())
        await r.zremrangebyrank("popular_searches", 0, -501)  # keep top 500
    return {
        "query": q,
        "page": page,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "videos": await attach_stars(app, chunk),  # stars only for the 10 on screen
        "year": year,
        "order": order,
    }


async def get_featured(app) -> list:
    raw = await cache_get(app, "featured")
    if not raw:
        data = await yt_get(
            app, "videos",
            {
                "part": "snippet,contentDetails,statistics", "chart": "mostPopular",
                "maxResults": 16, "regionCode": FEATURED_REGION,
            },
        )
        raw = [normalize_video(i) for i in data.get("items", [])]
        if raw:
            await cache_set(app, "featured", raw, SEARCH_TTL)
    # Stars are attached per request (cheap cache reads) so they never go stale
    # inside the cached list.
    return await attach_stars(app, raw)


async def get_era_milestones(app, year: int) -> list:
    """Fetch and cache metadata for the curated viral milestones of an era."""
    cache_key = f"milestones:{year}"
    cached = await cache_get(app, cache_key)
    if cached is not None:
        return await attach_stars(app, cached)

    ids = get_milestone_ids(year)
    if not ids:
        return []
    videos = await fetch_videos(app, ids)
    if videos:
        await cache_set(app, cache_key, videos, ERA_SEARCH_TTL)
    return await attach_stars(app, videos)


async def ryd_allowed(app) -> bool:
    """Keep ourselves under RYD's published limits (100/minute, 10,000/day) and
    honour a 429 by pausing all lookups for a minute."""
    r = app.state.redis
    if await r.get("rydctl:backoff"):
        return False
    minute_key = f"rydctl:min:{int(time.time() // 60)}"
    n = await r.incr(minute_key)
    if n == 1:
        await r.expire(minute_key, 120)
    if n > RYD_PER_MINUTE:
        return False
    day_key = "rydctl:day:" + time.strftime("%Y-%m-%d", time.gmtime())
    d = await r.incr(day_key)
    if d == 1:
        await r.expire(day_key, 172800)
    return d <= RYD_PER_DAY


async def fetch_ryd(app, vid: str) -> dict:
    """Likes/dislikes estimate for a video: fresh cache -> live lookup -> stale
    cache -> empty. A slow or failing RYD therefore only ever costs a refresh,
    never a missing star score for a video we've seen before."""
    r = app.state.redis
    key = f"ryd:{vid}"
    entry = await cache_get(app, key)
    if entry and time.time() - entry.get("at", 0) < RYD_FRESH:
        return entry
    fallback = entry or {"likes": None, "dislikes": None}
    if await r.get(f"rydneg:{vid}") or not await ryd_allowed(app):
        return fallback
    try:
        resp = await app.state.http.get(RYD_URL, params={"videoId": vid}, timeout=5)
    except httpx.HTTPError:
        await r.set(f"rydneg:{vid}", 1, ex=300)  # retry in 5 minutes
        return fallback
    if resp.status_code == 429:
        await r.set("rydctl:backoff", 1, ex=60)
        return fallback
    try:
        data = resp.json() if resp.status_code == 200 else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        await r.set(f"rydneg:{vid}", 1, ex=300 if resp.status_code != 404 else 21600)
        return fallback
    fresh = {"likes": data.get("likes"), "dislikes": data.get("dislikes"), "at": time.time()}
    await cache_set(app, key, fresh, RYD_KEEP)
    return fresh


async def attach_stars(app, videos: list) -> list:
    """Give each video its converted 5-star score, like the original thumbnails.
    Looked up concurrently; anything that isn't back within RYD_PAGE_TIMEOUT is
    left blank (stars=None) rather than holding the page up."""
    if not videos:
        return []
    sem = asyncio.Semaphore(5)

    async def one(v):
        async with sem:
            ryd = await fetch_ryd(app, v["id"])
        n = (ryd.get("likes") or 0) + (ryd.get("dislikes") or 0)
        return star_rating(ryd.get("likes"), ryd.get("dislikes")), n

    tasks = [asyncio.create_task(one(v)) for v in videos]
    done, pending = await asyncio.wait(tasks, timeout=RYD_PAGE_TIMEOUT)
    for t in pending:
        t.cancel()
    out = []
    for v, t in zip(videos, tasks):
        ok = t in done and not t.cancelled() and t.exception() is None
        st, n = t.result() if ok else (None, 0)
        out.append({**v, "stars": st, "ratings": n})
    return out


async def watched_now(db: AsyncSession, limit: int = 8) -> list:
    """'Videos Being Watched Now': anonymous, site-wide recent plays (no usernames)."""
    rows = (
        await db.execute(
            select(
                WatchHistory.video_id,
                func.max(WatchHistory.title),
                func.max(WatchHistory.channel),
                func.max(WatchHistory.thumbnail),
                func.max(WatchHistory.watched_at).label("t"),
            )
            .group_by(WatchHistory.video_id)
            .order_by(desc("t"))
            .limit(limit)
        )
    ).all()
    return [
        {"id": r[0], "title": r[1], "channel": r[2], "thumb": r[3]} for r in rows
    ]


async def tag_cloud(app) -> list:
    top = await app.state.redis.zrevrange("popular_searches", 0, 29, withscores=True)
    scores = {t: s for t, s in top}
    # NOTE: user-entered terms appear here; add a blocklist before going public.
    for seed in SEED_TAGS:
        if len(scores) >= 30:
            break
        scores.setdefault(seed, 1.0)
    lo, hi = min(scores.values()), max(scores.values())
    tags = []
    for name, s in sorted(scores.items()):
        size = 1 if hi == lo else 1 + round(4 * (s - lo) / (hi - lo))
        tags.append({"name": name, "size": size})
    return tags


# ------------------------------------------------------- rating formula
def star_rating(likes, dislikes) -> Optional[float]:
    """Star Rating = 1 + 4 * (Likes / (Likes + Dislikes))"""
    if likes is None or dislikes is None or likes + dislikes <= 0:
        return None
    return round(1 + 4 * (likes / (likes + dislikes)), 2)


def calculate_video_honors(video: dict, total_comments: int) -> list:
    v_hash = int(hashlib.md5(video["id"].encode()).hexdigest()[:8], 16)
    views = int(video.get("views") or 0)
    stars = video.get("community_stars") or video.get("display_stars") or 3.5
    cat_name = video.get("category") or "Entertainment"
    honors = []

    if views > 5_000_000:
        rank = (v_hash % 10) + 1
        honors.append({"rank": rank, "title": "Most Viewed (All Time)"})
    elif views > 200_000:
        rank = (v_hash % 15) + 1
        honors.append({"rank": rank, "title": "Most Viewed (This Month)"})
    else:
        rank = (v_hash % 20) + 1
        honors.append({"rank": rank, "title": "Most Viewed (This Week)"})

    if stars >= 4.0:
        rank = ((v_hash >> 3) % 15) + 1
        honors.append({"rank": rank, "title": f"Top Rated ({cat_name})"})
    elif stars >= 3.0:
        rank = ((v_hash >> 3) % 25) + 5
        honors.append({"rank": rank, "title": "Top Rated (This Month)"})

    if total_comments >= 1:
        rank = ((v_hash >> 6) % 20) + 1
        honors.append({"rank": rank, "title": "Most Discussed (This Week)"})

    rank_fav = ((v_hash >> 9) % 25) + 1
    honors.append({"rank": rank_fav, "title": "Top Favorited (All Time)"})

    return honors[:4]


def calculate_rating_distribution(likes: Optional[int], dislikes: Optional[int], local_avg: Optional[float], local_count: int) -> dict:
    l = likes or 0
    d = dislikes or 0
    tot = l + d
    if tot == 0:
        if local_count > 0:
            tot = local_count
            l = int(tot * ((local_avg or 4.0) / 5.0))
            d = tot - l
        else:
            tot = 100
            l = 85
            d = 15
    ratio = l / max(1, tot)
    p5 = int(round(ratio * 76))
    p4 = int(round(ratio * 18))
    p3 = int(round(ratio * 6))
    p2 = int(round((1 - ratio) * 30))
    p1 = max(0, 100 - (p5 + p4 + p3 + p2))
    return {
        5: {"pct": p5, "count": int(round(tot * (p5 / 100)))},
        4: {"pct": p4, "count": int(round(tot * (p4 / 100)))},
        3: {"pct": p3, "count": int(round(tot * (p3 / 100)))},
        2: {"pct": p2, "count": int(round(tot * (p2 / 100)))},
        1: {"pct": p1, "count": int(round(tot * (p1 / 100)))},
        "total": tot,
    }


async def get_channel_friends(db: AsyncSession, exclude_user_id: int) -> list:
    rows = (await db.execute(select(User).where(User.id != exclude_user_id).limit(8))).scalars().all()
    friends = [{"username": u.username, "joined": u.joined_at.strftime("%Y")} for u in rows]
    preset_retro = [
        "smosh", "lonelygirl15", "xX_EmoGoth_Xx", "geriatric1927", "Brookers",
        "chad_hurley", "steve_chen", "tspoon"
    ]
    for p in preset_retro:
        if len(friends) >= 8:
            break
        friends.append({"username": p, "joined": "2006"})
    return friends[:8]


# ------------------------------------------------------- profile styling
def safe_bg_url(url: str) -> Optional[str]:
    if not url or len(url) > 500 or re.search(r"[\s\"'()<>\\]", url):
        return None
    p = urlparse(url)
    return url if p.scheme == "https" and p.netloc else None


def wallpaper_css(theme: dict) -> str:
    parts = []
    color = theme.get("bg_color", "")
    if COLOR_RE.match(color or ""):
        parts.append(f"background-color:{color};")
    url = safe_bg_url(theme.get("bg_url", ""))
    if url:
        parts.append(f'background-image:url("{url}");')
    return "".join(parts)


# ------------------------------------------------------ video aggregation
async def log_history(db: AsyncSession, user: User, v: dict) -> None:
    last = (
        await db.execute(
            select(WatchHistory)
            .where(WatchHistory.user_id == user.id)
            .order_by(desc(WatchHistory.watched_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if last and last.video_id == v["id"]:  # refresh spam collapses into one row
        last.watched_at = now
    else:
        db.add(
            WatchHistory(
                user_id=user.id, video_id=v["id"], title=v["title"][:300],
                channel=v["channel"][:200], thumbnail=v["thumb"][:500], watched_at=now,
            )
        )
    await db.commit()


async def build_video_payload(app, db, vid, user=None, log=False) -> dict:
    vids = await fetch_videos(app, [vid])
    if not vids:
        raise HTTPException(404, "Video not found")
    v = dict(vids[0])
    ryd = await fetch_ryd(app, vid)
    community = star_rating(ryd.get("likes"), ryd.get("dislikes"))
    avg, cnt = (
        await db.execute(
            select(func.avg(LocalRating.stars), func.count(LocalRating.id)).where(
                LocalRating.video_id == vid
            )
        )
    ).one()
    user_stars, is_fav = None, False
    if user:
        user_stars = (
            await db.execute(
                select(LocalRating.stars).where(
                    LocalRating.user_id == user.id, LocalRating.video_id == vid
                )
            )
        ).scalar_one_or_none()
        is_fav = (
            await db.execute(
                select(Favorite.id).where(
                    Favorite.user_id == user.id, Favorite.video_id == vid
                )
            )
        ).scalar_one_or_none() is not None
        if log:
            await log_history(db, user, v)
    local_avg = round(float(avg), 2) if avg is not None else None
    v.update(
        embed_url=f"https://www.youtube.com/embed/{vid}?rel=0&playsinline=1",
        embed_code=(
            f'<iframe width="425" height="350" src="https://www.youtube.com/embed/{vid}" '
            'frameborder="0" allowfullscreen></iframe>'
        ),
        likes=ryd.get("likes"),
        dislikes=ryd.get("dislikes"),
        ratings_total=(
            ryd["likes"] + ryd["dislikes"]
            if ryd.get("likes") is not None and ryd.get("dislikes") is not None
            else None
        ),
        community_stars=community,
        local_avg=local_avg,
        local_count=cnt,
        user_stars=user_stars,
        # A member's own rating overrides the converted community score for them.
        display_stars=user_stars or community or local_avg or 0,
        is_favorite=is_fav,
    )
    return v


# ============================================================ JSON API
@app.get("/api/search")
async def api_search(
    request: Request,
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1, le=MAX_PAGES),
    year: Optional[int] = Query(None),
    order: str = Query("relevance"),
):
    q = q.strip()
    if not q and not year:
        raise HTTPException(400, "Provide q and/or year")
    clean_era(year, order)
    await rate_limit(request, "search", 30, 60)
    return await do_search(request.app, q, page, year, order)


@app.get("/api/video/{video_id}")
async def api_video(
    video_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    if not VIDEO_ID_RE.match(video_id):
        raise HTTPException(404, "Video not found")
    user = await current_user(request, db)
    payload = await build_video_payload(request.app, db, video_id, user, log=True)
    return JSONResponse(payload)


class RateIn(BaseModel):
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    stars: int = Field(ge=1, le=5)


@app.post("/api/rate")
async def api_rate(
    body: RateIn, request: Request, db: AsyncSession = Depends(get_db)
):
    check_csrf(request, request.headers.get("X-CSRF-Token"))
    user = require_user(await current_user(request, db))
    await rate_limit(request, "rate", 60, 60, ident=user.id)
    if not await fetch_videos(request.app, [body.video_id]):
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
    return {"ok": True, "stars": body.stars, "local_avg": round(float(avg), 2), "local_count": cnt}


@app.get("/healthz", tags=["health"])
async def healthz():
    """Health check endpoint for container orchestration and load balancers."""
    return {"status": "ok", "app": "RetroTube"}


# ======================================================== HTML pages
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: AsyncSession = Depends(get_db)):
    user = await current_user(request, db)
    try:
        videos = await get_featured(request.app)
    except HTTPException:
        videos = []
    tags = await tag_cloud(request.app)
    watching = await watched_now(db)
    return render(
        request, "index.html", user,
        videos=videos, tags=tags, watching=watching, active_tab="home",
    )


@app.get("/results", response_class=HTMLResponse)
async def results(
    request: Request,
    search_query: str = Query("", max_length=100),
    page: int = Query(1, ge=1, le=MAX_PAGES),
    year: str = Query("", max_length=4),
    order: str = Query("", max_length=12),
    db: AsyncSession = Depends(get_db),
):
    q = search_query.strip()
    year_i = int(year) if year.isdigit() else None
    if not q and not year_i:
        return RedirectResponse("/", status_code=303)
    if not q and year_i:  # year-only browsing lives on /browse now
        s = {"rating": "tr", "date": "mr"}.get(order, "mp")
        return RedirectResponse(f"/browse?s={s}&t=a&y={year_i}", status_code=303)
    order = order or ("viewCount" if year_i and not q else "relevance")
    clean_era(year_i, order)
    await rate_limit(request, "search", 30, 60)
    user = await current_user(request, db)
    data = await do_search(request.app, q, page, year_i, order)

    def href(o: str, with_page: bool = False) -> str:
        p = {"search_query": q, "order": o}
        if year_i:
            p["year"] = year_i
        return "/results?" + urlencode(p) + ("&page=" if with_page else "")

    sorts = [
        {"key": k, "label": v, "href": href(k)}
        for k, v in ORDERS.items()
        if q or k != "relevance"
    ]
    return render(
        request, "results.html", user,
        q=q, year=year_i, order=order, orders=ORDERS, sorts=sorts,
        data=data, base=href(order, True),
        active_tab="timemachine" if year_i and not q else "videos",
    )


@app.get("/watch", response_class=HTMLResponse)
async def watch(
    request: Request,
    v: str = Query(...),
    cp: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    if not VIDEO_ID_RE.match(v):
        raise HTTPException(404, "Video not found")
    user = await current_user(request, db)
    video = await build_video_payload(request.app, db, v, user, log=True)

    total_comments = (
        await db.execute(
            select(func.count(LocalComment.id)).where(LocalComment.video_id == v)
        )
    ).scalar_one()
    comments = (
        await db.execute(
            select(LocalComment.body, LocalComment.created_at, User.username)
            .join(User, User.id == LocalComment.user_id)
            .where(LocalComment.video_id == v)
            .order_by(desc(LocalComment.created_at))
            .limit(COMMENTS_PER_PAGE)
            .offset((cp - 1) * COMMENTS_PER_PAGE)
        )
    ).all()
    comment_pages = max(1, -(-total_comments // COMMENTS_PER_PAGE))

    history = []
    if user:
        rows = (
            await db.execute(
                select(WatchHistory)
                .where(WatchHistory.user_id == user.id, WatchHistory.video_id != v)
                .order_by(desc(WatchHistory.watched_at))
                .limit(8)
            )
        ).scalars()
        history = [
            {"id": h.video_id, "title": h.title, "thumb": h.thumbnail, "channel": h.channel}
            for h in rows
        ]

    # "More Videos from <year>": free, read straight from the Time Machine cache.
    era_videos = []
    if video.get("year") in ERAS:
        cached = await peek_search_results(request.app, "", video["year"], "viewCount")
        era_videos = [x for x in (cached or []) if x["id"] != v][:6]

    related = []
    if ENABLE_RELATED:
        query = " ".join(video["title"].split()[:5])
        related = [
            x for x in (await do_search(request.app, query, 1))["videos"] if x["id"] != v
        ][:6]

    # Honors & Rating Breakdown
    honors = calculate_video_honors(video, total_comments)
    ratings_breakdown = calculate_rating_distribution(
        video.get("likes"), video.get("dislikes"), video.get("local_avg"), video.get("local_count", 0)
    )

    # Video Responses
    responses = (
        await db.execute(
            select(VideoResponse)
            .where(VideoResponse.parent_video_id == v)
            .order_by(desc(VideoResponse.created_at))
            .limit(12)
        )
    ).scalars().all()

    # User Playlists for "Add to Playlist"
    user_playlists = []
    if user:
        user_playlists = (
            await db.execute(
                select(Playlist).where(Playlist.user_id == user.id).order_by(Playlist.title)
            )
        ).scalars().all()

    return render(
        request, "watch.html", user,
        video=video, comments=comments, total_comments=total_comments,
        cp=cp, comment_pages=comment_pages, comment_base=f"/watch?v={v}&cp=",
        history=history, related=related, era_videos=era_videos,
        era_year=video.get("year"), honors=honors, ratings_breakdown=ratings_breakdown,
        video_responses=responses, user_playlists=user_playlists,
        active_tab="videos",
    )


@app.get("/profile/{username}", response_class=HTMLResponse)
async def profile(
    request: Request,
    username: str,
    fp: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    me = await current_user(request, db)
    target = (
        await db.execute(select(User).where(User.username_lower == username.lower()))
    ).scalar_one_or_none()
    if not target:
        raise HTTPException(404, "No such channel")

    async def count(model):
        return (
            await db.execute(select(func.count(model.id)).where(model.user_id == target.id))
        ).scalar_one()

    fav_total = await count(Favorite)
    favs = (
        await db.execute(
            select(Favorite)
            .where(Favorite.user_id == target.id)
            .order_by(desc(Favorite.added_at))
            .limit(FAVS_PER_PAGE)
            .offset((fp - 1) * FAVS_PER_PAGE)
        )
    ).scalars()
    favorites = [
        {"id": f.video_id, "title": f.title, "thumb": f.thumbnail, "channel": f.channel}
        for f in favs
    ]
    top_friends = await get_channel_friends(db, target.id)
    playlists = (
        await db.execute(
            select(Playlist).where(Playlist.user_id == target.id).order_by(desc(Playlist.created_at)).limit(6)
        )
    ).scalars().all()
    return render(
        request, "profile.html", me,
        target=target,
        is_owner=bool(me and me.id == target.id),
        wallpaper=wallpaper_css(target.profile_theme or {}),
        favorites=favorites,
        fav_total=fav_total,
        fav_pages=max(1, -(-fav_total // FAVS_PER_PAGE)),
        fp=fp,
        fav_base=f"/profile/{target.username}?fp=",
        comment_count=await count(LocalComment),
        rating_count=await count(LocalRating),
        top_friends=top_friends,
        playlists=playlists,
        active_tab="channel" if me and me.id == target.id else "",
    )


# ---------------------------------------------------- auth (forms)
# ------------------------------------------- browse / categories / community
def browse_href(s, t, c, y, page=None) -> str:
    p = {"s": s, "t": t}
    if c:
        p["c"] = c
    if y:
        p["y"] = y
    if page:
        p["page"] = page
    return "/browse?" + urlencode(p)


@app.get("/browse", response_class=HTMLResponse)
async def browse(
    request: Request,
    s: str = Query("mp", max_length=2),
    t: str = Query("a", max_length=1),
    c: str = Query("", max_length=3),
    y: str = Query("", max_length=4),
    page: int = Query(1, ge=1, le=MAX_PAGES),
    db: AsyncSession = Depends(get_db),
):
    s = s if s in BROWSE_SORTS else "mp"
    t = t if t in BROWSE_TIMES else "a"
    cat = c if c in BROWSE_CATEGORY_IDS else ""
    year_i = int(y) if y.isdigit() else None
    if year_i is not None and year_i not in ERAS:
        raise HTTPException(400, f"Pick a year between {ERAS[0]} and {ERAS[-1]}.")
    await rate_limit(request, "search", 30, 60)
    user = await current_user(request, db)

    order, sort_label = BROWSE_SORTS[s]
    days = BROWSE_TIMES[t][1]
    after = None
    if days and not year_i:
        after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    data = await do_search(request.app, "", page, year_i, order, cat or None, after)

    sort_links = [
        {"label": lbl, "href": browse_href(k, t, cat, year_i), "active": k == s}
        for k, (_, lbl) in BROWSE_SORTS.items()
    ]
    time_links = [] if year_i else [
        {"label": lbl, "href": browse_href(s, k, cat, None), "active": k == t}
        for k, (lbl, _) in BROWSE_TIMES.items()
    ]
    year_links = [
        {"label": str(yr), "href": browse_href(s, "a", cat, yr), "active": yr == year_i}
        for yr in ERAS
    ] if year_i else []
    cat_name = CATEGORY_NAMES.get(cat, "")
    cat_links = [{"label": "All", "href": browse_href(s, t, "", year_i), "active": not cat}] + [
        {"label": nm, "href": browse_href(s, t, cid, year_i), "active": cid == cat}
        for cid, nm in CATEGORIES
    ]
    rail_years = [
        {"label": str(yr), "href": browse_href(s, "a", cat, yr), "active": yr == year_i}
        for yr in ERAS
    ]
    heading = f"{sort_label} : ({str(year_i) if year_i else BROWSE_TIMES[t][0]}) : {cat_name or 'All'}"
    middle = f"{cat_name} " if cat_name else ""
    title = (
        f"{sort_label} {middle}Videos of {year_i}" if year_i
        else f"{sort_label} {middle}Videos - {BROWSE_TIMES[t][0]}"
    )
    milestones = []
    if year_i and page == 1 and not cat:
        try:
            milestones = await get_era_milestones(request.app, year_i)
        except Exception:
            milestones = []

    return render(
        request, "browse.html", user,
        title=title, data=data, sort_links=sort_links, time_links=time_links,
        year_links=year_links, cat_name=cat_name, cat_links=cat_links,
        rail_years=rail_years, heading=heading, year_i=year_i, cat=cat,
        milestones=milestones,
        base=browse_href(s, t, cat, year_i) + "&page=",
        active_tab="timemachine" if year_i else ("categories" if cat else "videos"),
    )


@app.get("/categories", response_class=HTMLResponse)
async def categories(
    request: Request, y: Optional[str] = Query(None), db: AsyncSession = Depends(get_db)
):
    user = await current_user(request, db)
    year_i = int(y) if y and y.isdigit() and int(y) in ERAS else None
    return render(
        request, "categories.html", user,
        categories=CATEGORIES, info=CATEGORY_INFO,
        year=year_i, eras=ERAS, active_tab="categories",
    )


@app.get("/channels", response_class=HTMLResponse)
async def channels(request: Request, db: AsyncSession = Depends(get_db)):
    user = await current_user(request, db)
    rows = (
        await db.execute(
            select(User.username, User.joined_at, User.about)
            .order_by(desc(User.joined_at))
            .limit(30)
        )
    ).all()
    return render(request, "channels.html", user, members=rows, active_tab="channels")


@app.get("/community", response_class=HTMLResponse)
async def community(request: Request, db: AsyncSession = Depends(get_db)):
    user = await current_user(request, db)
    rows = (
        await db.execute(
            select(LocalComment.body, LocalComment.created_at, LocalComment.video_id, User.username)
            .join(User, User.id == LocalComment.user_id)
            .order_by(desc(LocalComment.created_at))
            .limit(15)
        )
    ).all()
    titles = {}
    if rows:
        try:  # one videos.list call (1 unit), mostly served from cache
            titles = {v["id"]: v["title"] for v in await fetch_videos(request.app, [r.video_id for r in rows])}
        except HTTPException:
            pass
    comments = [
        {
            "user": r.username, "body": r.body, "when": r.created_at.isoformat(),
            "video_id": r.video_id, "title": titles.get(r.video_id, "a video"),
        }
        for r in rows
    ]
    members = (
        await db.execute(select(User.username).order_by(desc(User.joined_at)).limit(10))
    ).scalars().all()
    return render(request, "community.html", user, comments=comments, members=members, active_tab="community")


@app.get("/help", response_class=HTMLResponse)
async def help_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await current_user(request, db)
    return render(request, "help.html", user, active_tab="")


# ------------------------------------------- time machine / history pages
@app.get("/timemachine", response_class=HTMLResponse)
async def timemachine(request: Request, db: AsyncSession = Depends(get_db)):
    user = await current_user(request, db)
    return render(request, "timemachine.html", user, eras=ERAS, active_tab="timemachine")


@app.get("/history", response_class=HTMLResponse)
async def history_page(
    request: Request, hp: int = Query(1, ge=1), db: AsyncSession = Depends(get_db)
):
    user = await current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    total = (
        await db.execute(
            select(func.count(WatchHistory.id)).where(WatchHistory.user_id == user.id)
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(WatchHistory)
            .where(WatchHistory.user_id == user.id)
            .order_by(desc(WatchHistory.watched_at))
            .limit(HISTORY_PER_PAGE)
            .offset((hp - 1) * HISTORY_PER_PAGE)
        )
    ).scalars()
    items = [
        {
            "id": h.video_id, "title": h.title, "thumb": h.thumbnail,
            "channel": h.channel, "watched": h.watched_at.strftime("%B %d, %Y"),
        }
        for h in rows
    ]
    return render(
        request, "history.html", user,
        items=items, total=total, page=hp,
        pages=max(1, -(-total // HISTORY_PER_PAGE)), base="/history?hp=", active_tab="",
    )


@app.post("/history/clear")
async def clear_history(
    request: Request, csrf: str = Form(""), db: AsyncSession = Depends(get_db)
):
    check_csrf(request, csrf)
    user = require_user(await current_user(request, db))
    await db.execute(delete(WatchHistory).where(WatchHistory.user_id == user.id))
    await db.commit()
    return RedirectResponse("/history", status_code=303)


@app.api_route("/register", methods=["GET", "POST"], response_class=HTMLResponse)
async def register(
    request: Request,
    csrf: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    user = await current_user(request, db)
    if request.method == "GET":
        return render(request, "auth.html", user, mode="register", error=None, active_tab="")
    check_csrf(request, csrf)
    await rate_limit(request, "register", 10, 3600)
    username = username.strip()
    error = None
    if not USERNAME_RE.match(username):
        error = "Username must be 3-20 characters: letters, numbers, underscore."
    elif len(password) < 8 or len(password) > 128:
        error = "Password must be 8-128 characters."
    if error:
        return render(request, "auth.html", user, mode="register", error=error, active_tab="")
    hashed = await asyncio.to_thread(ph.hash, password)
    new = User(username=username, username_lower=username.lower(), password_hash=hashed)
    db.add(new)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return render(
            request, "auth.html", user, mode="register",
            error="That username is taken.", active_tab="",
        )
    request.session.clear()
    request.session["uid"] = new.id
    return RedirectResponse("/", status_code=303)


@app.api_route("/login", methods=["GET", "POST"], response_class=HTMLResponse)
async def login(
    request: Request,
    csrf: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    user = await current_user(request, db)
    if request.method == "GET":
        return render(request, "auth.html", user, mode="login", error=None, active_tab="")
    check_csrf(request, csrf)
    await rate_limit(request, "login", 10, 900)
    row = (
        await db.execute(select(User).where(User.username_lower == username.strip().lower()))
    ).scalar_one_or_none()
    ok = False
    if row:
        try:
            ok = await asyncio.to_thread(ph.verify, row.password_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            ok = False
    if not ok:
        return render(
            request, "auth.html", user, mode="login",
            error="Invalid username or password.", active_tab="",
        )
    request.session.clear()  # new session on login (prevents fixation)
    request.session["uid"] = row.id
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
async def logout(request: Request, csrf: str = Form("")):
    check_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# ------------------------------------------ comments / favorites / profile
@app.post("/comment")
async def post_comment(
    request: Request,
    csrf: str = Form(""),
    video_id: str = Form(""),
    body: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    check_csrf(request, csrf)
    user = require_user(await current_user(request, db))
    await rate_limit(request, "comment", 10, 60, ident=user.id)
    body = body.strip()
    if not VIDEO_ID_RE.match(video_id) or not (1 <= len(body) <= 500):
        raise HTTPException(400, "Comments must be 1-500 characters")
    db.add(LocalComment(user_id=user.id, video_id=video_id, body=body))
    await db.commit()
    return RedirectResponse(f"/watch?v={video_id}#comments", status_code=303)


@app.post("/favorite")
async def toggle_favorite(
    request: Request,
    csrf: str = Form(""),
    video_id: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    check_csrf(request, csrf)
    user = require_user(await current_user(request, db))
    if not VIDEO_ID_RE.match(video_id):
        raise HTTPException(400, "Bad video id")
    existing = (
        await db.execute(
            select(Favorite).where(Favorite.user_id == user.id, Favorite.video_id == video_id)
        )
    ).scalar_one_or_none()
    if existing:
        await db.execute(delete(Favorite).where(Favorite.id == existing.id))
    else:
        vids = await fetch_videos(request.app, [video_id])
        if not vids:
            raise HTTPException(404, "Video not found")
        v = vids[0]
        db.add(
            Favorite(
                user_id=user.id, video_id=video_id, title=v["title"][:300],
                channel=v["channel"][:200], thumbnail=v["thumb"][:500],
            )
        )
    await db.commit()
    return RedirectResponse(f"/watch?v={video_id}", status_code=303)


@app.post("/profile/theme")
async def update_theme(
    request: Request,
    csrf: str = Form(""),
    bg_color: str = Form(""),
    bg_url: str = Form(""),
    about: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
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


@app.post("/profile/bulletin")
async def post_bulletin(
    request: Request,
    csrf: str = Form(""),
    body: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    check_csrf(request, csrf)
    user = require_user(await current_user(request, db))
    body = body.strip()
    if not (1 <= len(body) <= 500):
        raise HTTPException(400, "Bulletins must be 1-500 characters")
    entry = {"body": body, "created_at": datetime.now(timezone.utc).strftime("%b %d, %Y")}
    user.bulletins = [entry] + list(user.bulletins or [])[:9]  # reassign to flag change
    await db.commit()
    return RedirectResponse(f"/profile/{user.username}", status_code=303)


@app.get("/skin/{era}")
async def switch_skin(request: Request, era: str, next: str = "/"):
    if era in ("2006", "2008", "2009"):
        request.session["skin"] = era
    dest = next
    if dest == "/":
        ref = request.headers.get("referer")
        if ref:
            p = urlparse(ref).path
            if p.startswith("/") and not p.startswith("//"):
                dest = p
    if not dest.startswith("/") or dest.startswith("//"):
        dest = "/"
    return RedirectResponse(dest, status_code=303)


@app.get("/random")
@app.get("/lucky")
async def random_warp(request: Request):
    milestones = get_all_milestone_ids()
    chosen = secrets.choice(milestones) if milestones else "dQw4w9WgXcQ"
    return RedirectResponse(f"/watch?v={chosen}", status_code=303)


@app.post("/video-response")
async def post_video_response(
    request: Request,
    csrf: str = Form(""),
    parent_video_id: str = Form(...),
    response_video_input: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    check_csrf(request, csrf)
    user = require_user(await current_user(request, db))
    resp_vid = response_video_input.strip()
    m = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11})", resp_vid)
    if m:
        resp_vid = m.group(1)
    if not VIDEO_ID_RE.match(resp_vid):
        raise HTTPException(400, "Invalid YouTube video ID or link")
    if resp_vid == parent_video_id:
        raise HTTPException(400, "Video cannot respond to itself")
    vids = await fetch_videos(request.app, [resp_vid])
    if not vids:
        raise HTTPException(404, "Response video not found")
    resp_info = vids[0]
    vr = VideoResponse(
        parent_video_id=parent_video_id,
        response_video_id=resp_vid,
        title=resp_info["title"][:300],
        thumbnail=resp_info["thumb"][:500],
        user_id=user.id,
    )
    db.add(vr)
    await db.commit()
    return RedirectResponse(f"/watch?v={parent_video_id}", status_code=303)


# ----------------------------------------------------------- playlists
@app.get("/playlists", response_class=HTMLResponse)
async def playlists_list(request: Request, db: AsyncSession = Depends(get_db)):
    user = await current_user(request, db)
    query = (
        select(Playlist, User.username, func.count(PlaylistItem.id).label("item_count"))
        .join(User, User.id == Playlist.user_id)
        .outerjoin(PlaylistItem, PlaylistItem.playlist_id == Playlist.id)
        .group_by(Playlist.id, User.username)
        .order_by(desc(Playlist.created_at))
        .limit(30)
    )
    rows = (await db.execute(query)).all()
    playlists = [
        {
            "id": r[0].id,
            "title": r[0].title,
            "description": r[0].description,
            "created_at": r[0].created_at,
            "creator": r[1],
            "item_count": r[2],
        }
        for r in rows
    ]
    my_playlists = []
    if user:
        my_rows = (
            await db.execute(
                select(Playlist, func.count(PlaylistItem.id).label("item_count"))
                .outerjoin(PlaylistItem, PlaylistItem.playlist_id == Playlist.id)
                .where(Playlist.user_id == user.id)
                .group_by(Playlist.id)
                .order_by(desc(Playlist.created_at))
            )
        ).all()
        my_playlists = [
            {"id": r[0].id, "title": r[0].title, "description": r[0].description, "item_count": r[1]}
            for r in my_rows
        ]
    return render(
        request, "playlists.html", user,
        playlists=playlists, my_playlists=my_playlists, active_tab="playlists",
    )


@app.post("/playlist/create")
async def create_playlist(
    request: Request,
    csrf: str = Form(""),
    title: str = Form(""),
    description: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    check_csrf(request, csrf)
    user = require_user(await current_user(request, db))
    title = title.strip()
    if not (1 <= len(title) <= 100):
        raise HTTPException(400, "Title must be between 1 and 100 characters")
    pl = Playlist(
        user_id=user.id,
        title=title,
        description=description.strip()[:500],
    )
    db.add(pl)
    await db.commit()
    await db.refresh(pl)
    return RedirectResponse(f"/playlists/{pl.id}", status_code=303)


@app.post("/playlist/add")
async def add_to_playlist(
    request: Request,
    csrf: str = Form(""),
    playlist_id: int = Form(...),
    video_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    check_csrf(request, csrf)
    user = require_user(await current_user(request, db))
    if not VIDEO_ID_RE.match(video_id):
        raise HTTPException(400, "Invalid video ID")
    pl = await db.get(Playlist, playlist_id)
    if not pl or pl.user_id != user.id:
        raise HTTPException(404, "Playlist not found")

    vids = await fetch_videos(request.app, [video_id])
    if not vids:
        raise HTTPException(404, "Video not found")
    v_info = vids[0]

    existing = (
        await db.execute(
            select(PlaylistItem).where(
                PlaylistItem.playlist_id == playlist_id,
                PlaylistItem.video_id == video_id,
            )
        )
    ).scalar_one_or_none()
    if not existing:
        max_pos = (
            await db.execute(
                select(func.coalesce(func.max(PlaylistItem.position), 0))
                .where(PlaylistItem.playlist_id == playlist_id)
            )
        ).scalar_one()
        item = PlaylistItem(
            playlist_id=playlist_id,
            video_id=video_id,
            title=v_info["title"][:300],
            thumbnail=v_info["thumb"][:500],
            position=max_pos + 1,
        )
        db.add(item)
        await db.commit()
    return RedirectResponse(f"/playlists/{playlist_id}", status_code=303)


@app.get("/playlists/{playlist_id}", response_class=HTMLResponse)
async def view_playlist(
    request: Request,
    playlist_id: int,
    v: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    user = await current_user(request, db)
    pl = await db.get(Playlist, playlist_id)
    if not pl:
        raise HTTPException(404, "Playlist not found")
    owner = await db.get(User, pl.user_id)
    items = (
        await db.execute(
            select(PlaylistItem)
            .where(PlaylistItem.playlist_id == playlist_id)
            .order_by(PlaylistItem.position, PlaylistItem.id)
        )
    ).scalars().all()

    current_vid = v
    if not current_vid and items:
        current_vid = items[0].video_id

    next_vid = None
    if current_vid and items:
        for idx, it in enumerate(items):
            if it.video_id == current_vid and idx + 1 < len(items):
                next_vid = items[idx + 1].video_id
                break

    return render(
        request, "playlist_detail.html", user,
        playlist=pl, owner=owner, items=items,
        current_vid=current_vid, next_vid=next_vid,
        is_owner=bool(user and user.id == pl.user_id),
        active_tab="playlists",
    )


# RetroTube initialized

