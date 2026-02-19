from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from api.exceptions import register_exception_handlers
from api.routers import actions, decisions, errors, hypotheses

logger = logging.getLogger("ddw.api")


_RATE_WINDOW_SECONDS = 60.0
_rate_buckets: dict[str, tuple[float, int]] = {}


def _parse_rate_limit_rpm() -> int:
    """Parse DDW_RATE_LIMIT_RPM.

    Contract:
    - If env var is missing or <= 0, rate limiting is disabled (canonical default).
    - If env var is invalid, rate limiting is treated as disabled.
    """

    raw = os.getenv("DDW_RATE_LIMIT_RPM", "0").strip()
    try:
        return int(raw)
    except ValueError:
        return 0


_RATE_LIMIT_RPM = _parse_rate_limit_rpm()


def _rate_limit_is_disabled() -> bool:
    """Return True if rate limiting should be bypassed.

    Rationale:
    - Under pytest, the in-memory limiter makes tests flaky because buckets are global.
    - In dev, users may want to bypass it explicitly.
    """

    flag = os.getenv("DDW_DISABLE_RATE_LIMIT", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True

    # pytest exports this env var for each running test.
    if os.getenv("PYTEST_CURRENT_TEST") is not None:
        return True

    return False


def create_app() -> FastAPI:
    app = FastAPI(title="Decision Workspace", version="1.0.0")

    register_exception_handlers(app)

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

        # Basic (in-memory) rate limiting (opt-in via env).
        # Canonical default path: disabled unless DDW_RATE_LIMIT_RPM is set to a positive int.
        # Additional safety: missing tenant must flow downstream and yield 422 (not 429).
        if (
            _RATE_LIMIT_RPM > 0
            and not _rate_limit_is_disabled()
            and request.url.path != "/health"
            and tenant != "-"
        ):
            key = tenant

            now = time.time()
            start, count = _rate_buckets.get(key, (now, 0))
            if now - start >= _RATE_WINDOW_SECONDS:
                start, count = now, 0
            if count >= _RATE_LIMIT_RPM:
                retry_after = max(0, int(_RATE_WINDOW_SECONDS - (now - start)))
                resp = JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests"},
                    headers={"Retry-After": str(retry_after), "X-Request-Id": request_id},
                )
                logger.warning(
                    "%s %s -> 429 tenant=%s request_id=%s rate_key=%s",
                    request.method,
                    request.url.path,
                    tenant,
                    request_id,
                    key,
                )
                return resp

            _rate_buckets[key] = (start, count + 1)

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

    return app


app = create_app()
