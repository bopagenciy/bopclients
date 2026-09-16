"""Comprehensive test suite for Phase P24: Secure Team Invitations & Membership Onboarding."""

import pytest
import uuid
import hashlib
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus
from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.container import RuntimeContainer, build_runtime_container
from bopclients.api.app import create_bopclients_api_app
from bopclients.domain.organization import Organization, OrganizationMember
from bopclients.domain.user import User
from bopclients.domain.enums import MemberRole, InvitationStatus
from bopclients.domain.invitation import OrganizationInvitation


@pytest.fixture
def memory_db():
    """In-memory database instance migrated to schema 20260902_010."""
    db = create_database_connection(":memory:")
    DatabaseMigrator.migrate(db)
    return db


@pytest.fixture
def test_container(memory_db):
    """Wired RuntimeContainer on in-memory database."""
    settings = RuntimeSettings(
        database_url="sqlite:///:memory:",
        auth_signing_key="p24-test-signing-key-minimum-32-chars-long!",
        auth_token_expire_seconds=3600,
    )
    container = build_runtime_container(settings=settings, db=memory_db)
    return container


@pytest.fixture
def client_and_context(test_container):
    """FastAPI TestClient with pre-configured seed organization and users."""
    app = create_bopclients_api_app(container=test_container, settings=test_container.settings)
    client = TestClient(app)

    # Seed Org A
    org_a = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name="Acme Corp",
        slug="acme-corp",
    )
    test_container.org_repo.save(org_a)

    # Seed Org B (for cross-tenant tests)
    org_b = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name="Beta LLC",
        slug="beta-llc",
    )
    test_container.org_repo.save(org_b)

    # Seed Owner of Org A
    owner_user = test_container.auth_service.register_user(
        email="owner@acme.com",
        name="Alice Owner",
        password="Password123!",
    )
    test_container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=owner_user.id,
            role=MemberRole.OWNER,
        )
    )

    # Seed Admin of Org A
    admin_user = test_container.auth_service.register_user(
        email="admin@acme.com",
        name="Bob Admin",
        password="Password123!",
    )
    test_container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=admin_user.id,
            role=MemberRole.ADMIN,
        )
    )

    # Seed Regular Member of Org A
    member_user = test_container.auth_service.register_user(
        email="member@acme.com",
        name="Charlie Member",
        password="Password123!",
    )
    test_container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=member_user.id,
            role=MemberRole.MEMBER,
        )
    )

    # Tokens
    owner_tokens, _ = test_container.auth_service.authenticate("owner@acme.com", "Password123!")
    admin_tokens, _ = test_container.auth_service.authenticate("admin@acme.com", "Password123!")
    member_tokens, _ = test_container.auth_service.authenticate("member@acme.com", "Password123!")

    return {
        "client": client,
        "container": test_container,
        "org_a": org_a,
        "org_b": org_b,
        "owner_user": owner_user,
        "admin_user": admin_user,
        "member_user": member_user,
        "owner_token": owner_tokens.access_token,
        "admin_token": admin_tokens.access_token,
        "member_token": member_tokens.access_token,
    }


# =========================================================================
# 1. MIGRATION & READINESS CONTRACT
# =========================================================================

def test_migration_version_and_readiness(memory_db, test_container):
    """Verify migration 20260902_010 is applied and readiness check passes."""
    ver = DatabaseMigrator.get_current_version(memory_db)
    assert ver == "20260902_010"
    assert DatabaseMigrator.EXPECTED_VERSION == "20260902_010"

    readiness = RuntimeReadinessCheck.check(test_container.settings, db=memory_db)
    assert readiness.status == ReadinessStatus.READY
    assert readiness.schema_version == "20260902_010"
    assert readiness.tables_present is True


# =========================================================================
# 2. RBAC & TOKEN CREATION SECURITY
# =========================================================================

def test_owner_can_create_invitations(client_and_context):
    """Owner can invite Admin, Member, and Viewer; production excludes raw token and reports delivery_status."""
    ctx = client_and_context
    client = ctx["client"]
    headers = {
        "Authorization": f"Bearer {ctx['owner_token']}",
        "X-Bop-Organization-Id": ctx["org_a"].bop_organization_id,
    }

    # Invite an Admin (Production default: dev exposure is False)
    res_admin = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "newadmin@example.com", "role": "admin"},
        headers=headers,
    )
    assert res_admin.status_code == 201
    data_admin = res_admin.json()
    assert data_admin["role"] == "admin"
    assert data_admin["status"] == "pending"
    # Production response MUST NOT expose raw token or invite URL
    assert data_admin["raw_token"] is None
    assert data_admin["invite_url"] is None
    assert "token_hash" not in data_admin
    # Delivery status must be truthful (not claiming email was sent)
    assert data_admin["delivery_status"] == "not_configured"

    # Invite a Member
    res_member = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "newmember@example.com", "role": "member"},
        headers=headers,
    )
    assert res_member.status_code == 201
    assert res_member.json()["role"] == "member"
    assert res_member.json()["raw_token"] is None
    assert res_member.json()["delivery_status"] == "not_configured"

    # Invite a Viewer
    res_viewer = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "newviewer@example.com", "role": "viewer"},
        headers=headers,
    )
    assert res_viewer.status_code == 201
    assert res_viewer.json()["role"] == "viewer"
    assert res_viewer.json()["raw_token"] is None
    assert res_viewer.json()["delivery_status"] == "not_configured"


def test_development_token_exposure_mechanism(client_and_context):
    """When BOP_INVITATION_DEV_TOKEN_EXPOSURE is enabled, create response exposes raw_token for dev/test."""
    ctx = client_and_context
    client = ctx["client"]
    container = ctx["container"]
    headers = {
        "Authorization": f"Bearer {ctx['owner_token']}",
        "X-Bop-Organization-Id": ctx["org_a"].bop_organization_id,
    }

    # Enable dev token exposure explicitly
    container.settings.invitation_dev_token_exposure = True
    try:
        res = client.post(
            "/api/v1/organizations/current/invitations",
            json={"email": "devtest@example.com", "role": "viewer"},
            headers=headers,
        )
        assert res.status_code == 201
        data = res.json()
        assert data["raw_token"] is not None
        assert len(data["raw_token"]) > 20
        assert data["invite_url"] == f"/invite/{data['raw_token']}"
        assert data["delivery_status"] == "not_configured"
    finally:
        container.settings.invitation_dev_token_exposure = False


def test_cannot_invite_owner(client_and_context):
    """Nobody can invite an OWNER role."""
    ctx = client_and_context
    client = ctx["client"]
    headers = {
        "Authorization": f"Bearer {ctx['owner_token']}",
        "X-Bop-Organization-Id": ctx["org_a"].bop_organization_id,
    }
    res = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "attempt_owner@example.com", "role": "owner"},
        headers=headers,
    )
    assert res.status_code in (400, 422)


def test_admin_rbac_limits(client_and_context):
    """Admin can invite Member/Viewer, but CANNOT invite Admin or Owner."""
    ctx = client_and_context
    client = ctx["client"]
    headers = {
        "Authorization": f"Bearer {ctx['admin_token']}",
        "X-Bop-Organization-Id": ctx["org_a"].bop_organization_id,
    }

    # Admin inviting member -> Success
    res = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "from_admin@example.com", "role": "member"},
        headers=headers,
    )
    assert res.status_code == 201

    # Admin inviting admin -> Forbidden (403)
    res_admin = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "another_admin@example.com", "role": "admin"},
        headers=headers,
    )
    assert res_admin.status_code == 403


def test_member_cannot_invite(client_and_context):
    """Regular member cannot create invitations."""
    ctx = client_and_context
    client = ctx["client"]
    headers = {
        "Authorization": f"Bearer {ctx['member_token']}",
        "X-Bop-Organization-Id": ctx["org_a"].bop_organization_id,
    }
    res = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "forbidden@example.com", "role": "member"},
        headers=headers,
    )
    assert res.status_code == 403


def test_token_hash_stored_in_db_raw_not_stored(client_and_context):
    """Verify raw token is NOT in database, only SHA-256 token_hash."""
    ctx = client_and_context
    invitation, raw_token, *_ = ctx["container"].invitation_service.create_invitation(
        inviter_user_id=ctx["owner_user"].id,
        org_id=ctx["org_a"].id,
        email="hashcheck@example.com",
        role="member",
    )
    inv_id = invitation.id

    # Query DB directly
    db = ctx["container"].db
    rows = db.fetch_dicts("SELECT * FROM organization_invitations WHERE id = ?", (inv_id,))
    assert len(rows) == 1
    row = rows[0]
    expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    assert row["token_hash"] == expected_hash
    # Confirm raw_token is NOT anywhere in DB columns
    for col, val in row.items():
        assert val != raw_token


def test_list_invitations_omits_raw_token_and_hash(client_and_context):
    """Listing invitations must NEVER expose raw_token or token_hash."""
    ctx = client_and_context
    client = ctx["client"]
    headers = {
        "Authorization": f"Bearer {ctx['owner_token']}",
        "X-Bop-Organization-Id": ctx["org_a"].bop_organization_id,
    }

    client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "listcheck@example.com", "role": "member"},
        headers=headers,
    )

    res = client.get("/api/v1/organizations/current/invitations", headers=headers)
    assert res.status_code == 200
    invitations = res.json()
    assert len(invitations) >= 1
    for inv in invitations:
        assert inv["raw_token"] is None
        assert "token_hash" not in inv
        assert inv["invite_url"] is None
        assert inv["delivery_status"] == "not_configured"


# =========================================================================
# 3. DUPLICATE & CONFLICT PREVENTION
# =========================================================================

def test_duplicate_pending_invitation_rejected(client_and_context):
    """Creating a second pending invitation for same email in same org fails with 409."""
    ctx = client_and_context
    client = ctx["client"]
    headers = {
        "Authorization": f"Bearer {ctx['owner_token']}",
        "X-Bop-Organization-Id": ctx["org_a"].bop_organization_id,
    }

    res1 = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "duplicate@example.com", "role": "member"},
        headers=headers,
    )
    assert res1.status_code == 201

    res2 = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "duplicate@example.com", "role": "member"},
        headers=headers,
    )
    assert res2.status_code == 409
    assert res2.json()["error"]["code"] == "DUPLICATE_INVITATION"


def test_inviting_existing_member_rejected(client_and_context):
    """Inviting someone who is already a member fails with 409 ALREADY_ORGANIZATION_MEMBER."""
    ctx = client_and_context
    client = ctx["client"]
    headers = {
        "Authorization": f"Bearer {ctx['owner_token']}",
        "X-Bop-Organization-Id": ctx["org_a"].bop_organization_id,
    }

    # admin@acme.com is already in org_a
    res = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "admin@acme.com", "role": "member"},
        headers=headers,
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "ALREADY_ORGANIZATION_MEMBER"


# =========================================================================
# 4. REVOCATION LIFECYCLE
# =========================================================================

def test_revocation_by_owner_and_rejection_of_revoked(client_and_context):
    """Owner can revoke invitation, and revoked invitation cannot be accepted."""
    ctx = client_and_context
    client = ctx["client"]
    headers = {
        "Authorization": f"Bearer {ctx['owner_token']}",
        "X-Bop-Organization-Id": ctx["org_a"].bop_organization_id,
    }

    # Create invitation via service safely
    invitation, raw_token, *_ = ctx["container"].invitation_service.create_invitation(
        inviter_user_id=ctx["owner_user"].id,
        org_id=ctx["org_a"].id,
        email="revokeme@example.com",
        role="member",
    )
    inv_id = invitation.id

    # Revoke it
    del_res = client.delete(f"/api/v1/organizations/current/invitations/{inv_id}", headers=headers)
    assert del_res.status_code == 204

    # Public inspect reports revoked
    pub_res = client.get(f"/api/v1/invitations/{raw_token}")
    assert pub_res.status_code == 410
    assert pub_res.json()["error"]["code"] == "INVITATION_REVOKED"


# =========================================================================
# 5. ATOMIC ACCEPTANCE & REPLAY PROTECTION
# =========================================================================

def test_atomic_acceptance_for_existing_authenticated_user(client_and_context):
    """Logged in user with matching email accepts invitation atomically."""
    ctx = client_and_context
    client = ctx["client"]
    container = ctx["container"]

    # Register user Dave (exists in system, but not in Org A)
    dave = container.auth_service.register_user(
        email="dave@example.com",
        name="Dave User",
        password="Password123!",
    )
    dave_tokens, _ = container.auth_service.authenticate("dave@example.com", "Password123!")

    # Owner invites Dave via service safely
    invitation, raw_token, *_ = container.invitation_service.create_invitation(
        inviter_user_id=ctx["owner_user"].id,
        org_id=ctx["org_a"].id,
        email="dave@example.com",
        role="member",
    )

    # Dave inspects invitation
    inspect_res = client.get(f"/api/v1/invitations/{raw_token}")
    assert inspect_res.status_code == 200
    assert inspect_res.json()["organization_name"] == "Acme Corp"
    assert inspect_res.json()["role"] == "member"

    # Dave accepts invitation
    headers_dave = {"Authorization": f"Bearer {dave_tokens.access_token}"}
    accept_res = client.post(
        "/api/v1/invitations/accept",
        json={"token": raw_token},
        headers=headers_dave,
    )
    assert accept_res.status_code == 200
    acc_data = accept_res.json()
    assert acc_data["organization_id"] == ctx["org_a"].id
    assert acc_data["role"] == "member"

    # Verify membership in DB
    member = container.org_repo.get_member(ctx["org_a"].id, dave.id)
    assert member is not None
    assert member.role == MemberRole.MEMBER

    # Replay protection: accepting again fails with 409
    replay_res = client.post(
        "/api/v1/invitations/accept",
        json={"token": raw_token},
        headers=headers_dave,
    )
    assert replay_res.status_code == 409
    assert replay_res.json()["error"]["code"] == "INVITATION_ALREADY_ACCEPTED"


def test_acceptance_email_mismatch_rejected(client_and_context):
    """User logged in with different email cannot accept someone else's invitation."""
    ctx = client_and_context
    client = ctx["client"]

    # Invite target@example.com via service safely
    invitation, raw_token, *_ = ctx["container"].invitation_service.create_invitation(
        inviter_user_id=ctx["owner_user"].id,
        org_id=ctx["org_a"].id,
        email="target@example.com",
        role="member",
    )

    # Member user (member@acme.com) tries to accept it
    headers_member = {"Authorization": f"Bearer {ctx['member_token']}"}
    accept_res = client.post(
        "/api/v1/invitations/accept",
        json={"token": raw_token},
        headers=headers_member,
    )
    assert accept_res.status_code == 403
    assert accept_res.json()["error"]["code"] == "INVITATION_EMAIL_MISMATCH"


# =========================================================================
# 6. REGISTER AND ACCEPT (NEW USER ONBOARDING)
# =========================================================================

def test_register_and_accept_new_user(client_and_context):
    """New invited user registers account and accepts invitation in one request."""
    ctx = client_and_context
    client = ctx["client"]

    # Owner invites new person safely via service
    invitation, raw_token, *_ = ctx["container"].invitation_service.create_invitation(
        inviter_user_id=ctx["owner_user"].id,
        org_id=ctx["org_a"].id,
        email="newuser@example.com",
        role="admin",
    )

    # New user registers & accepts
    reg_res = client.post(
        "/api/v1/invitations/register-and-accept",
        json={
            "token": raw_token,
            "name": "New User",
            "password": "SecurePassword123!",
            "locale": "es",
        },
    )
    assert reg_res.status_code == 201
    data = reg_res.json()
    assert data["role"] == "admin"
    assert data["access_token"] is not None
    assert data["refresh_token"] is not None
    # Confirm password and password_hash are NEVER returned in response
    assert "password" not in data
    assert "password_hash" not in data

    # Check that user exists and is member of Org A with ADMIN role
    user = ctx["container"].user_repo.get_by_email("newuser@example.com")
    assert user is not None
    assert user.locale == "es"
    # Confirm Argon2id hashing used, plaintext password NEVER stored
    assert user.password_hash.startswith("$argon2id$")
    assert "SecurePassword123!" not in user.password_hash
    member = ctx["container"].org_repo.get_member(ctx["org_a"].id, user.id)
    assert member is not None
    assert member.role == MemberRole.ADMIN

    # Re-registration / duplicate user prevention
    dup_res = client.post(
        "/api/v1/invitations/register-and-accept",
        json={
            "token": raw_token,
            "name": "Duplicate Attempt",
            "password": "SecurePassword123!",
            "locale": "es",
        },
    )
    # Replay on already-accepted invitation fails
    assert dup_res.status_code in (400, 409)


# =========================================================================
# 7. CROSS-TENANT ISOLATION
# =========================================================================

def test_cross_tenant_invitation_isolation(client_and_context):
    """Invitations in Org A cannot be viewed or revoked by Org B."""
    ctx = client_and_context
    client = ctx["client"]
    container = ctx["container"]

    # Owner of Org B
    owner_b = container.auth_service.register_user(
        email="owner_b@beta.com",
        name="Beta Owner",
        password="Password123!",
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=ctx["org_b"].id,
            user_id=owner_b.id,
            role=MemberRole.OWNER,
        )
    )
    tokens_b, _ = container.auth_service.authenticate("owner_b@beta.com", "Password123!")

    # Owner of Org A creates invitation in Org A
    headers_a = {
        "Authorization": f"Bearer {ctx['owner_token']}",
        "X-Bop-Organization-Id": ctx["org_a"].bop_organization_id,
    }
    create_res = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "tenant_test@example.com", "role": "member"},
        headers=headers_a,
    )
    inv_id = create_res.json()["id"]

    # Org B lists invitations -> must NOT include invitation from Org A
    headers_b = {
        "Authorization": f"Bearer {tokens_b.access_token}",
        "X-Bop-Organization-Id": ctx["org_b"].bop_organization_id,
    }
    list_b = client.get("/api/v1/organizations/current/invitations", headers=headers_b)
    assert list_b.status_code == 200
    ids = [i["id"] for i in list_b.json()]
    assert inv_id not in ids

    # Org B tries to delete invitation from Org A -> 404
    del_b = client.delete(f"/api/v1/organizations/current/invitations/{inv_id}", headers=headers_b)
    assert del_b.status_code == 404
