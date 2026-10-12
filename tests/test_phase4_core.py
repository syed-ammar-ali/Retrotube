"""Automated tests for Phase 4: Core security, templating, and helpers."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from core.security import (
    check_csrf,
    get_csrf,
    hash_password,
    safe_bg_url,
    verify_password,
    wallpaper_css,
)
from core.templates import ago, templates


# ======================================================= Security & CSRF Tests
@pytest.mark.asyncio
async def test_password_hashing_and_verification():
    plain = "SuperSecretPassword123!"
    hashed = await hash_password(plain)
    assert hashed != plain
    assert hashed.startswith("$argon2id$")

    assert await verify_password(hashed, plain) is True
    assert await verify_password(hashed, "WrongPassword!") is False


def test_csrf_generation_and_validation():
    scope = {"type": "http", "session": {}}
    req = Request(scope)

    tok1 = get_csrf(req)
    assert len(tok1) >= 32
    # Consecutive calls return the same session token
    assert get_csrf(req) == tok1

    # Valid check passes without error
    check_csrf(req, tok1)

    # Invalid check raises 403
    with pytest.raises(HTTPException) as exc:
        check_csrf(req, "invalid_token_12345")
    assert exc.value.status_code == 403

    # None token raises 403
    with pytest.raises(HTTPException) as exc:
        check_csrf(req, None)
    assert exc.value.status_code == 403


def test_safe_bg_url_sanitization():
    assert safe_bg_url("https://example.com/bg.jpg") == "https://example.com/bg.jpg"
    assert safe_bg_url("https://cdn.retro.tv/img/pattern.png") == "https://cdn.retro.tv/img/pattern.png"
    assert safe_bg_url("https://site.org/photo.webp") == "https://site.org/photo.webp"

    # Insecure HTTP rejected
    assert safe_bg_url("http://insecure.com/bg.jpg") is None
    # Script execution rejected
    assert safe_bg_url("javascript:alert(1)") is None
    # Non-image files rejected
    assert safe_bg_url("https://malicious.org/script.js") is None
    assert safe_bg_url("https://evil.com/app.exe") is None


def test_wallpaper_css_generation():
    theme = {
        "bg_color": "#0033CC",
        "bg_url": "https://example.com/wall.jpg",
    }
    css = wallpaper_css(theme)
    assert "background-color: #0033CC;" in css
    assert "background-image: url('https://example.com/wall.jpg');" in css

    # Invalid bg_url ignored
    bad_theme = {"bg_color": "#112233", "bg_url": "javascript:void(0)"}
    bad_css = wallpaper_css(bad_theme)
    assert "background-color: #112233;" in bad_css
    assert "background-image" not in bad_css


# ===================================================== Template Filters Tests
def test_ago_filter():
    now = datetime.now(UTC)
    # Today
    assert ago(now.isoformat()) == "today"

    # Days ago
    three_days = (now - timedelta(days=3)).isoformat()
    assert ago(three_days) == "3 days ago"

    # Months ago
    two_months = (now - timedelta(days=65)).isoformat()
    assert ago(two_months) == "2 months ago"

    # Years ago
    two_years = (now - timedelta(days=740)).isoformat()
    assert ago(two_years) == "2 years ago"

    # Invalid input
    assert ago("") == ""
    assert ago(None) == ""


def test_commas_and_thumb_filters():
    commas_fn = templates.env.filters["commas"]
    assert commas_fn(1000) == "1,000"
    assert commas_fn(12345678) == "12,345,678"
    assert commas_fn(0) == "0"
    assert commas_fn(None) == "0"

    thumb_fn = templates.env.filters["thumb120"]
    assert thumb_fn("https://i.ytimg.com/vi/abc/hqdefault.jpg") == "https://i.ytimg.com/vi/abc/default.jpg"
    assert thumb_fn("https://i.ytimg.com/vi/abc/maxresdefault.jpg") == "https://i.ytimg.com/vi/abc/default.jpg"
    assert thumb_fn("https://i.ytimg.com/vi/abc/default.jpg") == "https://i.ytimg.com/vi/abc/default.jpg"
