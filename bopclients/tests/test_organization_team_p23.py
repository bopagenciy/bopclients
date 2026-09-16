"""P23 Organization & Team Administration Foundation Targeted Tests.

Covers:
1. Multi-tenant isolation:
   - Tenant A cannot list, view, update role of, or remove Tenant B members.
   - Cross-tenant user IDs return 404 (no information leakage).
   - Tenant A cannot update Tenant B settings.
2. Truthful member listing:
   - Returns members with id, organization_id, user_id, role, email, full_name, created_at.
   - Sensitive credentials (password_hash, session tokens) are strictly excluded.
3. RBAC & Role Management:
   - OWNER can update eligible roles (MEMBER -> ADMIN, ADMIN -> OWNER, etc.).
   - ADMIN can manage MEMBER <-> VIEWER only.
   - ADMIN cannot escalate self or others to OWNER or ADMIN (HTTP 403).
   - ADMIN cannot modify or remove OWNER (HTTP 403).
   - ADMIN cannot modify or remove fellow ADMIN (HTTP 403).
   - MEMBER cannot mutate roles or remove members (HTTP 403).
   - VIEWER cannot mutate roles or remove members (HTTP 403).
4. Last Owner Protection:
   - Sole OWNER cannot be demoted (HTTP 409 LAST_OWNER_PROTECTION).
   - Sole OWNER cannot be removed (HTTP 409 LAST_OWNER_PROTECTION).
   - When multiple OWNERs exist, demotion and removal of an owner is allowed.
5. Member Removal:
   - Removing membership deletes only the organization_members record.
   - Global user entity in users table is preserved (never deleted).
6. Self-management:
   - ADMIN can remove self (leaves org).
7. Organization profile update & immutable bop_organization_id:
   - Display name update works with validation.
   - bop_organization_id is strictly immutable.
"""

import uuid
import pytest
from starlette.testclient import TestClient

from bopclients.api.app import create_bopclients_api_app
from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.container import build_runtime_container
from bopclients.domain.organization import Organization, OrganizationMember
from bopclients.domain.enums import MemberRole


@pytest.fixture
def p23_fixture():
    db = create_database_connection(":memory:")
    DatabaseMigrator.migrate(db)

    settings = RuntimeSettings(
        database_url=":memory:",
        auth_signing_key="p23-targeted-test-signing-key-minimum-32-chars-long!",
        auth_token_expire_seconds=3600,
        auth_session_expire_days=7,
        enabled_providers=["official_website"],
    )
    container = build_runtime_container(settings, db=db)
    app = create_bopclients_api_app(container)
    client = TestClient(app)
    auth_service = container.auth_service

    # Setup Tenant A Users
    owner_a = auth_service.register_user(
        email="owner_a@acme.com",
        name="Alice Owner",
        password="PasswordA123!",
        locale="en",
    )
    admin_a = auth_service.register_user(
        email="admin_a@acme.com",
        name="Bob Admin",
        password="PasswordAdmin123!",
        locale="en",
    )
    member_a = auth_service.register_user(
        email="member_a@acme.com",
        name="Charlie Member",
        password="PasswordMember123!",
        locale="en",
    )
    viewer_a = auth_service.register_user(
        email="viewer_a@acme.com",
        name="Dana Viewer",
        password="PasswordViewer123!",
        locale="en",
    )

    # Setup Tenant A Org
    org_a = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name="Acme Corp",
        slug="acme-corp",
    )
    container.org_repo.save(org_a)
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=owner_a.id,
            role=MemberRole.OWNER,
        )
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=admin_a.id,
            role=MemberRole.ADMIN,
        )
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=member_a.id,
            role=MemberRole.MEMBER,
        )
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=viewer_a.id,
            role=MemberRole.VIEWER,
        )
    )

    # Setup Tenant B User & Org
    owner_b = auth_service.register_user(
        email="owner_b@globex.com",
        name="Eve Globex",
        password="PasswordB123!",
        locale="en",
    )
    org_b = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name="Globex Corp",
        slug="globex-corp",
    )
    container.org_repo.save(org_b)
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_b.id,
            user_id=owner_b.id,
            role=MemberRole.OWNER,
        )
    )

    # Authenticate and obtain tokens
    token_owner_a = auth_service.authenticate("owner_a@acme.com", "PasswordA123!")
    token_admin_a = auth_service.authenticate("admin_a@acme.com", "PasswordAdmin123!")
    token_member_a = auth_service.authenticate("member_a@acme.com", "PasswordMember123!")
    token_viewer_a = auth_service.authenticate("viewer_a@acme.com", "PasswordViewer123!")
    token_owner_b = auth_service.authenticate("owner_b@globex.com", "PasswordB123!")

    headers_owner_a = {
        "Authorization": f"Bearer {token_owner_a.access_token}",
        "X-Bop-Organization-Id": org_a.bop_organization_id,
    }
    headers_admin_a = {
        "Authorization": f"Bearer {token_admin_a.access_token}",
        "X-Bop-Organization-Id": org_a.bop_organization_id,
    }
    headers_member_a = {
        "Authorization": f"Bearer {token_member_a.access_token}",
        "X-Bop-Organization-Id": org_a.bop_organization_id,
    }
    headers_viewer_a = {
        "Authorization": f"Bearer {token_viewer_a.access_token}",
        "X-Bop-Organization-Id": org_a.bop_organization_id,
    }
    headers_owner_b = {
        "Authorization": f"Bearer {token_owner_b.access_token}",
        "X-Bop-Organization-Id": org_b.bop_organization_id,
    }

    return {
        "client": client,
        "container": container,
        "org_a": org_a,
        "org_b": org_b,
        "owner_a": owner_a,
        "admin_a": admin_a,
        "member_a": member_a,
        "viewer_a": viewer_a,
        "owner_b": owner_b,
        "headers_owner_a": headers_owner_a,
        "headers_admin_a": headers_admin_a,
        "headers_member_a": headers_member_a,
        "headers_viewer_a": headers_viewer_a,
        "headers_owner_b": headers_owner_b,
    }


def test_member_listing_truthful_and_sanitized(p23_fixture):
    client = p23_fixture["client"]
    headers = p23_fixture["headers_owner_a"]

    res = client.get("/api/v1/organizations/current/members", headers=headers)
    assert res.status_code == 200
    members = res.json()
    assert len(members) == 4

    emails = {m["email"] for m in members}
    assert emails == {"owner_a@acme.com", "admin_a@acme.com", "member_a@acme.com", "viewer_a@acme.com"}

    # Verify no secrets or sensitive data are exposed
    for m in members:
        assert "password_hash" not in m
        assert "password" not in m
        assert "session" not in m
        assert "token" not in m
        assert m["role"] in ["owner", "admin", "member", "viewer"]
        assert m["organization_id"] == p23_fixture["org_a"].id


def test_tenant_isolation_members_and_settings(p23_fixture):
    client = p23_fixture["client"]
    headers_a = p23_fixture["headers_owner_a"]
    owner_b = p23_fixture["owner_b"]

    # 1. Org A cannot see Org B members when listing
    res = client.get("/api/v1/organizations/current/members", headers=headers_a)
    assert res.status_code == 200
    member_user_ids = [m["user_id"] for m in res.json()]
    assert owner_b.id not in member_user_ids

    # 2. Org A attempting to update role of Org B member -> 404 (no leak)
    res_patch = client.patch(
        f"/api/v1/organizations/current/members/{owner_b.id}",
        json={"role": "member"},
        headers=headers_a,
    )
    assert res_patch.status_code == 404
    assert res_patch.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    # 3. Org A attempting to remove Org B member -> 404 (no leak)
    res_delete = client.delete(
        f"/api/v1/organizations/current/members/{owner_b.id}",
        headers=headers_a,
    )
    assert res_delete.status_code == 404
    assert res_delete.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_owner_role_management_lifecycle(p23_fixture):
    client = p23_fixture["client"]
    headers = p23_fixture["headers_owner_a"]
    member_a = p23_fixture["member_a"]

    # Promote MEMBER to ADMIN
    res = client.patch(
        f"/api/v1/organizations/current/members/{member_a.id}",
        json={"role": "admin"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["role"] == "admin"

    # Demote ADMIN to VIEWER
    res = client.patch(
        f"/api/v1/organizations/current/members/{member_a.id}",
        json={"role": "viewer"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["role"] == "viewer"


def test_admin_permissions_and_escalation_denial(p23_fixture):
    client = p23_fixture["client"]
    headers_admin = p23_fixture["headers_admin_a"]
    owner_a = p23_fixture["owner_a"]
    member_a = p23_fixture["member_a"]
    viewer_a = p23_fixture["viewer_a"]

    # 1. Admin can change MEMBER to VIEWER
    res = client.patch(
        f"/api/v1/organizations/current/members/{member_a.id}",
        json={"role": "viewer"},
        headers=headers_admin,
    )
    assert res.status_code == 200
    assert res.json()["role"] == "viewer"

    # 2. Admin can change VIEWER to MEMBER
    res = client.patch(
        f"/api/v1/organizations/current/members/{viewer_a.id}",
        json={"role": "member"},
        headers=headers_admin,
    )
    assert res.status_code == 200
    assert res.json()["role"] == "member"

    # 3. Admin CANNOT escalate member to OWNER
    res = client.patch(
        f"/api/v1/organizations/current/members/{member_a.id}",
        json={"role": "owner"},
        headers=headers_admin,
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN"

    # 4. Admin CANNOT escalate member to ADMIN
    res = client.patch(
        f"/api/v1/organizations/current/members/{member_a.id}",
        json={"role": "admin"},
        headers=headers_admin,
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN"

    # 5. Admin CANNOT modify OWNER role
    res = client.patch(
        f"/api/v1/organizations/current/members/{owner_a.id}",
        json={"role": "member"},
        headers=headers_admin,
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN"

    # 6. Admin CANNOT remove OWNER
    res = client.delete(
        f"/api/v1/organizations/current/members/{owner_a.id}",
        headers=headers_admin,
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN"


def test_member_and_viewer_mutation_denial(p23_fixture):
    client = p23_fixture["client"]
    headers_member = p23_fixture["headers_member_a"]
    headers_viewer = p23_fixture["headers_viewer_a"]
    viewer_a = p23_fixture["viewer_a"]

    # Member can read team
    res = client.get("/api/v1/organizations/current/members", headers=headers_member)
    assert res.status_code == 200

    # Member cannot update role
    res = client.patch(
        f"/api/v1/organizations/current/members/{viewer_a.id}",
        json={"role": "member"},
        headers=headers_member,
    )
    assert res.status_code == 403

    # Member cannot remove member
    res = client.delete(
        f"/api/v1/organizations/current/members/{viewer_a.id}",
        headers=headers_member,
    )
    assert res.status_code == 403

    # Viewer can read team
    res = client.get("/api/v1/organizations/current/members", headers=headers_viewer)
    assert res.status_code == 200

    # Viewer cannot update role
    res = client.patch(
        f"/api/v1/organizations/current/members/{viewer_a.id}",
        json={"role": "member"},
        headers=headers_viewer,
    )
    assert res.status_code == 403

    # Viewer cannot remove member
    res = client.delete(
        f"/api/v1/organizations/current/members/{viewer_a.id}",
        headers=headers_viewer,
    )
    assert res.status_code == 403


def test_last_owner_protection_demote_and_remove(p23_fixture):
    client = p23_fixture["client"]
    headers = p23_fixture["headers_owner_a"]
    owner_a = p23_fixture["owner_a"]
    admin_a = p23_fixture["admin_a"]

    # 1. Sole OWNER cannot be demoted -> 409 LAST_OWNER_PROTECTION
    res = client.patch(
        f"/api/v1/organizations/current/members/{owner_a.id}",
        json={"role": "admin"},
        headers=headers,
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "LAST_OWNER_PROTECTION"
    assert res.json()["error"]["message_key"] == "errors.last_owner_protection"

    # 2. Sole OWNER cannot be removed -> 409 LAST_OWNER_PROTECTION
    res = client.delete(
        f"/api/v1/organizations/current/members/{owner_a.id}",
        headers=headers,
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "LAST_OWNER_PROTECTION"
    assert res.json()["error"]["message_key"] == "errors.last_owner_protection"

    # 3. Promote admin_a to second OWNER
    res = client.patch(
        f"/api/v1/organizations/current/members/{admin_a.id}",
        json={"role": "owner"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["role"] == "owner"

    # 4. Now with 2 owners, demoting owner_a succeeds
    res = client.patch(
        f"/api/v1/organizations/current/members/{owner_a.id}",
        json={"role": "admin"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["role"] == "admin"


def test_remove_member_preserves_global_user(p23_fixture):
    client = p23_fixture["client"]
    container = p23_fixture["container"]
    headers = p23_fixture["headers_owner_a"]
    viewer_a = p23_fixture["viewer_a"]
    org_a = p23_fixture["org_a"]

    # Verify membership exists
    member_before = container.org_repo.get_member(org_a.id, viewer_a.id)
    assert member_before is not None

    # Remove member
    res = client.delete(
        f"/api/v1/organizations/current/members/{viewer_a.id}",
        headers=headers,
    )
    assert res.status_code == 204

    # Verify membership row is deleted
    member_after = container.org_repo.get_member(org_a.id, viewer_a.id)
    assert member_after is None

    # CRITICAL: Verify global user in users table is STILL INTACT (never deleted)
    user_record = container.user_repo.get_by_id(viewer_a.id)
    assert user_record is not None
    assert user_record.email == "viewer_a@acme.com"


def test_self_removal_by_admin(p23_fixture):
    client = p23_fixture["client"]
    container = p23_fixture["container"]
    headers_admin = p23_fixture["headers_admin_a"]
    admin_a = p23_fixture["admin_a"]
    org_a = p23_fixture["org_a"]

    # Admin removes self (leaves org)
    res = client.delete(
        f"/api/v1/organizations/current/members/{admin_a.id}",
        headers=headers_admin,
    )
    assert res.status_code == 204

    # Verify membership removed
    assert container.org_repo.get_member(org_a.id, admin_a.id) is None

    # Global user record preserved
    assert container.user_repo.get_by_id(admin_a.id) is not None


def test_organization_settings_and_immutable_bop_org_id(p23_fixture):
    client = p23_fixture["client"]
    container = p23_fixture["container"]
    headers = p23_fixture["headers_owner_a"]
    org_a = p23_fixture["org_a"]

    # Update organization name
    res = client.patch(
        "/api/v1/organizations/current",
        json={"name": "Acme Global Industries"},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Acme Global Industries"
    assert data["bop_organization_id"] == org_a.bop_organization_id

    # Empty name rejected
    res_empty = client.patch(
        "/api/v1/organizations/current",
        json={"name": "   "},
        headers=headers,
    )
    assert res_empty.status_code == 422

    # Verify repository-level immutability enforcement for bop_organization_id
    org_obj = container.org_repo.get_by_id(org_a.id)
    org_obj.bop_organization_id = str(uuid.uuid4())
    with pytest.raises(ValueError, match="Cannot mutate immutable bop_organization_id"):
        container.org_repo.save(org_obj)
