"""Jinja2 templating environment, filters, and rendering helpers."""
import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from core.security import get_csrf
from models import User
from services.youtube import CATEGORIES

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"

templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ------------------------------------------------ Custom Filters
templates.env.filters["commas"] = lambda n: f"{int(n or 0):,}"


def ago(iso: str) -> str:
    """Format ISO timestamp into classic 'N years ago' / 'today' relative strings."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return ""
    days = (datetime.now(UTC) - dt).days
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

_THUMB_RE = re.compile(r"/(?:mq|hq|sd|maxres)?default(?:_live)?\.jpg")
templates.env.filters["thumb120"] = lambda u: _THUMB_RE.sub("/default.jpg", u or "")

# ------------------------------------------------ Globals
ERAS = list(range(2006, 2017))
templates.env.globals["ERAS"] = ERAS
templates.env.globals["CATEGORIES"] = CATEGORIES


def render(request: Request, name: str, user: User | None = None, **ctx):
    """Render a Jinja2 template with request, user, and CSRF token injected."""
    ctx.update(user=user, csrf=get_csrf(request))
    return templates.TemplateResponse(request, name, ctx)
