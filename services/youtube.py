"""YouTube Data API v3 integration with batching, quota tracking, and caching."""
import hashlib
import re
from datetime import datetime
from typing import Any

import httpx
from fastapi import HTTPException

from services.cache import VIDEO_TTL, cache_get, cache_set
from services.quota import spend_quota

YT_BASE = "https://www.googleapis.com/youtube/v3"
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
PAGE_SIZE = 10
MAX_PAGES = 5
SEARCH_FETCH = MAX_PAGES * PAGE_SIZE  # 50 results per search call

CATEGORIES = [
    ("2", "Autos & Vehicles"), ("23", "Comedy"), ("24", "Entertainment"),
    ("1", "Film & Animation"), ("20", "Gadgets & Games"), ("26", "Howto & DIY"),
    ("10", "Music"), ("25", "News & Politics"), ("22", "People & Blogs"),
    ("15", "Pets & Animals"), ("17", "Sports"), ("19", "Travel & Places"),
]
CATEGORY_NAMES = {
    **dict(CATEGORIES), "27": "Education", "28": "Science & Technology",
    "29": "Nonprofits & Activism", "30": "Movies", "21": "Videoblogging",
}


def fmt_duration(iso: str) -> str:
    """Format ISO 8601 duration (e.g. PT4M37S) into classic MM:SS or HH:MM:SS."""
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", iso or "")
    if not m:
        return ""
    d, h, mi, s = (int(x or 0) for x in m.groups())
    h += d * 24
    return f"{h}:{mi:02d}:{s:02d}" if h else f"{mi:02d}:{s:02d}"


def normalize_video(item: dict) -> dict:
    """Convert a raw YouTube API item into RetroTube's 2006-07 data model."""
    sn = item.get("snippet", {})
    st = item.get("statistics", {})
    thumbs = sn.get("thumbnails", {})
    # The 120x90 'default' thumbnail maintains authentic 4:3 ratio with letterboxing
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


def search_cache_key(q: str, year: int | None, order: str, category: str | None = None, after: str | None = None) -> str:
    """Deterministic hash key for search query caching in Redis."""
    raw = f"{q.lower()}|{year}|{order}|{category}|{after}"
    return "search2:" + hashlib.sha1(raw.encode()).hexdigest()


async def fetch_videos(
    http_client: httpx.AsyncClient,
    redis: Any,
    ids: list[str],
    api_key: str,
    budget: int = 9000,
) -> list[dict]:
    """Fetch video metadata in 50-item batches (1 quota unit per call) with per-video caching."""
    valid_ids = [i for i in dict.fromkeys(ids) if VIDEO_ID_RE.match(i)]
    found: dict[str, dict] = {}
    missing: list[str] = []

    for vid in valid_ids:
        cached = await cache_get(redis, f"video2:{vid}")
        if cached:
            found[vid] = cached
        else:
            missing.append(vid)

    for start in range(0, len(missing), 50):
        chunk = missing[start : start + 50]
        await spend_quota(redis, 1, budget)
        try:
            resp = await http_client.get(
                f"{YT_BASE}/videos",
                params={
                    "part": "snippet,contentDetails,statistics",
                    "id": ",".join(chunk),
                    "key": api_key,
                },
            )
        except httpx.HTTPError:
            raise HTTPException(502, "Could not reach the YouTube API")

        if resp.status_code == 403:
            raise HTTPException(503, "YouTube API quota exhausted or invalid key")
        if resp.status_code >= 400:
            raise HTTPException(502, f"YouTube API error ({resp.status_code})")

        data = resp.json()
        for item in data.get("items", []):
            nv = normalize_video(item)
            found[nv["id"]] = nv
            await cache_set(redis, f"video2:{nv['id']}", nv, VIDEO_TTL)

    return [found[i] for i in valid_ids if i in found]
