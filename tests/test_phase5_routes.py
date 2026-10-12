"""Integration tests for Phase 5: API routes, authentication, and user actions."""

import pytest
from httpx import ASGITransport, AsyncClient

import main


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ========================================================== Step 5.1: API Tests
@pytest.mark.asyncio
async def test_api_search_missing_params():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/search")
        assert resp.status_code == 400
        assert "Provide q and/or year" in resp.text


@pytest.mark.asyncio
async def test_api_video_invalid_id():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/video/invalid_id!")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_api_rate_missing_csrf():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Without CSRF token, must be rejected with 403
        resp = await ac.post("/api/rate", json={"video_id": "vid00000001", "stars": 5})
        assert resp.status_code == 403


# ========================================================= Step 5.3: Auth Tests
@pytest.mark.asyncio
async def test_register_validation_errors():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Fetch form to acquire CSRF cookie & session
        get_resp = await ac.get("/register")
        assert get_resp.status_code == 200
        csrf_token = ac.cookies.get("csrf")

        # 2. Username too short
        resp = await ac.post(
            "/register",
            data={"csrf": csrf_token or "tok", "username": "ab", "password": "valid_password_123"},
            headers={"X-CSRF-Token": csrf_token or ""},
        )
        assert resp.status_code in (200, 403)
        if resp.status_code == 200:
            assert "Username must be 3-20 characters" in resp.text


# ================================================= Step 5.3: User Actions Tests
@pytest.mark.asyncio
async def test_comment_requires_auth():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Anonymous comment submission should fail auth
        resp = await ac.post(
            "/comment",
            data={"csrf": "tok", "video_id": "vid00000001", "body": "Great video!"},
        )
        # Missing CSRF or unauthorized
        assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_favorite_requires_auth():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/favorite",
            data={"csrf": "tok", "video_id": "vid00000001"},
        )
        assert resp.status_code in (401, 403)


# ============================================ Step 5.4: Milestones & Era Tests
def test_get_milestone_ids():
    from services.milestones import get_milestone_ids

    ids_2006 = get_milestone_ids(2006)
    assert len(ids_2006) >= 5
    assert "dMH0bHeiRNg" in ids_2006  # Evolution of Dance

    ids_2007 = get_milestone_ids(2007)
    assert "EwTZ2xpQwpA" in ids_2007  # Chocolate Rain
    assert "_OBlgSz8sSM" in ids_2007  # Charlie bit my finger


@pytest.mark.asyncio
async def test_categories_with_year_parameter():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/categories?y=2006")
        assert resp.status_code == 200
        assert "Browse Videos by Category (2006)" in resp.text
        assert "Time Machine Era:" in resp.text
        assert "href=\"/browse?s=mp&amp;t=a&amp;c=10&amp;y=2006\"" in resp.text


@pytest.mark.asyncio
async def test_skin_switcher():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/skin/2008?next=/browse", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/browse"


@pytest.mark.asyncio
async def test_random_warp():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/random", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"].startswith("/watch?v=")


@pytest.mark.asyncio
async def test_playlists_endpoint():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/playlists")
        assert resp.status_code == 200
        assert "Playlists &amp; Mixtapes" in resp.text


def test_video_honors_calculation():
    from main import calculate_video_honors

    mock_vid = {
        "id": "dQw4w9WgXcQ",
        "views": 10_000_000,
        "community_stars": 4.8,
        "category": "Music",
    }
    honors = calculate_video_honors(mock_vid, total_comments=50)
    assert len(honors) >= 2
    assert any("Most Viewed" in h["title"] for h in honors)
    assert any("Top Rated" in h["title"] for h in honors)


def test_rating_distribution_calculation():
    from main import calculate_rating_distribution

    dist = calculate_rating_distribution(likes=900, dislikes=100, local_avg=4.5, local_count=5)
    assert 5 in dist and 1 in dist
    assert dist[5]["pct"] > dist[1]["pct"]
    assert sum(dist[i]["pct"] for i in range(1, 6)) == 100

