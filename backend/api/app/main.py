"""Sunwai API entry point: `uvicorn app.main:app --port 8000` (run from the api/ folder)."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from . import db
from .config import VERSION, get_settings
from .errors import error_response
from .events import bus
from .llm.gateway import gateway
from .routes import load_all
from .services import rules
from .web import docs_response
from .workers import scheduler

log = logging.getLogger("sunwai")


class RateLimit:
    """Tiny per-IP limiter for write requests (POST/PUT/DELETE), contract code RATE_LIMITED."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.hits: dict[str, deque] = defaultdict(deque)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in ("POST", "PUT", "DELETE") \
                and not scope["path"].startswith("/api/sandbox/"):
            limit = get_settings().rate_limit_per_min
            ip = (scope.get("client") or ("?", 0))[0]
            q = self.hits[ip]
            now = time.monotonic()
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= limit:
                resp = error_response(429, "RATE_LIMITED", "Too many requests. Please slow down.",
                                      headers={"Retry-After": "30"})
                await resp(scope, receive, send)
                return
            q.append(now)
        await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(app: Starlette):
    s = get_settings()
    logging.basicConfig(level=s.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db.init_db()
    bus.bind_loop(asyncio.get_running_loop())
    log.info("Sunwai API %s starting (mock_mode=%s, db=%s)", VERSION, s.mock_mode, s.sqlite_path)
    if not s.mock_mode:
        await gateway().check_models()
        if not s.tinyfish_api_key:
            log.warning("TINYFISH_API_KEY is not set: agent features will return TINYFISH_CONFIG errors")
    if s.startup_rule_refresh and rules.needs_refresh("rbi_cms") and (s.mock_mode or s.tinyfish_api_key):
        rules.start_refresh("rbi_cms")
    if s.scheduler_enabled:
        scheduler.start()
    yield
    await scheduler.stop()


async def openapi(_: Request) -> JSONResponse:
    return JSONResponse(api.openapi("Sunwai API", VERSION))


async def docs(_: Request):
    return docs_response()


async def root(_: Request):
    return RedirectResponse("/docs")


async def not_found(request: Request, exc: Exception) -> JSONResponse:
    return error_response(404, "NOT_FOUND", f"No route for {request.method} {request.url.path}.")


async def method_not_allowed(request: Request, exc: Exception) -> JSONResponse:
    return error_response(400, "BAD_REQUEST", f"{request.method} is not allowed on {request.url.path}.")


async def server_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error", exc_info=exc)
    return error_response(500, "INTERNAL", "Something went wrong on our side. Please try again.")


api = load_all()


def create_app() -> Starlette:
    s = get_settings()
    routes = [Route("/", root), Route("/openapi.json", openapi), Route("/docs", docs), *api.starlette_routes()]
    middleware = [
        Middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["Content-Disposition"], allow_credentials=False),
        Middleware(RateLimit),
    ]
    return Starlette(routes=routes, middleware=middleware, lifespan=lifespan,
                     exception_handlers={404: not_found, 405: method_not_allowed, 500: server_error})


app = create_app()
