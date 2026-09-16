from typing import Optional
from fastapi import APIRouter, Depends, Request, status
from bopclients.api.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    UserProfileItem,
    RefreshTokenRequest,
    PasswordResetRequest,
    PasswordResetConfirmRequest,
    PasswordResetResponse,
    EmailVerificationConfirmRequest,
    EmailVerificationResponse,
    EmailVerificationResendRequest,
    EmailVerificationResendResponse,
)
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
            email_verified_at=user.email_verified_at,
            is_verified=user.is_verified,
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
            email_verified_at=user.email_verified_at,
            is_verified=user.is_verified,
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


@router.post(
    "/password-reset/request",
    response_model=PasswordResetResponse,
    status_code=status.HTTP_200_OK,
    summary="Request password reset instructions",
    description="Initiates password recovery. Neutral response prevents email enumeration.",
)
async def request_password_reset(
    payload: PasswordResetRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> PasswordResetResponse:
    auth_service.request_password_reset(email=payload.email, locale=payload.locale)
    return PasswordResetResponse(
        success=True,
        message="If the email is registered, password reset instructions have been sent.",
    )


@router.post(
    "/password-reset/confirm",
    response_model=PasswordResetResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirm password reset",
    description="Validates single-use reset token and updates account password, revoking existing sessions.",
)
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> PasswordResetResponse:
    auth_service.confirm_password_reset(
        raw_token=payload.token,
        new_password=payload.new_password,
    )
    return PasswordResetResponse(
        success=True,
        message="Password has been reset successfully. Please sign in with your new password.",
    )


@router.post(
    "/email-verification/confirm",
    response_model=EmailVerificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirm email verification",
    description="Validates single-use verification token and marks user email as verified.",
)
async def confirm_email_verification(
    payload: EmailVerificationConfirmRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> EmailVerificationResponse:
    auth_service.confirm_email_verification(raw_token=payload.token)
    return EmailVerificationResponse(
        success=True,
        message="Email verified successfully.",
    )


@router.post(
    "/email-verification/resend",
    response_model=EmailVerificationResendResponse,
    status_code=status.HTTP_200_OK,
    summary="Resend email verification",
    description="Sends a new verification email to the currently authenticated user.",
)
async def resend_email_verification(
    payload: Optional[EmailVerificationResendRequest] = None,
    current_user: UserPrincipal = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> EmailVerificationResendResponse:
    locale = (payload.locale if payload else None) or current_user.locale
    auth_service.send_verification_email(user_id=current_user.user_id, locale=locale)
    return EmailVerificationResendResponse(
        success=True,
        message="Verification email sent.",
    )
