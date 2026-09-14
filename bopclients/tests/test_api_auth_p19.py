"""Unit and integration tests for BopClients authentication and authorization domain.

Tests:
- Argon2id password hashing and scrypt fallback
- Hash verification and timing attack resistance
- Safe representation concealing sensitive hashes
- TokenService JWT generation, verification, expiration, tampering
- Session token generation and SHA-256 hashing
- Role-based authorization policy (OWNER, ADMIN, MEMBER, VIEWER)
- AuthService user registration, authentication, brute force lockout, and session revocation
"""

import time
import uuid
import pytest
from datetime import datetime, timezone

from bopclients.domain.auth.password import PasswordHasher
from bopclients.domain.auth.token import TokenService, TokenPayload
from bopclients.domain.auth.policy import AuthorizationPolicy, Permission
from bopclients.domain.auth.context import UserPrincipal, TenantContext, RequestContext
from bopclients.domain.user import User
from bopclients.domain.organization import Organization, OrganizationMember
from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.container import build_runtime_container
from bopclients.domain.exceptions import TenantAccessError, MemberRolePermissionError
from bopclients.domain.auth.token import TokenExpiredError, TokenSecurityError
from bopclients.application.auth_service import (
    AuthService,
    InvalidCredentialsError,
    InactiveUserError,
    AccountLockedError,
)


# ==============================================================================
# 1. PASSWORD HASHER TESTS
# ==============================================================================

class TestPasswordHasher:
    def test_argon2id_hashing_and_verification(self):
        hasher = PasswordHasher()
        plain = "SuperSecurePassword123!"
        hashed = hasher.hash_password(plain)

        assert hashed != plain
        assert "$argon2id$" in hashed
        assert hasher.verify_password(plain, hashed) is True
        assert hasher.verify_password("WrongPassword123!", hashed) is False

    def test_scrypt_fallback_hashing_and_verification(self):
        # Force scrypt algorithm
        hasher = PasswordHasher(preferred_algorithm="scrypt")
        plain = "FallbackSecretPass456!"
        hashed = hasher.hash_password(plain)

        assert hashed.startswith("$scrypt$")
        assert hasher.verify_password(plain, hashed) is True
        assert hasher.verify_password("WrongPassword", hashed) is False

    def test_hasher_verifies_across_supported_algorithms(self):
        argon_hasher = PasswordHasher(preferred_algorithm="argon2id")
        scrypt_hasher = PasswordHasher(preferred_algorithm="scrypt")
        plain = "UniversalSecret789!"

        argon_hash = argon_hasher.hash_password(plain)
        scrypt_hash = scrypt_hasher.hash_password(plain)

        # Both hashers must verify both formats
        assert argon_hasher.verify_password(plain, scrypt_hash) is True
        assert scrypt_hasher.verify_password(plain, argon_hash) is True

    def test_dummy_verify_takes_measurable_time(self):
        hasher = PasswordHasher()
        start = time.perf_counter()
        hasher.dummy_verify()
        elapsed = time.perf_counter() - start
        # Dummy verify should perform genuine computation (at least 1ms)
        assert elapsed > 0.001

    def test_random_salts_unique_per_hash_argon2id(self):
        hasher = PasswordHasher(preferred_algorithm="argon2id")
        plain = "CommonPassword987!"
        hash1 = hasher.hash_password(plain)
        hash2 = hasher.hash_password(plain)

        assert hash1 != hash2
        assert hasher.verify_password(plain, hash1) is True
        assert hasher.verify_password(plain, hash2) is True

    def test_random_salts_unique_per_hash_scrypt(self):
        hasher = PasswordHasher(preferred_algorithm="scrypt")
        plain = "CommonPassword987!"
        hash1 = hasher.hash_password(plain)
        hash2 = hasher.hash_password(plain)

        assert hash1 != hash2
        assert hasher.verify_password(plain, hash1) is True
        assert hasher.verify_password(plain, hash2) is True

    def test_empty_or_malformed_hash_returns_false(self):
        hasher = PasswordHasher()
        assert hasher.verify_password("password", "") is False
        assert hasher.verify_password("password", "invalid_format_string") is False
        assert hasher.verify_password("", "$argon2id$v=19$m=65536,t=3,p=4$dummy$dummy") is False


# ==============================================================================
# 2. TOKEN SERVICE TESTS
# ==============================================================================

class TestTokenService:
    @pytest.fixture
    def token_service(self):
        return TokenService(signing_key="unit-test-signing-key-minimum-32-chars-long!", expire_seconds=3600)

    def test_generate_and_decode_access_token(self, token_service):
        user_id = str(uuid.uuid4())
        email = "analyst@example.com"
        session_id = str(uuid.uuid4())

        token = token_service.create_access_token(user_id=user_id, email=email, session_id=session_id)
        payload = token_service.decode_access_token(token)

        assert payload.user_id == user_id
        assert payload.email == email
        assert payload.session_id == session_id
        assert payload.expires_at > time.time()

    def test_expired_token_raises_error(self):
        svc = TokenService(signing_key="unit-test-signing-key-minimum-32-chars-long!", expire_seconds=-10, clock_skew_seconds=0)
        token = svc.create_access_token("u-1", "user@example.com", "s-1")
        with pytest.raises(TokenExpiredError, match="Token has expired"):
            svc.decode_access_token(token)

    def test_tampered_token_signature_rejected(self, token_service):
        token = token_service.create_access_token("u-1", "user@example.com", "s-1")
        parts = token.split(".")
        # Tamper payload
        tampered = f"{parts[0]}.eyJyYW5kb20iOiAidmFsdWUifQ.{parts[2]}"
        with pytest.raises(TokenSecurityError, match="Invalid token signature"):
            token_service.decode_access_token(tampered)

    def test_different_signing_key_rejected(self, token_service):
        token = token_service.create_access_token("u-1", "user@example.com", "s-1")
        other_svc = TokenService(signing_key="completely-different-signing-key-for-test-32c", expire_seconds=3600)
        with pytest.raises(TokenSecurityError):
            other_svc.decode_access_token(token)

    def test_session_token_entropy_and_hashing(self, token_service):
        sess_token_1 = token_service.generate_session_token()
        sess_token_2 = token_service.generate_session_token()

        assert sess_token_1.startswith("bop_sess_")
        assert sess_token_2.startswith("bop_sess_")
        assert sess_token_1 != sess_token_2
        assert len(sess_token_1) >= 40

        hash_1 = token_service.hash_session_token(sess_token_1)
        hash_2 = token_service.hash_session_token(sess_token_2)
        assert hash_1 != hash_2
        assert len(hash_1) == 64  # SHA-256 hex string

    def test_audience_and_issuer_verification(self, token_service):
        token = token_service.create_access_token(user_id="u1", email="u1@test.com", session_id="s1")
        payload = token_service.decode_access_token(token)
        assert payload.aud == "bopclients-api"
        assert payload.iss == "bopclients"

        # Wrong audience
        wrong_aud_token = token_service.create_access_token("u1", "u1@test.com", "s1", custom_claims={"aud": "other-api"})
        with pytest.raises(TokenSecurityError, match="Invalid audience"):
            token_service.decode_access_token(wrong_aud_token)

        # Wrong issuer
        wrong_iss_token = token_service.create_access_token("u1", "u1@test.com", "s1", custom_claims={"iss": "rogue-issuer"})
        with pytest.raises(TokenSecurityError, match="Invalid issuer"):
            token_service.decode_access_token(wrong_iss_token)

    def test_unsupported_algorithm_rejected(self, token_service):
        import base64
        import json
        hdr = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode()
        body = base64.urlsafe_b64encode(json.dumps({"sub": "u1", "iss": "bopclients", "aud": "bopclients-api", "exp": 9999999999}).encode()).rstrip(b"=").decode()
        none_token = f"{hdr}.{body}."
        with pytest.raises(TokenSecurityError, match="Unsupported algorithm"):
            token_service.decode_access_token(none_token)


# ==============================================================================
# 3. USER ENTITY SECURITY & SENSITIVE FIELD MASKING
# ==============================================================================

class TestUserSecurity:
    def test_user_repr_masks_password_hash(self):
        user = User(
            id=str(uuid.uuid4()),
            email="developer@example.com",
            name="Developer",
            password_hash="$argon2id$v=19$m=65536,t=3,p=4$secretsalt$secretderivedhash",
            is_active=True,
            locale="en",
        )
        repr_str = repr(user)
        assert "secretsalt" not in repr_str
        assert "secretderivedhash" not in repr_str
        assert "password_hash=***REDACTED***" in repr_str

    def test_user_defaults(self):
        user = User(id="u-default", email="test@example.com", name="Test")
        assert user.is_active is True
        assert user.locale == "en"
        assert user.password_hash is None


# ==============================================================================
# 4. AUTHORIZATION POLICY & PERMISSIONS
# ==============================================================================

class TestAuthorizationPolicy:
    def test_owner_role_has_full_permissions(self):
        for perm in Permission:
            assert AuthorizationPolicy.has_permission("OWNER", perm) is True

    def test_admin_role_cannot_transfer_ownership(self):
        assert AuthorizationPolicy.has_permission("ADMIN", Permission.CAMPAIGN_CREATE) is True
        assert AuthorizationPolicy.has_permission("ADMIN", Permission.ORGANIZATION_MANAGE) is True
        assert AuthorizationPolicy.has_permission("ADMIN", Permission.MEMBERS_MANAGE) is True
        assert AuthorizationPolicy.has_permission("ADMIN", Permission.OWNER_TRANSFER) is False
        assert AuthorizationPolicy.has_permission("ADMIN", Permission.ORGANIZATION_DELETE) is False

    def test_member_role_scoped_permissions(self):
        # Members can manage campaigns, icps, prospects, signals
        assert AuthorizationPolicy.has_permission("MEMBER", Permission.CAMPAIGN_CREATE) is True
        assert AuthorizationPolicy.has_permission("MEMBER", Permission.PROSPECT_UPDATE) is True
        assert AuthorizationPolicy.has_permission("MEMBER", Permission.SIGNALS_READ) is True
        # Members cannot manage org settings, members, or delete org
        assert AuthorizationPolicy.has_permission("MEMBER", Permission.ORGANIZATION_MANAGE) is False
        assert AuthorizationPolicy.has_permission("MEMBER", Permission.ORGANIZATION_DELETE) is False
        assert AuthorizationPolicy.has_permission("MEMBER", Permission.MEMBERS_MANAGE) is False

    def test_viewer_role_read_only(self):
        assert AuthorizationPolicy.has_permission("VIEWER", Permission.CAMPAIGN_READ) is True
        assert AuthorizationPolicy.has_permission("VIEWER", Permission.PROSPECT_READ) is True
        assert AuthorizationPolicy.has_permission("VIEWER", Permission.SIGNALS_READ) is True
        assert AuthorizationPolicy.has_permission("VIEWER", Permission.MONITORING_READ) is True

        # Write operations denied
        assert AuthorizationPolicy.has_permission("VIEWER", Permission.CAMPAIGN_CREATE) is False
        assert AuthorizationPolicy.has_permission("VIEWER", Permission.CAMPAIGN_UPDATE) is False
        assert AuthorizationPolicy.has_permission("VIEWER", Permission.PROSPECT_UPDATE) is False
        assert AuthorizationPolicy.has_permission("VIEWER", Permission.INTEGRATION_MANAGE) is False

    def test_invalid_role_denied(self):
        assert AuthorizationPolicy.has_permission("GUEST", Permission.CAMPAIGN_READ) is False
        assert AuthorizationPolicy.has_permission("UNKNOWN", Permission.ORGANIZATION_READ) is False


# ==============================================================================
# 5. AUTH SERVICE INTEGRATION TESTS
# ==============================================================================

class TestAuthServiceIntegration:
    @pytest.fixture
    def container(self):
        db = create_database_connection(":memory:")
        DatabaseMigrator.migrate(db)
        settings = RuntimeSettings(
            database_url=":memory:",
            auth_signing_key="test-key-32-chars-long-minimum-length!",
            auth_token_expire_seconds=1800,
            auth_session_expire_days=7,
        )
        return build_runtime_container(settings, db=db)

    def test_user_registration_and_authentication(self, container):
        auth_service = container.auth_service
        user = auth_service.register_user(
            email="founder@example.com",
            name="Alice Founder",
            password="StrongPassword123!",
            locale="es",
        )

        assert user.email == "founder@example.com"
        assert user.name == "Alice Founder"
        assert user.locale == "es"
        assert user.password_hash is not None
        assert user.password_hash != "StrongPassword123!"

        # Authenticate
        auth_res = auth_service.authenticate(
            email="FOUNDER@example.com",  # verify case-insensitivity
            password="StrongPassword123!",
            ip_address="127.0.0.1",
        )

        assert auth_res.user.id == user.id
        assert auth_res.access_token is not None
        assert auth_res.session_token is not None
        assert auth_res.session.is_active is True

    def test_invalid_password_raises_credentials_error(self, container):
        auth_service = container.auth_service
        auth_service.register_user("bob@example.com", "Bob", "CorrectPass123!")

        with pytest.raises(InvalidCredentialsError):
            auth_service.authenticate("bob@example.com", "WrongPassword999!", ip_address="127.0.0.1")

    def test_nonexistent_user_raises_credentials_error_with_dummy_timing(self, container):
        auth_service = container.auth_service
        start = time.perf_counter()
        with pytest.raises(InvalidCredentialsError):
            auth_service.authenticate("nonexistent@example.com", "SomePassword123!", ip_address="127.0.0.1")
        elapsed = time.perf_counter() - start
        assert elapsed > 0.001  # dummy hash took time

    def test_inactive_user_cannot_authenticate(self, container):
        auth_service = container.auth_service
        user = auth_service.register_user("inactive@example.com", "Inactive", "Pass12345!")
        user.is_active = False
        container.user_repo.save(user)

        with pytest.raises(InactiveUserError, match="User account is inactive"):
            auth_service.authenticate("inactive@example.com", "Pass12345!", ip_address="127.0.0.1")

    def test_brute_force_lockout_after_5_failures(self, container):
        auth_service = container.auth_service
        auth_service.register_user("target@example.com", "Target", "TargetPass123!")

        # 5 consecutive failures
        for i in range(5):
            with pytest.raises(InvalidCredentialsError):
                auth_service.authenticate("target@example.com", f"WrongPass{i}", ip_address="10.0.0.1")

        # 6th attempt triggers AccountLockedError
        with pytest.raises(AccountLockedError, match="Too many failed login attempts"):
            auth_service.authenticate("target@example.com", "TargetPass123!", ip_address="10.0.0.1")

    def test_logout_revokes_session(self, container):
        auth_service = container.auth_service
        auth_service.register_user("carol@example.com", "Carol", "Pass12345!")
        auth_res = auth_service.authenticate("carol@example.com", "Pass12345!")

        # Verify session is retrievable by raw session token
        session = auth_service.get_session_by_token(auth_res.session_token)
        assert session is not None
        assert session.id == auth_res.session.id

        # Logout
        revoked = auth_service.logout(auth_res.session_token)
        assert revoked is True

        # Subsequent lookup returns None
        assert auth_service.get_session_by_token(auth_res.session_token) is None

    def test_resolve_tenant_context_membership_verification(self, container):
        auth_service = container.auth_service
        user = auth_service.register_user("dan@example.com", "Dan", "Pass12345!")
        principal = UserPrincipal(user_id=user.id, email=user.email, name=user.name, is_active=True, locale="en")

        # Create two organizations
        org1 = Organization(id=str(uuid.uuid4()), bop_organization_id=str(uuid.uuid4()), name="Org One", slug="org-one")
        org2 = Organization(id=str(uuid.uuid4()), bop_organization_id=str(uuid.uuid4()), name="Org Two", slug="org-two")
        container.org_repo.save(org1)
        container.org_repo.save(org2)

        # Add user as ADMIN to Org 1 only
        mem = OrganizationMember(id=str(uuid.uuid4()), organization_id=org1.id, user_id=user.id, role="ADMIN")
        container.org_repo.add_member(mem)

        # Resolve context for Org 1 -> succeeds
        ctx1 = auth_service.resolve_tenant_context(principal, org1.id)
        assert ctx1.role in ("ADMIN", "admin", "MemberRole.ADMIN") or ctx1.role == "admin"
        assert ctx1.is_admin is True
        assert ctx1.can_perform(Permission.CAMPAIGN_CREATE) is True
        assert ctx1.can_perform(Permission.OWNER_TRANSFER) is False

        # Resolve context by bop_organization_id -> succeeds
        ctx1_bop = auth_service.resolve_tenant_context(principal, org1.bop_organization_id)
        assert ctx1_bop.organization_id == org1.id

        # Resolve context for Org 2 -> raises TenantAccessError (404)
        with pytest.raises(TenantAccessError):
            auth_service.resolve_tenant_context(principal, org2.id)

        # Nonexistent org -> raises TenantAccessError (404)
        with pytest.raises(TenantAccessError):
            auth_service.resolve_tenant_context(principal, str(uuid.uuid4()))

    def test_revoked_session_rejects_access_token(self, container):
        auth_service = container.auth_service
        user = auth_service.register_user("revoketest@example.com", "Revoke Test", "Pass12345!")
        auth_res = auth_service.authenticate("revoketest@example.com", "Pass12345!")
        access_token = auth_res.access_token

        # Before revocation: token validates successfully
        principal, sess_id = auth_service.validate_access_token(access_token)
        assert principal.user_id == user.id

        # Revoke session
        auth_service.logout(auth_res.session.id)

        # After revocation: token is immediately rejected
        from bopclients.application.auth_service import SessionExpiredOrRevokedError
        with pytest.raises(SessionExpiredOrRevokedError, match="revoked"):
            auth_service.validate_access_token(access_token)
