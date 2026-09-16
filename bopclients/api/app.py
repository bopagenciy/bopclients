"""FastAPI Product API Application Factory for BopClients."""

import logging
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.container import RuntimeContainer, build_runtime_container
from bopclients.api.errors import register_exception_handlers
from bopclients.api.middleware import (
    CorrelationIdMiddleware,
    SecurityHeadersMiddleware,
    RequestLoggingMiddleware,
)

from bopclients.api.routers.auth_router import router as auth_router
from bopclients.api.routers.me_router import router as me_router
from bopclients.api.routers.organizations_router import router as organizations_router
from bopclients.api.routers.invitations_router import router as invitations_router
from bopclients.api.routers.campaigns_router import router as campaigns_router
from bopclients.api.routers.icps_router import router as icps_router
from bopclients.api.routers.target_markets_router import router as target_markets_router
from bopclients.api.routers.prospects_router import router as prospects_router
from bopclients.api.routers.discovery_router import router as discovery_router
from bopclients.api.routers.signals_router import router as signals_router
from bopclients.api.routers.research_router import router as research_router
from bopclients.api.routers.monitoring_router import router as monitoring_router
from bopclients.api.routers.integrations_router import router as integrations_router
from bopclients.api.routers.health_router import router as health_router

logger = logging.getLogger("bopclients.api")


def create_bopclients_api_app(
    container: Optional[RuntimeContainer] = None,
    settings: Optional[RuntimeSettings] = None,
) -> FastAPI:
    """Application factory for BopClients Product API.

    Wires routers, middleware, exception handlers, and security baseline.
    """
    if not settings:
        settings = RuntimeSettings.from_env()

    if not container:
        container = build_runtime_container(settings=settings)

    app = FastAPI(
        title="BopClients Product API",
        version="1.0.0",
        description="Multilingual multi-tenant product API and authorization layer for BopClients.",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Attach container and settings to app state
    app.state.container = container
    app.state.settings = settings

    # 1. Register global exception handlers
    register_exception_handlers(app)

    # 2. Register Middleware (LIFO order in Starlette)
    # Logging
    app.add_middleware(RequestLoggingMiddleware)
    # Security baseline headers
    app.add_middleware(SecurityHeadersMiddleware)
    # Correlation ID
    app.add_middleware(CorrelationIdMiddleware)

    # CORS configuration (settings-driven, no credentials with wildcard)
    allowed_origins = settings.cors_allowed_origins or ["http://localhost:3000", "http://localhost:5173"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
    )

    # 3. Register Routers
    # Operational unversioned routes
    app.include_router(health_router)

    # Canonical /api/v1 business routes
    app.include_router(auth_router)
    app.include_router(me_router)
    app.include_router(organizations_router)
    app.include_router(campaigns_router)
    app.include_router(icps_router)
    app.include_router(target_markets_router)
    app.include_router(prospects_router)
    app.include_router(discovery_router)
    app.include_router(signals_router)
    app.include_router(research_router)
    app.include_router(monitoring_router)
    app.include_router(integrations_router)
    app.include_router(invitations_router)

    return app


# Module-level default application instance for ASGI servers
app = create_bopclients_api_app()
