"""Live PostgreSQL targeted integration test for Phase P26: Account Recovery & Email Verification."""

import os
import uuid
import hashlib
import pytest
from starlette.testclient import TestClient

from bopclients.api.app import create_bopclients_api_app
from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.container import build_runtime_container
from bopclients.domain.organization import Organization, OrganizationMember
from bopclients.domain.enums import MemberRole
from bopclients.domain.auth_token import AuthTokenType

TEST_PG_URL = os.environ.get(
    "BOPCLIENTS_TEST_POSTGRES_URL",
    "postgresql://bop:bop_test_password@localhost:55432/bopclients_test",
).strip()

HAS_POSTGRES_TEST_DB = False
try:
    _test_conn = create_database_connection(TEST_PG_URL)
    _test_conn.execute("SELECT 1")
    _test_conn.close()
    HAS_POSTGRES_TEST_DB = True
except Exception:
    HAS_POSTGRES_TEST_DB = False

pytestmark = pytest.mark.skipif(
    not HAS_POSTGRES_TEST_DB,
    reason="PostgreSQL test database not accessible on port 55432",
)


@pytest.fixture
def pg_recovery_context():
    """Live Postgres database connection and container with schema 20260902_011."""
    db = create_database_connection(TEST_PG_URL)
    DatabaseMigrator.migrate(db)

    settings = RuntimeSettings(
        database_url=TEST_PG_URL,
        auth_signing_key="postgres-p26-recovery-signing-key-32chars!",
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

    suffix = uuid.uuid4().hex[:8]
    org = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name=f"PG Recovery Org {suffix}",
        slug=f"pg-rec-{suffix}",
    )
    container.org_repo.save(org)

    # Register user through auth service
    email = f"recovery-{suffix}@bopagency.test"
    user = container.auth_service.register_user(
        email=email,
        name=f"PG Recovery User {suffix}",
        password="InitialPassword123!",
        locale="es",
    )
    member = OrganizationMember(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        user_id=user.id,
        role=MemberRole.ADMIN,
    )
    container.org_repo.add_member(member)

    yield {
        "db": db,
        "container": container,
        "app": app,
        "client": client,
        "org": org,
        "email": email,
        "user": user,
        "initial_password": "InitialPassword123!",
        "suffix": suffix,
    }

    db.close()


def test_postgres_migration_011_and_table_structure(pg_recovery_context):
    """Verify migration 20260902_011 applied on live PostgreSQL and schema matches."""
    ctx = pg_recovery_context
    db = ctx["db"]
    ver = DatabaseMigrator.get_current_version(db)
    assert ver == "20260902_011"

    # Verify auth_tokens table in PostgreSQL
    tables = db.fetch_dicts(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'auth_tokens'"
    )
    assert len(tables) == 1

    # Verify email_verified_at column on users table
    columns = db.fetch_dicts(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'email_verified_at'"
    )
    assert len(columns) == 1

    # Verify indexes on auth_tokens
    indexes = db.fetch_dicts(
        "SELECT indexname FROM pg_indexes WHERE tablename = 'auth_tokens'"
    )
    index_names = {r["indexname"] for r in indexes}
    assert "idx_auth_tokens_token_hash" in index_names
    assert "idx_auth_tokens_user_type" in index_names


def test_postgres_password_reset_flow(pg_recovery_context):
    """Verify full password reset lifecycle on live PostgreSQL database."""
    ctx = pg_recovery_context
    client = ctx["client"]
    container = ctx["container"]
    db = ctx["db"]
    email = ctx["email"]
    user = ctx["user"]

    # 1. Request password reset
    resp = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": email, "locale": "es"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # Verify transactional email was delivered via in_memory sender
    sent_msgs = container.email_sender.get_sent_messages()
    assert len(sent_msgs) >= 1
    sent_msg = sent_msgs[-1]
    assert sent_msg.to == email
    assert "recuperación" in sent_msg.subject.lower() or "restablecer" in sent_msg.subject.lower()

    # Extract raw token from reset link in email
    raw_token = sent_msg.html_body.split("/reset-password/")[1].split('"')[0]

    # Verify raw token is NOT stored anywhere in PostgreSQL
    raw_token_records = db.fetch_dicts(
        "SELECT * FROM auth_tokens WHERE token_hash = %s",
        (raw_token,),
    )
    assert len(raw_token_records) == 0

    # Verify SHA-256 hash IS stored in PostgreSQL
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    hash_records = db.fetch_dicts(
        "SELECT * FROM auth_tokens WHERE token_hash = %s AND user_id = %s",
        (token_hash, user.id),
    )
    assert len(hash_records) == 1
    assert hash_records[0]["consumed_at"] is None
    assert hash_records[0]["token_type"] == AuthTokenType.PASSWORD_RESET.value

    # 2. Confirm password reset
    confirm_resp = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": raw_token,
            "new_password": "NewStrongPostgresPassword456!",
        },
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["success"] is True

    # Verify token is marked consumed in PostgreSQL
    updated_records = db.fetch_dicts(
        "SELECT * FROM auth_tokens WHERE token_hash = %s",
        (token_hash,),
    )
    assert updated_records[0]["consumed_at"] is not None

    # Verify replay fails (token reuse protection)
    replay_resp = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": raw_token,
            "new_password": "AnotherPassword789!",
        },
    )
    assert replay_resp.status_code == 400
    assert replay_resp.json()["error"]["code"] == "INVALID_TOKEN"

    # Verify old password cannot log in
    old_login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": ctx["initial_password"]},
    )
    assert old_login.status_code == 401

    # Verify new password logs in successfully
    new_login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "NewStrongPostgresPassword456!"},
    )
    assert new_login.status_code == 200
    assert "access_token" in new_login.json()


def test_postgres_email_verification_lifecycle(pg_recovery_context):
    """Verify email verification flow persists to live PostgreSQL database."""
    ctx = pg_recovery_context
    client = ctx["client"]
    container = ctx["container"]
    db = ctx["db"]
    email = ctx["email"]
    user = ctx["user"]

    # Initial state: user is unverified
    user_row = db.fetch_dicts("SELECT email_verified_at FROM users WHERE id = %s", (user.id,))
    assert user_row[0]["email_verified_at"] is None

    # Login to get bearer token
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": ctx["initial_password"]},
    )
    assert login_resp.status_code == 200
    access_token = login_resp.json()["access_token"]
    user_profile = login_resp.json()["user"]
    assert user_profile["is_verified"] is False
    assert user_profile["email_verified_at"] is None

    # Authenticated resend verification email
    resend_resp = client.post(
        "/api/v1/auth/email-verification/resend",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"locale": "es"},
    )
    assert resend_resp.status_code == 200
    assert resend_resp.json()["success"] is True

    # Extract verification token
    sent_msgs = container.email_sender.get_sent_messages()
    sent_msg = sent_msgs[-1]
    assert sent_msg.to == email
    raw_token = sent_msg.html_body.split("/verify-email/")[1].split('"')[0]

    # Confirm email verification
    confirm_resp = client.post(
        "/api/v1/auth/email-verification/confirm",
        json={"token": raw_token},
    )
    assert confirm_resp.status_code == 200
    data = confirm_resp.json()
    assert data["success"] is True

    # Verify PostgreSQL database has email_verified_at set
    updated_user = db.fetch_dicts("SELECT email_verified_at FROM users WHERE id = %s", (user.id,))
    assert updated_user[0]["email_verified_at"] is not None

    # Verify profile endpoint returns is_verified = True
    profile_resp = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert profile_resp.status_code == 200
    assert profile_resp.json()["is_verified"] is True
    assert profile_resp.json()["email_verified_at"] is not None
