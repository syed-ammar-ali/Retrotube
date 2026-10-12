"""Authentication routes: registration, login, and logout."""
import re
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.rate_limit import rate_limit
from core.security import check_csrf, current_user, hash_password, verify_password
from core.templates import render
from database import get_db
from models import User

router = APIRouter(tags=["auth"])

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")


@router.api_route("/register", methods=["GET", "POST"], response_class=HTMLResponse)
async def register(
    request: Request,
    csrf: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Handle member registration."""
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

    hashed = await hash_password(password)
    new_user = User(username=username, username_lower=username.lower(), password_hash=hashed)
    db.add(new_user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return render(
            request, "auth.html", user, mode="register",
            error="That username is taken.", active_tab="",
        )

    request.session.clear()
    request.session["uid"] = new_user.id
    return RedirectResponse("/", status_code=303)


@router.api_route("/login", methods=["GET", "POST"], response_class=HTMLResponse)
async def login(
    request: Request,
    csrf: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Handle member login."""
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
        ok = await verify_password(row.password_hash, password)

    if not ok:
        return render(
            request, "auth.html", user, mode="login",
            error="Invalid username or password.", active_tab="",
        )

    request.session.clear()
    request.session["uid"] = row.id
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
async def logout(request: Request, csrf: str = Form("")):
    """Clear the session cookie on logout."""
    check_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/", status_code=303)
