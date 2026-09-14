"""FastAPI dependencies for container injection, authentication, tenant context, and RBAC."""

from typing import Optional, Callable
from fastapi import Request, Depends, Header, status
from bopclients.runtime.container import RuntimeContainer
from bopclients.application.auth_service import AuthService
from bopclients.domain.auth.token import TokenSecurityError, TokenInvalidError
from bopclients.domain.auth.policy import AuthorizationPolicy, Permission
from bopclients.domain.auth.context import UserPrincipal, TenantContext, RequestContext

SUPPORTED_LOCALES = {"en", "es"}


def get_container(request: Request) -> RuntimeContainer:
    """Extract configured RuntimeContainer from application state."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise RuntimeError("RuntimeContainer is not initialized on application state.")
    return container


def get_auth_service(container: RuntimeContainer = Depends(get_container)) -> AuthService:
    """Dependency providing the centralized AuthService."""
    return container.auth_service


def resolve_locale(accept_language_header: Optional[str], user_locale: Optional[str] = None) -> str:
    """Resolve active language according to strict precedence rules:

    1. Explicit authenticated user persisted preference (if set and supported)
    2. Accept-Language request header (if matching supported locale)
    3. Default fallback: 'en'
    """
    if user_locale and user_locale.strip().lower() in SUPPORTED_LOCALES:
        return user_locale.strip().lower()

    if accept_language_header:
        raw = accept_language_header.lower()
        # Check for Spanish preference in header
        if "es" in raw.replace("_", "-").split(",") or raw.startswith("es"):
            return "es"

    return "en"


from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security_scheme = HTTPBearer(auto_error=False, scheme_name="BearerAuth", description="HS256 JWT access token")


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserPrincipal:
    """Authenticate request using Bearer JWT access token."""
    token: Optional[str] = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    elif authorization:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]

    if not token:
        raise TokenSecurityError("Authorization header is required.")

    principal, session_id = auth_service.validate_access_token(token)

    # Attach to request state for audit & logging middleware
    request.state.user_id = principal.user_id
    request.state.session_id = session_id
    return principal


def get_tenant_context(
    request: Request,
    x_bop_organization_id: Optional[str] = Header(None, alias="X-Bop-Organization-Id"),
    current_user: UserPrincipal = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> TenantContext:
    """Resolve and verify tenant organization boundary from authenticated membership."""
    tenant = auth_service.resolve_tenant_context(
        user_id=current_user.user_id,
        requested_bop_organization_id=x_bop_organization_id,
    )

    request.state.organization_id = tenant.organization_id
    request.state.bop_organization_id = tenant.bop_organization_id
    request.state.member_role = tenant.role.value
    return tenant


def get_request_context(
    request: Request,
    accept_language: Optional[str] = Header(None, alias="Accept-Language"),
    current_user: UserPrincipal = Depends(get_current_user),
    tenant_context: TenantContext = Depends(get_tenant_context),
) -> RequestContext:
    """Assemble complete actor request context for application services."""
    request_id = getattr(request.state, "request_id", "unknown")
    locale = resolve_locale(accept_language, current_user.locale)
    client_ip = request.client.host if request.client else None

    return RequestContext(
        request_id=request_id,
        principal=current_user,
        tenant=tenant_context,
        locale=locale,
        ip_address=client_ip,
    )


def require_permission(permission: Permission) -> Callable:
    """Dependency factory enforcing RBAC permission checks against the active tenant role."""

    def _permission_checker(tenant_context: TenantContext = Depends(get_tenant_context)) -> TenantContext:
        AuthorizationPolicy.enforce(
            role=tenant_context.role,
            permission=permission,
            context_message=f"tenant={tenant_context.bop_organization_id}",
        )
        return tenant_context

    return _permission_checker
