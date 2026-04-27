"""FastAPI app factory: routers, middleware, schema init."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import auth
import db
from config import Config, ensure_dirs
from routers import agent as agent_router
from routers import pages as pages_router
from routers import web_api as web_router

log = logging.getLogger("app")


CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "fetch"


def build_app(cfg: Config) -> FastAPI:
    ensure_dirs(cfg)
    db.configure(cfg.storage.db_path)
    db.init_schema()
    auth.configure(cfg)
    agent_router.configure(cfg)
    web_router.configure(cfg)

    app = FastAPI(title="RAC Server", docs_url=None, redoc_url=None, openapi_url=None)

    app.add_middleware(
        SessionMiddleware,
        secret_key=cfg.auth.session_secret,
        max_age=cfg.auth.session_lifetime_hours * 3600,
        same_site="lax",
        https_only=False,
    )

    @app.middleware("http")
    async def csrf_and_session_redirect(request: Request, call_next):
        path = request.url.path
        method = request.method.upper()

        # CSRF: protect /api/web/* writes via X-Requested-With header.
        # Login form, agent endpoints, and GETs are exempt.
        if (
            path.startswith("/api/web/")
            and method in ("POST", "PUT", "PATCH", "DELETE")
        ):
            xrw = request.headers.get(CSRF_HEADER, "").lower()
            if xrw != CSRF_VALUE:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "missing X-Requested-With header"},
                )

        return await call_next(request)

    @app.exception_handler(HTTPException)
    async def http_exc_handler(request: Request, exc: HTTPException):
        # For HTML routes, redirect to /login on 401 instead of JSON.
        path = request.url.path
        if exc.status_code == 401 and not path.startswith("/api/"):
            return RedirectResponse(url="/login", status_code=302)
        headers = getattr(exc, "headers", None)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=headers,
        )

    @app.middleware("http")
    async def log_agent_requests(request: Request, call_next):
        path = request.url.path
        is_agent = path.startswith("/api/agent/")
        response = await call_next(request)
        if is_agent:
            # device_id may not be available here cheaply; agent router logs richer info.
            log.info("agent http: %s %s -> %s", request.method, path, response.status_code)
        return response

    # static
    static_dir = Path("static")
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory="static"), name="static")

    # routers
    app.include_router(pages_router.router)
    app.include_router(agent_router.router)
    app.include_router(web_router.router)

    return app
