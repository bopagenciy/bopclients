"""Application service coordinating authentication, token lifecycle, and tenant resolution."""

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple
from bopclients.domain.user import User
from bopclients.domain.enums import MemberRole
from bopclients.domain.exceptions import TenantAccessError
from bopclients.domain.auth.password import PasswordHasher
from bopclients.domain.auth.token import TokenService, TokenPair, TokenPayload, TokenSecurityError, TokenExpiredError, TokenInvalidError
from bopclients.domain.auth.context import UserPrincipal, TenantContext
from bopclients.domain.auth_token import AuthToken, AuthTokenType
from bopclients.infrastructure.repositories.organization_repository import UserRepository, OrganizationRepository
from bopclients.infrastructure.repositories.auth_repository import AuthSessionRepository, LoginAttemptRepository
from bopclients.infrastructure.repositories.auth_token_repository import AuthTokenRepository
from bopclients.application.interfaces.email_sender import ITransactionalEmailSender
from bopclients.domain.email import TransactionalEmailMessage, EmailCategory
from bopclients.application.email_templates import render_password_reset_email, render_email_verification_email

logger = logging.getLogger("bopclients.application.auth")


class AuthError(Exception):
    """Base application exception for authentication failures."""
    code: str = "AUTHENTICATION_FAILED"
    message_key: str = "errors.authentication_failed"


class InvalidCredentialsError(AuthError):
    """Raised when email or password verification fails."""
    code: str = "INVALID_CREDENTIALS"
    message_key: str = "errors.invalid_credentials"


class InvalidTokenError(AuthError):
    """Raised when an auth token (reset or verification) is invalid, expired, or consumed."""
    code: str = "INVALID_TOKEN"
    message_key: str = "errors.invalid_token"


class PasswordValidationError(AuthError):
    """Raised when password policy validation fails."""
    code: str = "PASSWORD_VALIDATION_FAILED"
    message_key: str = "errors.password_validation_failed"


class InactiveUserError(AuthError):
    """Raised when an inactive user attempts to authenticate."""
    code: str = "USER_INACTIVE"
    message_key: str = "errors.user_inactive"


class AccountLockedError(AuthError):
    """Raised when too many failed login attempts lock the account temporarily."""
    code: str = "ACCOUNT_LOCKED"
    message_key: str = "errors.account_locked"


class SessionExpiredOrRevokedError(AuthError):
    """Raised when session has been revoked or expired."""
    code: str = "SESSION_INVALID"
    message_key: str = "errors.session_invalid"


class NoOrganizationMembershipError(TenantAccessError):
    """Raised when user has no active organization memberships."""
    code: str = "NO_TENANT_MEMBERSHIP"
    message_key: str = "errors.no_tenant_membership"


class AuthSessionInfo:
    """Read-only view of a persisted authentication session."""

    def __init__(self, data: Dict[str, Any]):
        self._data = data
        self.id = data.get("id")
        self.user_id = data.get("user_id")
        self.token_hash = data.get("token_hash")
        self.created_at = data.get("created_at")
        self.expires_at = data.get("expires_at")
        self.revoked_at = data.get("revoked_at")
        self.last_used_at = data.get("last_used_at")
        self.is_active = self.revoked_at is None

    def __getitem__(self, item: str) -> Any:
        return self._data[item]

    def get(self, item: str, default: Any = None) -> Any:
        return self._data.get(item, default)


class AuthResult(tuple):
    """Result of successful authentication, supporting tuple unpacking (token_pair, user) and attribute access."""

    def __new__(cls, token_pair: TokenPair, user: User, session: Optional[AuthSessionInfo] = None):
        return super().__new__(cls, (token_pair, user))

    def __init__(self, token_pair: TokenPair, user: User, session: Optional[AuthSessionInfo] = None):
        self._token_pair = token_pair
        self._user = user
        self._session = session

    @property
    def token_pair(self) -> TokenPair:
        return self._token_pair

    @property
    def user(self) -> User:
        return self._user

    @property
    def access_token(self) -> str:
        return self._token_pair.access_token

    @property
    def session_token(self) -> str:
        return self._token_pair.refresh_token

    @property
    def refresh_token(self) -> str:
        return self._token_pair.refresh_token

    @property
    def session(self) -> Optional[AuthSessionInfo]:
        return self._session


class AuthService:
    """Orchestrator for product user authentication and tenant context resolution."""

    def __init__(
        self,
        user_repo: UserRepository,
        org_repo: OrganizationRepository,
        session_repo: AuthSessionRepository,
        attempt_repo: LoginAttemptRepository,
        token_service: TokenService,
        password_hasher: Optional[PasswordHasher] = None,
        auth_token_repo: Optional[AuthTokenRepository] = None,
        email_sender: Optional[ITransactionalEmailSender] = None,
        app_url: str = "http://localhost:3000",
        default_from: Optional[str] = None,
        session_expire_days: int = 30,
        max_login_failures: int = 5,
        lockout_window_seconds: int = 900,  # 15 minutes
        password_reset_token_expire_minutes: int = 60,
        email_verification_token_expire_hours: int = 24,
    ):
        self.user_repo = user_repo
        self.org_repo = org_repo
        self.session_repo = session_repo
        self.attempt_repo = attempt_repo
        self.token_service = token_service
        self.password_hasher = password_hasher or PasswordHasher()
        self.auth_token_repo = auth_token_repo
        self.email_sender = email_sender
        self.app_url = app_url.rstrip("/") if app_url else "http://localhost:3000"
        self.default_from = default_from
        self.session_expire_days = session_expire_days
        self.max_login_failures = max_login_failures
        self.lockout_window_seconds = lockout_window_seconds
        self.password_reset_token_expire_minutes = password_reset_token_expire_minutes
        self.email_verification_token_expire_hours = email_verification_token_expire_hours

    @staticmethod
    def _compute_identifier_hash(email: str, ip_address: Optional[str]) -> str:
        norm_email = email.strip().lower()
        ip = (ip_address or "unknown").strip()
        raw = f"{norm_email}:{ip}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def authenticate(
        self,
        email: str,
        password: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Tuple[TokenPair, User]:
        """Authenticate user credentials and issue token pair.

        Enforces brute-force lockout, inactive user checks, and constant-time comparison.
        """
        if not email or not password:
            raise InvalidCredentialsError("Email and password are required.")

        norm_email = email.strip().lower()
        ident_hash = self._compute_identifier_hash(norm_email, ip_address)

        # 1. Brute-force lockout check
        recent_failures = self.attempt_repo.count_recent_failures(ident_hash, self.lockout_window_seconds)
        if recent_failures >= self.max_login_failures:
            logger.warning(f"Brute-force lockout triggered for identifier_hash={ident_hash[:8]}...")
            raise AccountLockedError("Too many failed login attempts. Please try again later.")

        # 2. User lookup
        user = self.user_repo.get_by_email(norm_email)
        if user is None:
            # Timing attack mitigation: run constant-time dummy verification
            self.password_hasher.dummy_verify()
            self.attempt_repo.record_attempt(ident_hash, is_successful=False)
            raise InvalidCredentialsError("Invalid email or password.")

        # 3. Active status check
        if not user.is_active:
            self.attempt_repo.record_attempt(ident_hash, is_successful=False)
            raise InactiveUserError("User account is inactive. Please contact your organization administrator.")

        # 4. Password verification
        if not user.password_hash or not self.password_hasher.verify(password, user.password_hash):
            self.attempt_repo.record_attempt(ident_hash, is_successful=False)
            raise InvalidCredentialsError("Invalid email or password.")

        # 5. Clear login attempts on success
        self.attempt_repo.clear_failures(ident_hash)

        # 6. Create persistent session
        raw_refresh_token = self.token_service.generate_opaque_session_token()
        token_hash = self.token_service.hash_session_token(raw_refresh_token)
        expires_at = (datetime.now(timezone.utc) + timedelta(days=self.session_expire_days)).isoformat()
        ua_hash = hashlib.sha256(user_agent.encode("utf-8")).hexdigest() if user_agent else None

        session_record = self.session_repo.create_session(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            user_agent_hash=ua_hash,
            ip_address=ip_address,
        )
        session_id = session_record["id"]

        # 7. Create access token
        access_token = self.token_service.create_access_token(
            user_id=user.id,
            email=user.email,
            session_id=session_id,
        )

        token_pair = TokenPair(
            access_token=access_token,
            token_type="Bearer",
            expires_in=self.token_service.access_token_expire_seconds,
            refresh_token=raw_refresh_token,
        )

        session_info = AuthSessionInfo(session_record)
        return AuthResult(token_pair, user, session_info)

    def register_user(
        self,
        email: str,
        name: str,
        password: str,
        locale: str = "en",
        is_active: bool = True,
        email_verified: bool = False,
    ) -> User:
        """Register a new user with securely hashed password."""
        norm_email = email.strip().lower()
        pwd_hash = self.password_hasher.hash(password)
        now_iso = datetime.now(timezone.utc).isoformat()
        user = User(
            email=norm_email,
            full_name=name.strip(),
            password_hash=pwd_hash,
            is_active=is_active,
            locale=locale,
            email_verified_at=now_iso if email_verified else None,
        )
        user.validate()
        return self.user_repo.save(user)

    def logout(self, session_id_or_token: str) -> bool:
        """Revoke the active session by ID or raw session token."""
        if not session_id_or_token:
            return False
        if session_id_or_token.startswith("bop_sess_"):
            token_hash = self.token_service.hash_session_token(session_id_or_token)
            return self.session_repo.revoke_session_by_token_hash(token_hash)
        return self.session_repo.revoke_session(session_id_or_token)

    def get_session_by_token(self, raw_token: str) -> Optional[AuthSessionInfo]:
        """Lookup active unrevoked session by raw session token."""
        if not raw_token:
            return None
        token_hash = self.token_service.hash_session_token(raw_token)
        sess = self.session_repo.get_active_session_by_hash(token_hash)
        return AuthSessionInfo(sess) if sess else None

    def validate_access_token(self, token: str) -> Tuple[UserPrincipal, str]:
        """Validate access token signature, verify user is active, and ensure session unrevoked.

        Returns:
            Tuple of (UserPrincipal, session_id).
        """
        payload: TokenPayload = self.token_service.verify_access_token(token)

        # Verify session is still active
        session = self.session_repo.get_session_by_id(payload.session_id)
        if session is None or session.get("revoked_at") is not None:
            raise SessionExpiredOrRevokedError("Session has been revoked or is no longer valid.")

        now_iso = datetime.now(timezone.utc).isoformat()
        if session.get("expires_at") and session["expires_at"] <= now_iso:
            raise SessionExpiredOrRevokedError("Session has expired.")

        # Verify user still exists and is active
        user = self.user_repo.get_by_id(payload.user_id)
        if user is None or not user.is_active:
            raise InactiveUserError("User account is inactive or no longer exists.")

        # Touch session activity
        self.session_repo.touch_session(payload.session_id)

        principal = UserPrincipal(
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            locale=user.locale,
            is_active=user.is_active,
            session_id=payload.session_id,
            email_verified_at=user.email_verified_at,
        )
        return principal, payload.session_id

    def resolve_tenant_context(
        self,
        user_id: Any = None,
        requested_bop_organization_id: Optional[str] = None,
        user_or_id: Any = None,
    ) -> TenantContext:
        """Resolve tenant context for user, validating membership and role.

        Args:
            user_id: Authenticated user ID or UserPrincipal.
            requested_bop_organization_id: Optional X-Bop-Organization-Id header value.
            user_or_id: Optional alias for user_id.

        Returns:
            TenantContext representing the active tenant boundary.
        """
        target = user_id if user_id is not None else user_or_id
        if target is None:
            raise ValueError("user_id must be provided to resolve_tenant_context")
        uid = target.user_id if hasattr(target, "user_id") else str(target)
        memberships = self.org_repo.get_user_memberships(uid)
        if not memberships:
            raise NoOrganizationMembershipError("User does not belong to any organization.")

        target = None
        if requested_bop_organization_id and requested_bop_organization_id.strip():
            req_id = requested_bop_organization_id.strip()
            for m in memberships:
                if m.get("bop_organization_id") == req_id or m.get("organization_id") == req_id:
                    target = m
                    break
            if target is None:
                # User is not a member of the requested organization
                raise TenantAccessError(
                    f"Access denied: User '{user_id}' is not an authorized member of organization '{req_id}'"
                )
        else:
            # Default to first organization membership
            target = memberships[0]

        role = MemberRole(target["role"].lower())
        return TenantContext(
            organization_id=target["organization_id"],
            bop_organization_id=target["bop_organization_id"],
            role=role,
            membership_id=target["membership_id"],
        )

    @staticmethod
    def hash_token(raw_token: str) -> str:
        """Compute deterministic SHA-256 hash of raw auth token."""
        return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()

    def request_password_reset(self, email: str, locale: Optional[str] = None) -> None:
        """Initiate password recovery flow.

        Enumeration-safe: Always succeeds neutrally from caller perspective.
        Never reveals whether the user account exists.
        """
        if not email or not email.strip():
            return

        norm_email = email.strip().lower()
        user = self.user_repo.get_by_email(norm_email)

        # Timing attack mitigation & enumeration protection:
        # If user does not exist or is inactive, perform dummy work and return neutrally.
        if user is None or not user.is_active:
            self.password_hasher.dummy_verify()
            return

        if not self.auth_token_repo:
            logger.warning("AuthTokenRepository not configured on AuthService, cannot process password reset.")
            return

        # Invalidate/revoke any prior active password reset tokens for this user
        self.auth_token_repo.revoke_active_tokens_for_user(user.id, AuthTokenType.PASSWORD_RESET)

        # Generate high-entropy 32-byte urlsafe token
        raw_token = secrets.token_urlsafe(32)
        token_hash = self.hash_token(raw_token)

        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(minutes=self.password_reset_token_expire_minutes)).isoformat()

        token_record = AuthToken(
            id=str(uuid.uuid4()),
            user_id=user.id,
            token_hash=token_hash,
            token_type=AuthTokenType.PASSWORD_RESET,
            expires_at=expires_at,
            created_at=now.isoformat(),
        )
        self.auth_token_repo.save(token_record)

        # Dispatch transactional email if sender is configured
        if self.email_sender:
            user_locale = locale or user.locale or "en"
            reset_url = f"{self.app_url}/{user_locale}/reset-password/{raw_token}"
            subject, html_body, text_body = render_password_reset_email(
                user_name=user.full_name,
                reset_url=reset_url,
                locale=user_locale,
                expires_minutes=self.password_reset_token_expire_minutes,
            )
            msg = TransactionalEmailMessage(
                to=user.email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                category=EmailCategory.PASSWORD_RESET,
                from_email=self.default_from,
                metadata={"user_id": user.id, "token_id": token_record.id},
            )
            try:
                self.email_sender.send(msg)
            except Exception as ex:
                logger.error(f"Failed to dispatch password reset email to {user.email}: {ex}")

    def confirm_password_reset(self, raw_token: str, new_password: str) -> User:
        """Confirm password reset using single-use token and update credentials.

        Enforces token validity, expiry, single-use consumption, password policy,
        Argon2id hashing, and session revocation.
        """
        if not raw_token or not raw_token.strip():
            raise InvalidTokenError("Password reset token is required.")

        if not new_password:
            raise PasswordValidationError("New password is required.")

        if not self.auth_token_repo:
            raise RuntimeError("AuthTokenRepository is required for confirm_password_reset.")

        token_hash = self.hash_token(raw_token)
        token_record = self.auth_token_repo.get_by_token_hash(token_hash)

        if not token_record or token_record.token_type != AuthTokenType.PASSWORD_RESET:
            raise InvalidTokenError("Invalid or expired password reset token.")

        if not token_record.is_valid():
            raise InvalidTokenError("Password reset token has expired or already been used.")

        # Password strength validation
        try:
            self.password_hasher.validate_password(new_password)
        except ValueError as ex:
            raise PasswordValidationError(str(ex))

        # Lookup user
        user = self.user_repo.get_by_id(token_record.user_id)
        if not user or not user.is_active:
            raise InactiveUserError("User account is inactive or not found.")

        # Update password hash with Argon2id
        user.password_hash = self.password_hasher.hash(new_password)
        self.user_repo.save(user)

        # Mark token consumed atomically to prevent replay
        now_iso = datetime.now(timezone.utc).isoformat()
        self.auth_token_repo.consume_token(token_record.id, consumed_at=now_iso)

        # Revoke all active sessions for this user
        self.session_repo.revoke_all_user_sessions(user.id)

        logger.info(f"Password reset successfully confirmed for user {user.id} ({user.email}). Sessions revoked.")
        return user

    def send_verification_email(self, user_id: str, locale: Optional[str] = None) -> None:
        """Generate email verification token and send verification email to user."""
        user = self.user_repo.get_by_id(user_id)
        if not user or not user.is_active:
            raise InactiveUserError("User account is inactive or not found.")

        # Idempotency: if already verified, skip
        if user.is_verified:
            logger.info(f"User {user.id} is already verified. Skipping verification email.")
            return

        if not self.auth_token_repo:
            logger.warning("AuthTokenRepository not configured on AuthService, cannot send verification email.")
            return

        # Revoke any prior active verification tokens for this user
        self.auth_token_repo.revoke_active_tokens_for_user(user.id, AuthTokenType.EMAIL_VERIFICATION)

        # Generate high-entropy 32-byte urlsafe token
        raw_token = secrets.token_urlsafe(32)
        token_hash = self.hash_token(raw_token)

        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(hours=self.email_verification_token_expire_hours)).isoformat()

        token_record = AuthToken(
            id=str(uuid.uuid4()),
            user_id=user.id,
            token_hash=token_hash,
            token_type=AuthTokenType.EMAIL_VERIFICATION,
            expires_at=expires_at,
            created_at=now.isoformat(),
        )
        self.auth_token_repo.save(token_record)

        if self.email_sender:
            user_locale = locale or user.locale or "en"
            verify_url = f"{self.app_url}/{user_locale}/verify-email/{raw_token}"
            subject, html_body, text_body = render_email_verification_email(
                user_name=user.full_name,
                verify_url=verify_url,
                locale=user_locale,
                expires_hours=self.email_verification_token_expire_hours,
            )
            msg = TransactionalEmailMessage(
                to=user.email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                category=EmailCategory.EMAIL_VERIFICATION,
                from_email=self.default_from,
                metadata={"user_id": user.id, "token_id": token_record.id},
            )
            try:
                self.email_sender.send(msg)
            except Exception as ex:
                logger.error(f"Failed to dispatch verification email to {user.email}: {ex}")

    def confirm_email_verification(self, raw_token: str) -> User:
        """Confirm user's email address using single-use verification token."""
        if not raw_token or not raw_token.strip():
            raise InvalidTokenError("Verification token is required.")

        if not self.auth_token_repo:
            raise RuntimeError("AuthTokenRepository is required for confirm_email_verification.")

        token_hash = self.hash_token(raw_token)
        token_record = self.auth_token_repo.get_by_token_hash(token_hash)

        if not token_record or token_record.token_type != AuthTokenType.EMAIL_VERIFICATION:
            raise InvalidTokenError("Invalid or expired email verification token.")

        if not token_record.is_valid():
            raise InvalidTokenError("Email verification token has expired or already been used.")

        user = self.user_repo.get_by_id(token_record.user_id)
        if not user or not user.is_active:
            raise InactiveUserError("User account is inactive or not found.")

        # Mark user verified
        now_iso = datetime.now(timezone.utc).isoformat()
        user.email_verified_at = now_iso
        self.user_repo.save(user)

        # Mark token consumed
        self.auth_token_repo.consume_token(token_record.id, consumed_at=now_iso)

        logger.info(f"Email verified successfully for user {user.id} ({user.email}).")
        return user
