"""Live PostgreSQL targeted integration test for Phase P24: Secure Team Invitations."""

import os
import uuid
import hashlib
import pytest
from datetime import datetime, timezone
from starlette.testclient import TestClient

from bopclients.api.app import create_bopclients_api_app
from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus
from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.container import build_runtime_container
from bopclients.domain.organization import Organization, OrganizationMember
from bopclients.domain.enums import MemberRole, InvitationStatus

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
def pg_invitations_context():
    """Live Postgres database connection and container with schema 20260902_010."""
    db = create_database_connection(TEST_PG_URL)
    applied_ver = DatabaseMigrator.migrate(db)

    settings = RuntimeSettings(
        database_url=TEST_PG_URL,
        auth_signing_key="postgres-p24-signing-key-minimum-32-chars-long!",
        auth_token_expire_seconds=3600,
        invitation_dev_token_exposure=True,
    )
    container = build_runtime_container(settings, db=db)
    app = create_bopclients_api_app(container)
    client = TestClient(app)

    # Seed an isolated organization for this test run
    suffix = uuid.uuid4().hex[:8]
    org = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name=f"PG Invitations Corp {suffix}",
        slug=f"pg-inv-corp-{suffix}",
    )
    container.org_repo.save(org)

    owner = container.auth_service.register_user(
        email=f"owner_{suffix}@pgcorp.com",
        name="PG Owner",
        password="Password123!",
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org.id,
            user_id=owner.id,
            role=MemberRole.OWNER,
        )
    )
    tokens, _ = container.auth_service.authenticate(owner.email, "Password123!")

    yield {
        "db": db,
        "container": container,
        "client": client,
        "org": org,
        "owner": owner,
        "owner_token": tokens.access_token,
        "applied_version": applied_ver,
    }
    db.close()


def test_postgres_migration_010_and_table_structure(pg_invitations_context):
    """Verify migration 20260902_010 applied on live PostgreSQL and table exists."""
    ctx = pg_invitations_context
    db = ctx["db"]
    ver = DatabaseMigrator.get_current_version(db)
    assert ver in ("20260902_010", "20260902_011")

    # Verify table in PostgreSQL information_schema
    tables = db.fetch_dicts(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'organization_invitations'"
    )
    assert len(tables) == 1

    # Verify indexes in PostgreSQL pg_indexes
    indexes = db.fetch_dicts(
        "SELECT indexname FROM pg_indexes WHERE tablename = 'organization_invitations'"
    )
    index_names = {r["indexname"] for r in indexes}
    assert "idx_invitations_org" in index_names
    assert "idx_invitations_token_hash" in index_names


def test_postgres_invitation_lifecycle_and_acceptance(pg_invitations_context):
    """Test full invitation lifecycle and atomic acceptance against live PostgreSQL."""
    ctx = pg_invitations_context
    client = ctx["client"]
    container = ctx["container"]
    org = ctx["org"]
    owner_token = ctx["owner_token"]

    headers = {
        "Authorization": f"Bearer {owner_token}",
        "X-Bop-Organization-Id": org.bop_organization_id,
    }

    invite_email = f"invited_{uuid.uuid4().hex[:6]}@example.com"

    # 1. Create invitation via API
    create_res = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": invite_email, "role": "admin"},
        headers=headers,
    )
    assert create_res.status_code == 201
    data = create_res.json()
    inv_id = data["id"]
    raw_token = data["raw_token"]
    assert raw_token is not None

    # 2. Verify PostgreSQL direct row
    db = ctx["db"]
    pg_rows = db.fetch_dicts(
        "SELECT * FROM organization_invitations WHERE id = %s",
        (inv_id,),
    )
    assert len(pg_rows) == 1
    pg_row = pg_rows[0]
    assert pg_row["status"] == "pending"
    assert pg_row["role"] == "admin"
    assert pg_row["token_hash"] == hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    # 3. Public inspection endpoint
    inspect_res = client.get(f"/api/v1/invitations/{raw_token}")
    assert inspect_res.status_code == 200
    assert inspect_res.json()["organization_name"] == org.name
    assert inspect_res.json()["email"] == invite_email

    # 4. Register & accept against live PostgreSQL
    reg_res = client.post(
        "/api/v1/invitations/register-and-accept",
        json={
            "token": raw_token,
            "name": "Live PG User",
            "password": "SecurePassword123!",
            "locale": "es",
        },
    )
    assert reg_res.status_code == 201
    reg_data = reg_res.json()
    assert reg_data["role"] == "admin"
    assert reg_data["organization_id"] == org.id

    # 5. Check PostgreSQL membership table and invitation state
    updated_inv = db.fetch_dicts(
        "SELECT * FROM organization_invitations WHERE id = %s",
        (inv_id,),
    )[0]
    assert updated_inv["status"] == "accepted"
    assert updated_inv["accepted_at"] is not None

    members = db.fetch_dicts(
        "SELECT * FROM organization_members WHERE organization_id = %s AND user_id = %s",
        (org.id, reg_data["user_id"]),
    )
    assert len(members) == 1
    assert members[0]["role"] == "admin"


def test_postgres_resend_token_rotation_and_hash_persistence(pg_invitations_context):
    """Verify resend rotates token_hash and persists new hash on live PostgreSQL."""
    ctx = pg_invitations_context
    client = ctx["client"]
    org = ctx["org"]
    owner_token = ctx["owner_token"]
    db = ctx["db"]

    headers = {
        "Authorization": f"Bearer {owner_token}",
        "X-Bop-Organization-Id": org.bop_organization_id,
    }

    invite_email = f"resend_{uuid.uuid4().hex[:6]}@example.com"

    # 1. Invitation has hash A
    create_res = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": invite_email, "role": "member"},
        headers=headers,
    )
    assert create_res.status_code == 201
    create_data = create_res.json()
    inv_id = create_data["id"]
    token_a = create_data["raw_token"]
    assert token_a is not None

    pg_row_a = db.fetch_dicts(
        "SELECT * FROM organization_invitations WHERE id = %s",
        (inv_id,),
    )[0]
    hash_a = pg_row_a["token_hash"]
    expected_hash_a = hashlib.sha256(token_a.encode("utf-8")).hexdigest()
    assert hash_a == expected_hash_a

    # 2. Resend executes
    resend_res = client.post(
        f"/api/v1/organizations/current/invitations/{inv_id}/resend",
        json={"locale": "es"},
        headers=headers,
    )
    assert resend_res.status_code == 200
    resend_data = resend_res.json()
    token_b = resend_data["raw_token"]
    assert token_b is not None

    # 3. DB now contains hash B
    pg_row_b = db.fetch_dicts(
        "SELECT * FROM organization_invitations WHERE id = %s",
        (inv_id,),
    )[0]
    hash_b = pg_row_b["token_hash"]
    expected_hash_b = hashlib.sha256(token_b.encode("utf-8")).hexdigest()
    assert hash_b == expected_hash_b

    # 4. hash A != hash B
    assert hash_a != hash_b
    assert token_a != token_b

    # 5. Old token rejected
    old_inspect = client.get(f"/api/v1/invitations/{token_a}")
    assert old_inspect.status_code == 404

    # 6. New token accepted / valid
    new_inspect = client.get(f"/api/v1/invitations/{token_b}")
    assert new_inspect.status_code == 200
    assert new_inspect.json()["organization_name"] == org.name
    assert new_inspect.json()["email"] == invite_email

    # 7. No raw token persisted in database
    for col, val in pg_row_b.items():
        assert val != token_a
        assert val != token_b
