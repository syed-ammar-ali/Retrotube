"""Security utilities: Argon2id password hashing, CSRF protection, and session guards."""
import asyncio
import secrets
from urllib.parse import urlparse

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from models import User

ph = PasswordHasher()


async def hash_password(password: str) -> str:
    """Hash a password using Argon2id off the main event loop."""
    return await asyncio.to_thread(ph.hash, password)


async def verify_password(hashed: str, plain: str) -> bool:
    """Verify an Argon2id password hash safely off the main event loop."""
    try:
        return await asyncio.to_thread(ph.verify, hashed, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False


def get_csrf(request: Request) -> str:
    """Generate or retrieve a cryptographically secure CSRF token stored in the session."""
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    return request.session["csrf"]


def check_csrf(request: Request, token: str | None) -> None:
    """Validate a submitted CSRF token against the session using constant-time comparison."""
    expected = request.session.get("csrf")
    if not expected or not token or not secrets.compare_digest(expected, token):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token")


async def current_user(request: Request, db: AsyncSession) -> User | None:
    """Resolve the currently authenticated User from the session ID, if present."""
    uid = request.session.get("uid")
    return await db.get(User, uid) if uid else None


def require_user(user: User | None) -> User:
    """Ensure a user is authenticated, raising HTTP 401 if not."""
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in first")
    return user


def safe_bg_url(url: str) -> str | None:
    """Sanitize custom profile wallpaper URLs, strictly allowing HTTPS image files."""
    p = urlparse(url or "")
    if p.scheme != "https" or not p.netloc:
        return None
    allowed_exts = (".jpg", ".jpeg", ".png", ".gif", ".webp")
    if not any(p.path.lower().endswith(ext) for ext in allowed_exts):
        return None
    return url


def wallpaper_css(theme: dict) -> str:
    """Generate inline CSS styling for channel profiles based on validated theme data."""
    parts = []
    if theme.get("bg_color"):
        parts.append(f"background-color: {theme['bg_color']};")
    if theme.get("bg_url"):
        clean = safe_bg_url(theme["bg_url"])
        if clean:
            parts.append(f"background-image: url('{clean}'); background-repeat: repeat;")
    return " ".join(parts)
