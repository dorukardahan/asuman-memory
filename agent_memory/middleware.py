"""Security middleware for the Memory API.

Provides:
    - API key authentication (X-API-Key header)
    - Rate limiting (per-IP, in-memory sliding window)
    - Audit logging (structured request/response logging)
"""

from __future__ import annotations

import logging
import secrets
import time
from collections import defaultdict
from typing import Callable, Set

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("audit")


# ---------------------------------------------------------------------------
# API Key Authentication
# ---------------------------------------------------------------------------

class APIKeyMiddleware(BaseHTTPMiddleware):
    """Require X-API-Key header on all non-exempt paths."""

    EXEMPT_PATHS: Set[str] = {"/v1/health", "/docs", "/openapi.json", "/redoc"}

    def __init__(self, app, api_key: str):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        key = request.headers.get("X-API-Key", "")
        if not key or not secrets.compare_digest(key, self.api_key):
            audit_logger.warning(
                "AUTH_FAIL ip=%s path=%s",
                request.client.host if request.client else "unknown",
                request.url.path,
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )

        return await call_next(request)


# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple sliding-window rate limiter (per-IP, in-memory)."""

    def __init__(self, app, max_requests: int = 120, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "0.0.0.0"
        now = time.time()

        # Prune old entries
        hits = self._hits[client_ip]
        self._hits[client_ip] = [t for t in hits if now - t < self.window]

        if len(self._hits[client_ip]) >= self.max_requests:
            audit_logger.warning(
                "RATE_LIMIT ip=%s path=%s count=%d",
                client_ip, request.url.path, len(self._hits[client_ip]),
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(self.window)},
            )

        self._hits[client_ip].append(now)
        return await call_next(request)


# ---------------------------------------------------------------------------
# Audit Logging
# ---------------------------------------------------------------------------

class AuditLogMiddleware(BaseHTTPMiddleware):
    """Log every request with structured fields for forensic analysis."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.time()
        client_ip = request.client.host if request.client else "unknown"

        # Extract agent from query params or body (best-effort)
        agent = request.query_params.get("agent", "-")

        response = await call_next(request)
        elapsed_ms = round((time.time() - start) * 1000, 1)

        audit_logger.info(
            "method=%s path=%s status=%d ip=%s agent=%s elapsed_ms=%.1f",
            request.method,
            request.url.path,
            response.status_code,
            client_ip,
            agent,
            elapsed_ms,
        )

        return response
