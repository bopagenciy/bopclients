from typing import Optional
from fastapi import APIRouter, Depends, Request, status
from bopclients.api.schemas.auth import LoginRequest, LoginResponse, LogoutResponse, UserProfileItem, RefreshTokenRequest
from bopclients.api.dependencies import get_auth_service, get_current_user
from bopclients.application.auth_service import (
    AuthService,
    SessionExpiredOrRevokedError,
    InactiveUserError,
)
from bopclients.domain.auth.context import UserPrincipal

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate user credentials",
    description="Authenticates email and password, enforces brute-force protection, and returns JWT access token.",
)
async def login(
    payload: LoginRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    token_pair, user = auth_service.authenticate(
        email=payload.email,
        password=payload.password,
        ip_address=client_ip,
        user_agent=user_agent,
    )

    return LoginResponse(
        access_token=token_pair.access_token,
        token_type=token_pair.token_type,
        expires_in=token_pair.expires_in,
        refresh_token=token_pair.refresh_token,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        locale=user.locale,
        user=UserProfileItem(
            id=user.id,
            email=user.email,
            name=user.full_name,
            locale=user.locale,
        ),
    )


@router.post(
    "/refresh",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh access token",
    description="Rotates access token using active session token.",
)
async def refresh_token(
    payload: RefreshTokenRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    session = auth_service.get_session_by_token(payload.refresh_token)
    if not session or not session.is_active:
        raise SessionExpiredOrRevokedError("Invalid or expired session token.")

    user = auth_service.user_repo.get_by_id(session.user_id)
    if not user or not user.is_active:
        raise InactiveUserError("User account is inactive or not found.")

    new_access_token = auth_service.token_service.create_access_token(
        user_id=user.id,
        email=user.email,
        session_id=session.id,
    )
    auth_service.session_repo.touch_session(session.id)

    return LoginResponse(
        access_token=new_access_token,
        token_type="Bearer",
        expires_in=auth_service.token_service.access_token_expire_seconds,
        refresh_token=payload.refresh_token,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        locale=user.locale,
        user=UserProfileItem(
            id=user.id,
            email=user.email,
            name=user.full_name,
            locale=user.locale,
        ),
    )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    status_code=status.HTTP_200_OK,
    summary="Revoke active session",
    description="Revokes the server-side session associated with the active access token.",
)
async def logout(
    request: Request,
    payload: Optional[RefreshTokenRequest] = None,
    current_user: UserPrincipal = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> LogoutResponse:
    if payload and payload.refresh_token:
        auth_service.logout(payload.refresh_token)
    else:
        session_id = getattr(request.state, "session_id", None) or current_user.session_id
        if session_id:
            auth_service.logout(session_id)

    return LogoutResponse(success=True, message="Session successfully terminated.")
