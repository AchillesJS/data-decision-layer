from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from api.exceptions import register_exception_handlers
from api.routers import (
    actions,
    analytics,
    decisions,
    diagnostics,
    errors,
    hypotheses,
    jobs,
    potentials,
    runners,
    runs,
)

logger = logging.getLogger("ddw.api")


def create_app() -> FastAPI:
    app = FastAPI(title="Decision Workspace", version="1.0.0")

    register_exception_handlers(app)

    # CORS is required for browser-based UIs (e.g. Next.js dev server on :3000).
    # Keep it configurable for deployments; defaults are safe for local development.
    cors_origins = os.getenv(
        "DDW_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://26.26.26.1:3000",
    )
    origins = [o.strip() for o in cors_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Total-Count", "X-Request-Id"],
        )

    @app.middleware("http")
    async def request_id_and_logging(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        request.state.request_id = request_id

        started = time.perf_counter()
        tenant_header = request.headers.get("X-Tenant-Id")
        tenant = tenant_header.strip() if tenant_header and tenant_header.strip() else "-"

        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            logger.exception(
                "%s %s -> exception tenant=%s request_id=%s %.2fms",
                request.method,
                request.url.path,
                tenant,
                request_id,
                elapsed_ms,
            )
            raise

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.info(
            "%s %s -> %s tenant=%s request_id=%s %.2fms",
            request.method,
            request.url.path,
            response.status_code,
            tenant,
            request_id,
            elapsed_ms,
        )

        response.headers["X-Request-Id"] = request_id
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(errors.router)
    app.include_router(hypotheses.router)
    app.include_router(actions.router)
    app.include_router(decisions.router)
    app.include_router(potentials.router)
    app.include_router(runs.router)
    app.include_router(runners.router)
    app.include_router(jobs.router)
    app.include_router(analytics.router)
    app.include_router(diagnostics.router)

    return app


app = create_app()
