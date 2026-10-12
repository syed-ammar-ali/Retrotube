"""Comprehensive automated tests for Phase 3: Cache, Quota, YouTube & RYD services."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from services.cache import SEARCH_TTL, cache_delete, cache_get, cache_set
from services.quota import quota_cost, quota_key, spend_quota
from services.ryd import fetch_ryd, star_rating
from services.youtube import fetch_videos, fmt_duration, normalize_video


# ======================================================== Step 3.1: Cache Tests
@pytest.mark.asyncio
async def test_cache_primitives():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = '{"test": 123}'

    val = await cache_get(mock_redis, "key1")
    assert val == {"test": 123}
    mock_redis.get.assert_awaited_once_with("key1")

    await cache_set(mock_redis, "key2", {"a": "b"}, SEARCH_TTL)
    mock_redis.set.assert_awaited_once_with("key2", '{"a": "b"}', ex=SEARCH_TTL)

    await cache_delete(mock_redis, "key3")
    mock_redis.delete.assert_awaited_once_with("key3")


# ======================================================== Step 3.2: Quota Tests
def test_quota_costs():
    assert quota_cost("search") == 100
    assert quota_cost("videos") == 1
    assert quota_cost("unknown") == 1


def test_quota_key_format():
    key = quota_key()
    assert key.startswith("quota:")
    # Must look like quota:YYYY-MM-DD
    parts = key.split(":")
    assert len(parts) == 2
    assert len(parts[1].split("-")) == 3


@pytest.mark.asyncio
async def test_spend_quota_within_budget():
    mock_redis = AsyncMock()
    mock_redis.incrby.return_value = 500

    used = await spend_quota(mock_redis, 100, budget=1000)
    assert used == 500
    mock_redis.incrby.assert_awaited_once()
    mock_redis.expire.assert_awaited_once()


@pytest.mark.asyncio
async def test_spend_quota_circuit_breaker_trips():
    mock_redis = AsyncMock()
    mock_redis.incrby.return_value = 9500  # Exceeds budget of 9000

    with pytest.raises(HTTPException) as exc_info:
        await spend_quota(mock_redis, 100, budget=9000)

    assert exc_info.value.status_code == 503
    assert "RetroTube has reached today's YouTube API budget allowance" in exc_info.value.detail
    # Must rollback increment
    mock_redis.decrby.assert_awaited_once()


# ====================================================== Step 3.3: YouTube Tests
def test_fmt_duration_variations():
    assert fmt_duration("PT4M37S") == "04:37"
    assert fmt_duration("PT1H2M3S") == "1:02:03"
    assert fmt_duration("PT45S") == "00:45"
    assert fmt_duration("P1DT2H3M4S") == "26:03:04"
    assert fmt_duration("invalid") == ""


def test_normalize_video():
    raw_item = {
        "id": "dQw4w9WgXcQ",
        "snippet": {
            "title": "Rick Astley - Never Gonna Give You Up",
            "channelTitle": "RickAstleyVEVO",
            "channelId": "UCuAXFkgsw1L7xaCfnd5JJOw",
            "description": "The official video",
            "publishedAt": "2009-10-25T06:57:33Z",
            "categoryId": "10",
            "tags": ["Rick Astley", "80s", "Pop"],
            "thumbnails": {
                "default": {"url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg"}
            },
        },
        "contentDetails": {"duration": "PT3M33S"},
        "statistics": {"viewCount": "1400000000"},
    }
    v = normalize_video(raw_item)
    assert v["id"] == "dQw4w9WgXcQ"
    assert v["title"] == "Rick Astley - Never Gonna Give You Up"
    assert v["duration"] == "03:33"
    assert v["views"] == 1400000000
    assert v["category"] == "Music"
    assert v["year"] == 2009


@pytest.mark.asyncio
async def test_fetch_videos_with_cache_hit_and_miss(mocker):
    mock_redis = AsyncMock()
    mock_redis.incrby.return_value = 1
    # First ID is cached, second is missing
    mock_redis.get.side_effect = lambda k: '{"id": "vid00000001", "title": "Cached"}' if "vid00000001" in k else None

    mock_http = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "items": [
            {
                "id": "vid00000002",
                "snippet": {"title": "Fetched", "publishedAt": "2007-01-01T00:00:00Z"},
                "contentDetails": {"duration": "PT1M00S"},
                "statistics": {"viewCount": "100"},
            }
        ]
    }
    mock_http.get.return_value = mock_response

    results = await fetch_videos(
        mock_http, mock_redis, ["vid00000001", "vid00000002"], api_key="fake-key", budget=9000
    )

    assert len(results) == 2
    assert results[0]["id"] == "vid00000001"
    assert results[1]["id"] == "vid00000002"
    mock_http.get.assert_awaited_once()


# ========================================================== Step 3.4: RYD Tests
def test_star_rating_formula():
    assert star_rating(900, 100) == 4.6
    assert star_rating(100, 0) == 5.0
    assert star_rating(0, 100) == 1.0
    assert star_rating(50, 50) == 3.0
    assert star_rating(0, 0) is None
    assert star_rating(None, 10) is None


@pytest.mark.asyncio
async def test_fetch_ryd_success():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_redis.incr.return_value = 1

    mock_http = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"likes": 900, "dislikes": 100}
    mock_http.get.return_value = mock_resp

    data = await fetch_ryd(mock_http, mock_redis, "dQw4w9WgXcQ")
    assert data["stars"] == 4.6
    assert data["likes"] == 900
    assert data["dislikes"] == 100


@pytest.mark.asyncio
async def test_fetch_ryd_fallback_on_429():
    mock_redis = AsyncMock()
    # Stale cache present
    mock_redis.get.return_value = '{"stars": 4.2, "likes": 500, "dislikes": 100, "at": 1000}'
    mock_redis.incr.return_value = 1

    mock_http = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_http.get.return_value = mock_resp

    data = await fetch_ryd(mock_http, mock_redis, "dQw4w9WgXcQ")
    # Returns the stale cached rating gracefully
    assert data["stars"] == 4.2
