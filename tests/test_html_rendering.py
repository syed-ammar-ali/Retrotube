"""Comprehensive integration tests verifying HTML page rendering for all main routes."""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import main


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.asyncio
async def test_get_home_page():
    transport = ASGITransport(app=main.app)
    with patch("main.get_featured", new_callable=AsyncMock) as mock_feat:
        mock_feat.return_value = []
        with patch("main.tag_cloud", new_callable=AsyncMock) as mock_tags:
            mock_tags.return_value = [{"name": "music", "size": 3}]
            with patch("main.watched_now", new_callable=AsyncMock) as mock_watch:
                mock_watch.return_value = []
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    resp = await ac.get("/")
                    assert resp.status_code == 200
                    assert "<title>RetroTube" in resp.text
                    assert "What's New" in resp.text


@pytest.mark.asyncio
async def test_get_categories_page():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/categories")
        assert resp.status_code == 200
        assert "Browse Videos by Category" in resp.text
        assert "Comedy" in resp.text
        assert "Autos &amp; Vehicles" in resp.text


@pytest.mark.asyncio
async def test_get_timemachine_page():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/timemachine")
        assert resp.status_code == 200
        assert "Time Machine" in resp.text
        assert "2006" in resp.text
        assert "2016" in resp.text


@pytest.mark.asyncio
async def test_get_help_page():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/help")
        assert resp.status_code == 200
        assert "RetroTube Help" in resp.text
        assert "What is RetroTube?" in resp.text


@pytest.mark.asyncio
async def test_get_auth_pages():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login_resp = await ac.get("/login")
        assert login_resp.status_code == 200
        assert "Member Login" in login_resp.text

        reg_resp = await ac.get("/register")
        assert reg_resp.status_code == 200
        assert "Sign Up for a free RetroTube account" in reg_resp.text


@pytest.mark.asyncio
async def test_error_page_rendering():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/non_existent_page_12345")
        assert resp.status_code == 404
        assert "Not Found" in resp.text
        assert "Back to the home page" in resp.text


@pytest.mark.asyncio
async def test_healthz_endpoint():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "app": "RetroTube"}
