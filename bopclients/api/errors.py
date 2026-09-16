"""Consistent API error models, exception handlers, and sensitive data sanitization."""

import logging
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from bopclients.domain.exceptions import (
    BopClientsDomainError,
    EntityNotFoundError,
    ValidationError as DomainValidationError,
    MemberRolePermissionError,
    TenantAccessError,
    LastOwnerProtectionError,
    InvalidRoleTransitionError,
    InvitationNotFoundError,
    InvitationExpiredError,
    InvitationAlreadyAcceptedError,
    InvitationRevokedError,
    AlreadyOrganizationMemberError,
    DuplicateInvitationError,
    InvitationEmailMismatchError,
)
from bopclients.application.auth_service import (
    AuthError,
    InvalidCredentialsError,
    InactiveUserError,
    AccountLockedError,
    SessionExpiredOrRevokedError,
    NoOrganizationMembershipError,
    InvalidTokenError,
    PasswordValidationError,
)
from bopclients.domain.auth.token import TokenSecurityError, TokenExpiredError, TokenInvalidError

logger = logging.getLogger("bopclients.api.errors")


class ErrorDetail(BaseModel):
    """Detailed canonical error envelope."""

    code: str = Field(description="Machine-readable, language-neutral uppercase error code")
    message: str = Field(description="Human-readable safe error message (fallback English)")
    message_key: str = Field(description="Frontend localization key for client translation")
    request_id: str = Field(description="Correlation request identifier for tracing")
    details: Dict[str, Any] = Field(default_factory=dict, description="Structured error context or validation errors")


class ErrorResponse(BaseModel):
    """Top-level error response envelope."""

    error: ErrorDetail


TRANSLATION_CATALOG: Dict[str, Dict[str, str]] = {
    "en": {
        "errors.invalid_credentials": "Invalid email or password.",
        "errors.inactive_user": "User account is inactive. Please contact your organization administrator.",
        "errors.account_locked": "Too many failed login attempts. Please try again later.",
        "errors.token_expired": "Access token has expired. Please refresh your session.",
        "errors.token_invalid": "Access token is missing or invalid.",
        "errors.session_invalid": "Session has been revoked or is no longer valid.",
        "errors.resource_not_found": "The requested resource was not found.",
        "errors.forbidden": "User role does not possess required permission.",
        "errors.no_tenant_membership": "User does not belong to any organization.",
        "errors.validation_error": "Request validation failed.",
        "errors.internal_server_error": "An unexpected internal server error occurred.",
        "errors.not_found": "Resource not found.",
        "errors.method_not_allowed": "Method not allowed.",
        "errors.last_owner_protection": "Cannot demote or remove the last owner of the organization.",
        "errors.invalid_role_transition": "Invalid role transition.",
        "errors.invitation_not_found": "Invitation not found.",
        "errors.invitation_expired": "This invitation has expired.",
        "errors.invitation_already_accepted": "This invitation has already been accepted.",
        "errors.invitation_revoked": "This invitation has been revoked.",
        "errors.already_organization_member": "User is already a member of this organization.",
        "errors.duplicate_invitation": "A pending invitation already exists for this email.",
        "errors.invitation_email_mismatch": "The authenticated user email does not match this invitation.",
        "errors.invalid_token": "Invalid or expired token.",
        "errors.password_validation_failed": "Password does not meet the security requirements.",
    },
    "es": {
        "errors.invalid_credentials": "Credenciales inválidas. Correo o contraseña incorrectos.",
        "errors.inactive_user": "La cuenta de usuario está inactiva. Contacte al administrador de su organización.",
        "errors.account_locked": "Demasiados intentos fallidos. Por favor intente más tarde.",
        "errors.token_expired": "El token de acceso ha expirado. Por favor renueve su sesión.",
        "errors.token_invalid": "El token de acceso es inválido o no fue proporcionado.",
        "errors.session_invalid": "La sesión ha sido revocada o ya no es válida.",
        "errors.resource_not_found": "El recurso solicitado no fue encontrado.",
        "errors.forbidden": "El rol de usuario no cuenta con los permisos requeridos.",
        "errors.no_tenant_membership": "El usuario no pertenece a ninguna organización.",
        "errors.validation_error": "Error de validación en la solicitud.",
        "errors.internal_server_error": "Ocurrió un error interno del servidor.",
        "errors.not_found": "Recurso no encontrado.",
        "errors.method_not_allowed": "Método no permitido.",
        "errors.last_owner_protection": "No se puede degradar o eliminar al último propietario de la organización.",
        "errors.invalid_role_transition": "Transición de rol no permitida.",
        "errors.invitation_not_found": "Invitación no encontrada.",
        "errors.invitation_expired": "Esta invitación ha expirado.",
        "errors.invitation_already_accepted": "Esta invitación ya ha sido aceptada.",
        "errors.invitation_revoked": "Esta invitación ha sido revocada.",
        "errors.already_organization_member": "El usuario ya es miembro de esta organización.",
        "errors.duplicate_invitation": "Ya existe una invitación pendiente para este correo.",
        "errors.invitation_email_mismatch": "El correo del usuario autenticado no coincide con esta invitación.",
        "errors.invalid_token": "Token inválido o expirado.",
        "errors.password_validation_failed": "La contraseña no cumple con los requisitos de seguridad.",
    },
}


def resolve_request_locale(request: Optional[Request] = None) -> str:
    """Resolve locale with precedence: request.state.user locale > Accept-Language > 'en'."""
    if not request:
        return "en"
    user = getattr(request.state, "user", None)
    if user and getattr(user, "locale", None) in ("en", "es"):
        return user.locale
    accept_lang = request.headers.get("Accept-Language", "").lower()
    if "es" in accept_lang:
        return "es"
    return "en"


def create_error_response(
    status_code: int,
    code: str,
    message: str,
    message_key: str,
    request_id: str,
    details: Optional[Dict[str, Any]] = None,
    request: Optional[Request] = None,
) -> JSONResponse:
    """Helper formatting consistent JSON error responses with localization."""
    locale = resolve_request_locale(request)
    catalog = TRANSLATION_CATALOG.get(locale, TRANSLATION_CATALOG["en"])
    localized_message = catalog.get(message_key, message)

    payload = {
        "error": {
            "code": code,
            "message": localized_message,
            "message_key": message_key,
            "request_id": request_id,
            "details": details or {},
        }
    }
    return JSONResponse(status_code=status_code, content=payload)


def register_exception_handlers(app) -> None:
    """Register unified exception handlers on the FastAPI application."""

    @app.exception_handler(EntityNotFoundError)
    async def entity_not_found_handler(request: Request, exc: EntityNotFoundError):
        req_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="RESOURCE_NOT_FOUND",
            message=str(exc) or "The requested resource was not found.",
            message_key="errors.resource_not_found",
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(TenantAccessError)
    async def tenant_access_error_handler(request: Request, exc: TenantAccessError):
        req_id = getattr(request.state, "request_id", "unknown")
        # Returning 404 on cross-tenant resource access prevents resource enumeration
        return create_error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="RESOURCE_NOT_FOUND",
            message="The requested resource was not found.",
            message_key="errors.resource_not_found",
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(MemberRolePermissionError)
    async def permission_error_handler(request: Request, exc: MemberRolePermissionError):
        req_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(
            status_code=status.HTTP_403_FORBIDDEN,
            code="FORBIDDEN",
            message=str(exc) or "User role does not possess required permission.",
            message_key="errors.forbidden",
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(LastOwnerProtectionError)
    async def last_owner_protection_handler(request: Request, exc: LastOwnerProtectionError):
        req_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(
            status_code=status.HTTP_409_CONFLICT,
            code="LAST_OWNER_PROTECTION",
            message=str(exc) or "Cannot demote or remove the last owner of the organization.",
            message_key="errors.last_owner_protection",
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(InvalidRoleTransitionError)
    async def invalid_role_transition_handler(request: Request, exc: InvalidRoleTransitionError):
        req_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="INVALID_ROLE_TRANSITION",
            message=str(exc) or "Invalid role transition.",
            message_key="errors.invalid_role_transition",
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(InvitationNotFoundError)
    async def invitation_not_found_handler(request: Request, exc: InvitationNotFoundError):
        req_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="INVITATION_NOT_FOUND",
            message=str(exc) or "Invitation not found.",
            message_key="errors.invitation_not_found",
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(InvitationExpiredError)
    async def invitation_expired_handler(request: Request, exc: InvitationExpiredError):
        req_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(
            status_code=status.HTTP_410_GONE,
            code="INVITATION_EXPIRED",
            message=str(exc) or "This invitation has expired.",
            message_key="errors.invitation_expired",
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(InvitationAlreadyAcceptedError)
    async def invitation_already_accepted_handler(request: Request, exc: InvitationAlreadyAcceptedError):
        req_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(
            status_code=status.HTTP_409_CONFLICT,
            code="INVITATION_ALREADY_ACCEPTED",
            message=str(exc) or "This invitation has already been accepted.",
            message_key="errors.invitation_already_accepted",
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(InvitationRevokedError)
    async def invitation_revoked_handler(request: Request, exc: InvitationRevokedError):
        req_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(
            status_code=status.HTTP_410_GONE,
            code="INVITATION_REVOKED",
            message=str(exc) or "This invitation has been revoked.",
            message_key="errors.invitation_revoked",
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(AlreadyOrganizationMemberError)
    async def already_organization_member_handler(request: Request, exc: AlreadyOrganizationMemberError):
        req_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(
            status_code=status.HTTP_409_CONFLICT,
            code="ALREADY_ORGANIZATION_MEMBER",
            message=str(exc) or "User is already a member of this organization.",
            message_key="errors.already_organization_member",
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(DuplicateInvitationError)
    async def duplicate_invitation_handler(request: Request, exc: DuplicateInvitationError):
        req_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(
            status_code=status.HTTP_409_CONFLICT,
            code="DUPLICATE_INVITATION",
            message=str(exc) or "A pending invitation already exists for this email.",
            message_key="errors.duplicate_invitation",
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(InvitationEmailMismatchError)
    async def invitation_email_mismatch_handler(request: Request, exc: InvitationEmailMismatchError):
        req_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(
            status_code=status.HTTP_403_FORBIDDEN,
            code="INVITATION_EMAIL_MISMATCH",
            message=str(exc) or "The authenticated user email does not match this invitation.",
            message_key="errors.invitation_email_mismatch",
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(InvalidCredentialsError)
    async def invalid_credentials_handler(request: Request, exc: InvalidCredentialsError):
        req_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code=exc.code,
            message=str(exc),
            message_key=exc.message_key,
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(InactiveUserError)
    async def inactive_user_handler(request: Request, exc: InactiveUserError):
        req_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(
            status_code=status.HTTP_403_FORBIDDEN,
            code=exc.code,
            message=str(exc),
            message_key=exc.message_key,
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(AccountLockedError)
    async def account_locked_handler(request: Request, exc: AccountLockedError):
        req_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code=exc.code,
            message=str(exc),
            message_key=exc.message_key,
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(TokenExpiredError)
    async def token_expired_handler(request: Request, exc: TokenExpiredError):
        req_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="TOKEN_EXPIRED",
            message="Access token has expired. Please refresh your session.",
            message_key="errors.token_expired",
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(TokenSecurityError)
    async def token_security_handler(request: Request, exc: TokenSecurityError):
        req_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="TOKEN_INVALID",
            message="Access token is missing or invalid.",
            message_key="errors.token_invalid",
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(SessionExpiredOrRevokedError)
    async def session_revoked_handler(request: Request, exc: SessionExpiredOrRevokedError):
        req_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code=exc.code,
            message=str(exc),
            message_key=exc.message_key,
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(InvalidTokenError)
    async def invalid_token_handler(request: Request, exc: InvalidTokenError):
        req_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code=exc.code,
            message=str(exc),
            message_key=exc.message_key,
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(PasswordValidationError)
    async def password_validation_handler(request: Request, exc: PasswordValidationError):
        req_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=exc.code,
            message=str(exc),
            message_key=exc.message_key,
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(DomainValidationError)
    async def domain_validation_handler(request: Request, exc: DomainValidationError):
        req_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message=str(exc),
            message_key="errors.validation_error",
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(request: Request, exc: RequestValidationError):
        req_id = getattr(request.state, "request_id", "unknown")
        errors = {}
        for err in exc.errors():
            loc = ".".join(str(x) for x in err["loc"] if x != "body")
            errors[loc or "body"] = err["msg"]
        return create_error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="REQUEST_VALIDATION_ERROR",
            message="Invalid request payload or parameters.",
            message_key="errors.request_validation_error",
            request_id=req_id,
            details=errors,
            request=request,
        )

    @app.exception_handler(StarletteHTTPException)
    async def starlette_http_handler(request: Request, exc: StarletteHTTPException):
        req_id = getattr(request.state, "request_id", "unknown")
        code = "HTTP_ERROR"
        message_key = "errors.http_error"
        if exc.status_code == 404:
            code = "NOT_FOUND"
            message_key = "errors.not_found"
        elif exc.status_code == 401:
            code = "UNAUTHORIZED"
            message_key = "errors.unauthorized"
        elif exc.status_code == 403:
            code = "FORBIDDEN"
            message_key = "errors.forbidden"
        elif exc.status_code == 405:
            code = "METHOD_NOT_ALLOWED"
            message_key = "errors.method_not_allowed"

        return create_error_response(
            status_code=exc.status_code,
            code=code,
            message=str(exc.detail),
            message_key=message_key,
            request_id=req_id,
            request=request,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        req_id = getattr(request.state, "request_id", "unknown")
        logger.error(f"Unhandled internal server error [request_id={req_id}]: {type(exc).__name__}: {exc}", exc_info=True)
        # Never leak exception tracebacks or SQL details
        return create_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected internal server error occurred.",
            message_key="errors.internal_server_error",
            request_id=req_id,
            request=request,
        )
