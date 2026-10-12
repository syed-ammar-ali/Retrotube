"""Automated tests for Phase 7: Automation tools, cache warmer, and preview generator."""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from tools import preview
from warm_cache import warm

BASE_DIR = Path(__file__).resolve().parent.parent


@pytest.mark.asyncio
async def test_warm_cache_stops_at_budget(capsys):
    """Verify warm_cache stops immediately when current quota reaches or exceeds budget."""
    with patch("warm_cache.aioredis.from_url") as mock_from_url:
        mock_redis = AsyncMock()
        mock_from_url.return_value = mock_redis

        # Mock quota used returning 6000 (which is >= budget 5000)
        with patch("main.quota_used", new_callable=AsyncMock) as mock_quota:
            mock_quota.return_value = 6000
            with patch("main.cache_get", new_callable=AsyncMock) as mock_cache_get:
                mock_cache_get.return_value = None  # Cache miss

                await warm(budget=5000, stars_pages=0)

    captured = capsys.readouterr().out
    assert "Stopped at 6000 units used today (budget 5000)" in captured


@pytest.mark.asyncio
async def test_warm_cache_skips_already_cached(capsys):
    """Verify warm_cache skips lists that are already cached without spending quota."""
    with patch("warm_cache.aioredis.from_url") as mock_from_url:
        mock_redis = AsyncMock()
        mock_from_url.return_value = mock_redis

        with patch("main.quota_used", new_callable=AsyncMock) as mock_quota:
            mock_quota.return_value = 0
            with patch("main.cache_get", new_callable=AsyncMock) as mock_cache_get:
                # Return dummy cached list
                mock_cache_get.return_value = [{"id": "vid00000001", "title": "Test"}]

                with patch("main.fetch_search_results", new_callable=AsyncMock) as mock_fetch:
                    mock_fetch.return_value = [{"id": "vid00000001"}]
                    await warm(budget=9000, stars_pages=0)

    captured = capsys.readouterr().out
    assert "Done. Warmed 0 new lists" in captured


def test_preview_render_all_pages():
    """Verify that preview.py renders HTML strings for all 13 defined pages."""
    for name in preview.PAGES:
        html = preview.render(name)
        assert "<!DOCTYPE html>" in html
        assert "Retro" in html
