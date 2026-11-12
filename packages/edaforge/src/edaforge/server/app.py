"""The EDAForge local web server: JSON API under ``/api`` plus the built web app.

Local-first (PROJECT_PROMPT.md section 9): the server binds to 127.0.0.1, checks the ``Host``
header (DNS-rebinding protection), requires a custom header on every state-changing request
(a cross-site page cannot send it without a CORS preflight, which is never granted), sends a
strict Content-Security-Policy and never contacts another host.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from edaforge.server.store import NotFound, ProjectStore, default_home

__all__ = ["CLIENT_HEADER", "create_app"]

CLIENT_HEADER = "x-edaforge-client"
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


def _default_dist() -> Path | None:
    configured = os.environ.get("EDAFORGE_WEB_DIST")
    if configured:
        return Path(configured)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "apps" / "web" / "dist"
        if candidate.is_dir():
            return candidate
    return None


def create_app(
    home: Path | None = None,
    *,
    web_dist: Path | None = None,
    allowed_hosts: list[str] | None = None,
) -> FastAPI:
    store = ProjectStore(home or default_home())
    app = FastAPI(title="EDAForge", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store

    hosts = allowed_hosts or [
        h.strip()
        for h in os.environ.get("EDAFORGE_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(
            ","
        )
        if h.strip()
    ]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if (
            request.url.path.startswith("/api/")
            and request.method
            not in {
                "GET",
                "HEAD",
                "OPTIONS",
            }
            and request.headers.get(CLIENT_HEADER) != "1"
        ):
            return JSONResponse({"detail": "missing client header"}, status_code=403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(NotFound)
    async def not_found(_: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(exc) or "not found"}, status_code=404)

    from edaforge.server.routes_data import router as data_router

    app.include_router(data_router, prefix="/api")
    _optional_routers(app)

    dist = web_dist if web_dist is not None else _default_dist()
    if dist is not None and (dist / "index.html").is_file():
        root = dist.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> Response:
            if path.startswith("api/"):
                return JSONResponse({"detail": "not found"}, status_code=404)
            candidate = (root / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(root):
                headers = (
                    {"Cache-Control": "public, max-age=31536000, immutable"}
                    if path.startswith("assets/")
                    else {"Cache-Control": "no-cache"}
                )
                return FileResponse(candidate, headers=headers)
            return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})

    return app


def _optional_routers(app: FastAPI) -> None:
    """Routers of later milestones, included when present."""
    import importlib

    for module in (
        "edaforge.server.routes_links",
        "edaforge.server.routes_runs",
        "edaforge.server.routes_clean",
    ):
        try:
            loaded = importlib.import_module(module)
        except ModuleNotFoundError as exc:
            if exc.name == module:
                continue
            raise
        app.include_router(loaded.router, prefix="/api")
