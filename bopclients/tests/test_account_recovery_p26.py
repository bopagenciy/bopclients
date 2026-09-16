"""Targeted tests for Phase P26: Account Recovery & Email Verification."""

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from bopclients.domain.organization import Organization, OrganizationMember
from bopclients.domain.enums import MemberRole, InvitationStatus
from bopclients.domain.auth_token import AuthToken, AuthTokenType
from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.container import build_runtime_container
from bopclients.api.app import create_bopclients_api_app


@pytest.fixture
def recovery_ctx():
    """Builds a test environment with InMemoryEmailSender and pre-seeded org/user."""
    db = create_database_connection(":memory:")
    DatabaseMigrator.migrate(db)

    settings = RuntimeSettings(
        database_url="sqlite:///:memory:",
        auth_signing_key="p26-test-signing-key-minimum-32-chars-long!",
        auth_token_expire_seconds=3600,
        email_provider="in_memory",
        email_from="support@bopclients.com",
        email_api_key="re_test_key_secret",
        app_url="https://app.bopclients.com",
        password_reset_token_expire_minutes=60,
        email_verification_token_expire_hours=24,
    )
    container = build_runtime_container(settings=settings, db=db)
    app = create_bopclients_api_app(container=container, settings=settings)
    client = TestClient(app)

    # Seed Org
    org = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name="Acme Corp",
        slug="acme-corp",
    )
    container.org_repo.save(org)

    # Seed User
    user = container.auth_service.register_user(
        email="user@acme.com",
        name="Alice User",
        password="Password123!",
        locale="en",
    )
    member = OrganizationMember(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        user_id=user.id,
        role=MemberRole.ADMIN,
    )
    container.org_repo.add_member(member)

    return {
        "db": db,
        "settings": settings,
        "container": container,
        "app": app,
        "client": client,
        "org": org,
        "user": user,
    }


def test_password_reset_request_existing_user(recovery_ctx):
    """Test requesting password reset generates token and sends email."""
    client = recovery_ctx["client"]
    container = recovery_ctx["container"]
    email_sender = container.email_sender

    res = client.post("/api/v1/auth/password-reset/request", json={"email": "user@acme.com"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "If the email is registered" in data["message"]

    # Verify email was dispatched
    sent = email_sender.get_sent_messages()
    assert len(sent) == 1
    msg = sent[0]
    assert msg.to == "user@acme.com"
    assert "Reset your BopClients password" in msg.subject
    assert "/reset-password/" in msg.html_body

    # Verify raw token is NOT in database, only hash
    tokens = container.db.fetch_dicts("SELECT * FROM auth_tokens WHERE user_id = ?", (recovery_ctx["user"].id,))
    assert len(tokens) == 1
    stored = tokens[0]
    assert stored["token_type"] == "password_reset"
    assert len(stored["token_hash"]) == 64
    assert stored["consumed_at"] is None


def test_password_reset_request_nonexistent_email(recovery_ctx):
    """Test neutral response for non-existent email preventing enumeration."""
    client = recovery_ctx["client"]
    container = recovery_ctx["container"]
    email_sender = container.email_sender

    res = client.post("/api/v1/auth/password-reset/request", json={"email": "nonexistent@acme.com"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True

    # No email should be dispatched
    assert len(email_sender.get_sent_messages()) == 0


def test_password_reset_confirm_flow(recovery_ctx):
    """Test full confirm password reset flow, Argon2id update, and session revocation."""
    client = recovery_ctx["client"]
    container = recovery_ctx["container"]
    email_sender = container.email_sender

    # Log in initially to obtain active session
    login_res = client.post("/api/v1/auth/login", json={"email": "user@acme.com", "password": "Password123!"})
    assert login_res.status_code == 200
    initial_access_token = login_res.json()["access_token"]

    # Verify initial session is valid
    me_res = client.get("/api/v1/me", headers={"Authorization": f"Bearer {initial_access_token}"})
    assert me_res.status_code == 200

    # Request password reset
    client.post("/api/v1/auth/password-reset/request", json={"email": "user@acme.com"})
    msg = email_sender.get_sent_messages()[-1]

    # Extract raw token from reset URL
    raw_token = msg.html_body.split("/reset-password/")[1].split('"')[0]

    # Confirm password reset with new password
    confirm_res = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw_token, "new_password": "NewSecurePassword456!"},
    )
    assert confirm_res.status_code == 200
    assert confirm_res.json()["success"] is True

    # 1. Previous access token is now revoked because sessions were invalidated
    stale_me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {initial_access_token}"})
    assert stale_me.status_code == 401

    # 2. Old password fails authentication
    old_login = client.post("/api/v1/auth/login", json={"email": "user@acme.com", "password": "Password123!"})
    assert old_login.status_code == 401

    # 3. New password authenticates successfully
    new_login = client.post("/api/v1/auth/login", json={"email": "user@acme.com", "password": "NewSecurePassword456!"})
    assert new_login.status_code == 200

    # 4. Replay protection: cannot reuse same reset token
    replay_res = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw_token, "new_password": "AnotherPassword789!"},
    )
    assert replay_res.status_code == 400
    assert replay_res.json()["error"]["code"] == "INVALID_TOKEN"


def test_password_reset_expired_token(recovery_ctx):
    """Test expired password reset token is rejected."""
    client = recovery_ctx["client"]
    container = recovery_ctx["container"]

    # Request reset
    client.post("/api/v1/auth/password-reset/request", json={"email": "user@acme.com"})
    raw_token = container.email_sender.get_sent_messages()[-1].html_body.split("/reset-password/")[1].split('"')[0]

    # Manually expire the token in database
    past_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    container.db.execute("UPDATE auth_tokens SET expires_at = ?", (past_iso,))
    container.db.commit()

    res = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw_token, "new_password": "NewSecurePassword456!"},
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_TOKEN"


def test_email_verification_flow(recovery_ctx):
    """Test sending and confirming email verification."""
    client = recovery_ctx["client"]
    container = recovery_ctx["container"]
    email_sender = container.email_sender

    # Log in as Alice User
    login_res = client.post("/api/v1/auth/login", json={"email": "user@acme.com", "password": "Password123!"})
    token = login_res.json()["access_token"]
    user_item = login_res.json()["user"]
    assert user_item["is_verified"] is False
    assert user_item["email_verified_at"] is None

    # Resend verification email
    resend_res = client.post(
        "/api/v1/auth/email-verification/resend",
        headers={"Authorization": f"Bearer {token}"},
        json={"locale": "es"},
    )
    assert resend_res.status_code == 200
    assert resend_res.json()["success"] is True

    # Verify email was sent with Spanish subject
    sent = email_sender.get_sent_messages()
    assert len(sent) == 1
    msg = sent[0]
    assert "Verifique su dirección de correo electrónico" in msg.subject
    assert "/verify-email/" in msg.html_body

    # Extract token
    raw_token = msg.html_body.split("/verify-email/")[1].split('"')[0]

    # Confirm verification
    confirm_res = client.post("/api/v1/auth/email-verification/confirm", json={"token": raw_token})
    assert confirm_res.status_code == 200
    assert confirm_res.json()["success"] is True

    # User profile should now show is_verified = True
    me_res = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    profile = me_res.json()
    assert profile["is_verified"] is True
    assert profile["email_verified_at"] is not None

    # Replay protection: cannot reuse verification token
    replay_res = client.post("/api/v1/auth/email-verification/confirm", json={"token": raw_token})
    assert replay_res.status_code == 400
    assert replay_res.json()["error"]["code"] == "INVALID_TOKEN"


def test_invitation_registration_verifies_email_automatically(recovery_ctx):
    """Test that register-and-accept automatically marks email_verified_at."""
    container = recovery_ctx["container"]
    org = recovery_ctx["org"]
    inviter = recovery_ctx["user"]

    # Create invitation
    invitation, raw_token, delivery = container.invitation_service.create_invitation(
        inviter_user_id=inviter.id,
        org_id=org.id,
        email="newinvitee@acme.com",
        role=MemberRole.MEMBER,
    )

    # Register and accept via invitation
    inv, member, new_user, auth_res = container.invitation_service.register_and_accept(
        raw_token=raw_token,
        name="Bob Invitee",
        password="SecurePassword999!",
        locale="en",
    )

    # Verify user is marked email_verified_at immediately
    assert new_user.email_verified_at is not None
    assert new_user.is_verified is True

    # Verify persisted in database
    db_user = container.user_repo.get_by_id(new_user.id)
    assert db_user.email_verified_at is not None
    assert db_user.is_verified is True


def test_password_reset_weak_password_rejected(recovery_ctx):
    """Test that password reset rejects passwords shorter than 8 characters."""
    client = recovery_ctx["client"]
    container = recovery_ctx["container"]

    client.post("/api/v1/auth/password-reset/request", json={"email": "user@acme.com"})
    raw_token = container.email_sender.get_sent_messages()[-1].html_body.split("/reset-password/")[1].split('"')[0]

    # Attempt reset with short password
    res = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw_token, "new_password": "short"},
    )
    assert res.status_code in (400, 422)


def test_email_verification_invalid_token(recovery_ctx):
    """Test confirming email verification with a completely invalid token."""
    client = recovery_ctx["client"]
    res = client.post("/api/v1/auth/email-verification/confirm", json={"token": "invalid_fake_token_123456"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_TOKEN"


def test_email_verification_expired_token(recovery_ctx):
    """Test expired email verification token is rejected (Item C)."""
    client = recovery_ctx["client"]
    container = recovery_ctx["container"]

    # Log in and request verification email
    login_res = client.post("/api/v1/auth/login", json={"email": "user@acme.com", "password": "Password123!"})
    token = login_res.json()["access_token"]
    client.post(
        "/api/v1/auth/email-verification/resend",
        headers={"Authorization": f"Bearer {token}"},
        json={"locale": "en"},
    )
    raw_token = container.email_sender.get_sent_messages()[-1].html_body.split("/verify-email/")[1].split('"')[0]

    # Expire the token in database
    past_iso = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    container.db.execute("UPDATE auth_tokens SET expires_at = ?", (past_iso,))
    container.db.commit()

    res = client.post("/api/v1/auth/email-verification/confirm", json={"token": raw_token})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_TOKEN"


def test_verification_resend_rotation(recovery_ctx):
    """Test verification resend rotates tokens, invalidating token A while token B is valid (Item D)."""
    client = recovery_ctx["client"]
    container = recovery_ctx["container"]

    login_res = client.post("/api/v1/auth/login", json={"email": "user@acme.com", "password": "Password123!"})
    token = login_res.json()["access_token"]

    # Issue token A
    res_a = client.post(
        "/api/v1/auth/email-verification/resend",
        headers={"Authorization": f"Bearer {token}"},
        json={"locale": "en"},
    )
    assert res_a.status_code == 200
    token_a = container.email_sender.get_sent_messages()[-1].html_body.split("/verify-email/")[1].split('"')[0]

    # Issue token B (resend)
    res_b = client.post(
        "/api/v1/auth/email-verification/resend",
        headers={"Authorization": f"Bearer {token}"},
        json={"locale": "es"},
    )
    assert res_b.status_code == 200
    token_b = container.email_sender.get_sent_messages()[-1].html_body.split("/verify-email/")[1].split('"')[0]

    # Token B must be distinct from Token A
    assert token_b != token_a

    # Token A is revoked / invalid
    res_confirm_a = client.post("/api/v1/auth/email-verification/confirm", json={"token": token_a})
    assert res_confirm_a.status_code == 400
    assert res_confirm_a.json()["error"]["code"] == "INVALID_TOKEN"

    # Token B is valid and succeeds
    res_confirm_b = client.post("/api/v1/auth/email-verification/confirm", json={"token": token_b})
    assert res_confirm_b.status_code == 200
    assert res_confirm_b.json()["success"] is True


def test_wrong_token_purpose(recovery_ctx):
    """Test cross-purpose token rejection: reset token cannot verify email and vice versa (Item E)."""
    client = recovery_ctx["client"]
    container = recovery_ctx["container"]

    # Generate password reset token
    client.post("/api/v1/auth/password-reset/request", json={"email": "user@acme.com"})
    reset_token = container.email_sender.get_sent_messages()[-1].html_body.split("/reset-password/")[1].split('"')[0]

    # Generate email verification token
    login_res = client.post("/api/v1/auth/login", json={"email": "user@acme.com", "password": "Password123!"})
    jwt_token = login_res.json()["access_token"]
    client.post(
        "/api/v1/auth/email-verification/resend",
        headers={"Authorization": f"Bearer {jwt_token}"},
        json={"locale": "en"},
    )
    verify_token = container.email_sender.get_sent_messages()[-1].html_body.split("/verify-email/")[1].split('"')[0]

    # 1. Verification token cannot be used to reset password
    bad_reset = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": verify_token, "new_password": "NewSecurePassword456!"},
    )
    assert bad_reset.status_code == 400
    assert bad_reset.json()["error"]["code"] == "INVALID_TOKEN"

    # 2. Reset token cannot be used to verify email
    bad_verify = client.post("/api/v1/auth/email-verification/confirm", json={"token": reset_token})
    assert bad_verify.status_code == 400
    assert bad_verify.json()["error"]["code"] == "INVALID_TOKEN"


def test_enumeration_safety_under_delivery_failure(recovery_ctx):
    """Test public responses remain indistinguishable when email delivery fails (Item G)."""
    client = recovery_ctx["client"]
    container = recovery_ctx["container"]

    # Inject failure into email_sender
    failing_sender = MagicMock()
    failing_sender.send.side_effect = RuntimeError("SMTP/API connection failure")
    container.email_sender = failing_sender
    container.auth_service.email_sender = failing_sender

    # Request reset for existing registered email
    res_existing = client.post("/api/v1/auth/password-reset/request", json={"email": "user@acme.com"})
    assert res_existing.status_code == 200
    data_existing = res_existing.json()

    # Request reset for non-existent unknown email
    res_unknown = client.post("/api/v1/auth/password-reset/request", json={"email": "totallyunknown@acme.com"})
    assert res_unknown.status_code == 200
    data_unknown = res_unknown.json()

    # Both responses must be identical in structure and text
    assert data_existing == data_unknown
    assert data_existing["success"] is True
    assert "If the email is registered" in data_existing["message"]
