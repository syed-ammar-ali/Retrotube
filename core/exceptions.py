"""Application exception handlers for HTML pages and JSON APIs."""
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.templates import templates


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Render HTML error template for browser requests, or JSON response for /api/*."""
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            {"detail": exc.detail},
            status_code=exc.status_code,
            headers=exc.headers,
        )
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "user": None,
            "csrf": "",
            "status": exc.status_code,
            "message": exc.detail,
            "active_tab": "",
        },
        status_code=exc.status_code,
        headers=exc.headers,
    )
