"""HTTP Middleware for request correlation, timing, sanitized logging, and security headers."""

import logging
import time
import uuid
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("bopclients.api.access")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Assigns or propagates X-Request-Id and attaches to request.state."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        incoming_id = request.headers.get("X-Request-Id", "").strip()
        # Accept valid incoming correlation ID (alphanumeric/hyphens up to 64 chars)
        if incoming_id and len(incoming_id) <= 64 and incoming_id.replace("-", "").isalnum():
            request_id = incoming_id
        else:
            request_id = f"req-{uuid.uuid4()}"

        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforces essential security baseline headers for JSON API responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Structured request logging strictly masking authorization headers and credentials."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()
        request_id = getattr(request.state, "request_id", "unknown")

        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        actor_user_id = getattr(request.state, "user_id", None)
        bop_org_id = getattr(request.state, "bop_organization_id", None)

        log_data = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "user_id": actor_user_id,
            "bop_organization_id": bop_org_id,
        }

        # Ensure credentials/Authorization are never logged
        logger.info(f"API_REQUEST: {log_data}")
        return response
