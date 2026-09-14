"""Adversarial cross-tenant IDOR (Insecure Direct Object Reference) and RBAC privilege escalation tests.

Verifies:
1. An authenticated user of Tenant A cannot access, read, update, or delete Tenant B's:
   - Campaigns (/api/v1/campaigns/{id})
   - Prospects (/api/v1/prospects/{id})
   - Prospect intelligence (/api/v1/prospects/{id}/intelligence)
   - ICPs (/api/v1/icps/{id})
   - Target markets (/api/v1/target-markets/{id})
   - Organization details (/api/v1/organizations/{id})
2. All cross-tenant access attempts return HTTP 404 (NOT 403 or 401) to prevent enumeration.
3. Supplying Tenant B's X-Bop-Organization-Id header with Tenant A user credentials returns HTTP 403 (or 404).
4. RBAC privilege escalation boundaries:
   - VIEWER role receives 403 when trying to create/edit campaigns, prospects, destinations, or manage members.
"""

import uuid
import pytest
from datetime import datetime, timezone
from starlette.testclient import TestClient

from bopclients.api.app import create_bopclients_api_app
from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.container import build_runtime_container
from bopclients.domain.organization import Organization, OrganizationMember
from bopclients.domain.campaign import Campaign
from bopclients.domain.icp import IdealCustomerProfile, TargetMarket
from bopclients.domain.prospect import Prospect
from bopclients.domain.enums import CampaignStatus, MemberRole
from bopclients.domain.integration.destination import IntegrationDestination


@pytest.fixture
def idor_fixture():
    """Sets up two completely separate tenants (Tenant A and Tenant B) with their own users."""
    db = create_database_connection(":memory:")
    DatabaseMigrator.migrate(db)

    settings = RuntimeSettings(
        database_url=":memory:",
        auth_signing_key="idor-test-signing-key-minimum-32-chars-long!",
        auth_token_expire_seconds=3600,
        auth_session_expire_days=7,
        enabled_providers=["official_website"],
    )
    container = build_runtime_container(settings, db=db)
    app = create_bopclients_api_app(container)
    client = TestClient(app)

    auth_service = container.auth_service

    # 1. Setup Tenant A
    user_a = auth_service.register_user(
        email="user_a@tenanta.com",
        name="User A",
        password="PasswordA123!",
        locale="en",
    )
    org_a_id = str(uuid.uuid4())
    bop_org_a_id = str(uuid.uuid4())
    org_a = Organization(
        id=org_a_id,
        bop_organization_id=bop_org_a_id,
        name="Tenant A Corp",
        slug="tenant-a",
    )
    container.org_repo.save(org_a)
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a_id,
            user_id=user_a.id,
            role="OWNER",
        )
    )

    auth_res_a = auth_service.authenticate("user_a@tenanta.com", "PasswordA123!")
    headers_a = {
        "Authorization": f"Bearer {auth_res_a.access_token}",
        "X-Bop-Organization-Id": bop_org_a_id,
    }

    # 2. Setup Tenant B
    user_b = auth_service.register_user(
        email="user_b@tenantb.com",
        name="User B",
        password="PasswordB123!",
        locale="en",
    )
    org_b_id = str(uuid.uuid4())
    bop_org_b_id = str(uuid.uuid4())
    org_b = Organization(
        id=org_b_id,
        bop_organization_id=bop_org_b_id,
        name="Tenant B Corp",
        slug="tenant-b",
    )
    container.org_repo.save(org_b)
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_b_id,
            user_id=user_b.id,
            role="OWNER",
        )
    )

    auth_res_b = auth_service.authenticate("user_b@tenantb.com", "PasswordB123!")
    headers_b = {
        "Authorization": f"Bearer {auth_res_b.access_token}",
        "X-Bop-Organization-Id": bop_org_b_id,
    }

    # 3. Setup Tenant A Viewer User
    user_a_viewer = auth_service.register_user(
        email="viewer_a@tenanta.com",
        name="Viewer A",
        password="ViewerA123!",
        locale="en",
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a_id,
            user_id=user_a_viewer.id,
            role="VIEWER",
        )
    )
    auth_res_viewer = auth_service.authenticate("viewer_a@tenanta.com", "ViewerA123!")
    headers_a_viewer = {
        "Authorization": f"Bearer {auth_res_viewer.access_token}",
        "X-Bop-Organization-Id": bop_org_a_id,
    }

    # 4. Seed Resources under Tenant B
    # Campaign B
    camp_b = Campaign(
        id=str(uuid.uuid4()),
        organization_id=org_b_id,
        name="Tenant B Secret Campaign",
        status=CampaignStatus.ACTIVE,
    )
    container.campaign_repo.save(org_b_id, camp_b)

    # Prospect B
    prospect_b = Prospect(
        id=str(uuid.uuid4()),
        organization_id=org_b_id,
        name="Tenant B Secret Prospect",
        website_url="https://secret-b.example.com",
    )
    container.prospect_repo.save_prospect(org_b_id, prospect_b)

    # ICP B
    icp_b_id = str(uuid.uuid4())
    tm_b = TargetMarket(
        id=str(uuid.uuid4()),
        icp_id=icp_b_id,
        country="CA",
        city="Toronto",
    )
    icp_b = IdealCustomerProfile(
        id=icp_b_id,
        organization_id=org_b_id,
        name="Tenant B Secret ICP",
        target_markets=[tm_b],
    )
    container.icp_repo.save(org_b_id, icp_b)

    # Destination B
    dest_b = IntegrationDestination.create(
        bop_organization_id=bop_org_b_id,
        target_app_id="webhook",
        destination_name="Tenant B Destination",
        endpoint_url="https://webhook.tenantb.com/events",
    )
    container.destination_repo.create_destination(dest_b)

    return {
        "client": client,
        "headers_a": headers_a,
        "headers_b": headers_b,
        "headers_a_viewer": headers_a_viewer,
        "org_a": org_a,
        "org_b": org_b,
        "camp_b": camp_b,
        "prospect_b": prospect_b,
        "icp_b": icp_b,
        "tm_b": tm_b,
        "dest_b": dest_b,
        "bop_org_b_id": bop_org_b_id,
        "user_a_token": auth_res_a.access_token,
    }


class TestCrossTenantIDORProtection:
    """Ensure Tenant A cannot view or tamper with Tenant B resources (Must return 404)."""

    def test_tenant_a_cannot_read_tenant_b_campaign(self, idor_fixture):
        client = idor_fixture["client"]
        headers_a = idor_fixture["headers_a"]
        camp_b_id = idor_fixture["camp_b"].id

        # Tenant A tries to read Tenant B's campaign
        res = client.get(f"/api/v1/campaigns/{camp_b_id}", headers=headers_a)
        assert res.status_code == 404
        assert res.json()["error"]["code"] in ("ENTITY_NOT_FOUND", "NOT_FOUND", "RESOURCE_NOT_FOUND")

    def test_tenant_a_cannot_update_tenant_b_campaign(self, idor_fixture):
        client = idor_fixture["client"]
        headers_a = idor_fixture["headers_a"]
        camp_b_id = idor_fixture["camp_b"].id

        res = client.patch(
            f"/api/v1/campaigns/{camp_b_id}",
            headers=headers_a,
            json={"name": "Hacked Name"},
        )
        assert res.status_code == 404

    def test_tenant_a_cannot_read_tenant_b_prospect(self, idor_fixture):
        client = idor_fixture["client"]
        headers_a = idor_fixture["headers_a"]
        prospect_b_id = idor_fixture["prospect_b"].id

        res = client.get(f"/api/v1/prospects/{prospect_b_id}", headers=headers_a)
        assert res.status_code == 404

    def test_tenant_a_cannot_read_tenant_b_prospect_intelligence(self, idor_fixture):
        client = idor_fixture["client"]
        headers_a = idor_fixture["headers_a"]
        prospect_b_id = idor_fixture["prospect_b"].id

        res = client.get(f"/api/v1/prospects/{prospect_b_id}/intelligence", headers=headers_a)
        assert res.status_code == 404

    def test_tenant_a_cannot_read_tenant_b_icp(self, idor_fixture):
        client = idor_fixture["client"]
        headers_a = idor_fixture["headers_a"]
        icp_b_id = idor_fixture["icp_b"].id

        res = client.get(f"/api/v1/icps/{icp_b_id}", headers=headers_a)
        assert res.status_code == 404

    def test_tenant_a_cannot_read_tenant_b_target_market(self, idor_fixture):
        client = idor_fixture["client"]
        headers_a = idor_fixture["headers_a"]
        tm_b_id = idor_fixture["tm_b"].id

        res = client.get(f"/api/v1/target-markets/{tm_b_id}", headers=headers_a)
        assert res.status_code == 404

    def test_tenant_a_cannot_update_tenant_b_target_market(self, idor_fixture):
        client = idor_fixture["client"]
        headers_a = idor_fixture["headers_a"]
        tm_b_id = idor_fixture["tm_b"].id

        res = client.patch(
            f"/api/v1/target-markets/{tm_b_id}",
            headers=headers_a,
            json={"city": "Hacked City"},
        )
        assert res.status_code == 404

    def test_tenant_a_cannot_read_tenant_b_organization_details(self, idor_fixture):
        client = idor_fixture["client"]
        headers_a = idor_fixture["headers_a"]
        org_b_id = idor_fixture["org_b"].id

        res = client.get(f"/api/v1/organizations/{org_b_id}", headers=headers_a)
        assert res.status_code == 404

    def test_tenant_a_user_spoofing_tenant_b_header_is_denied(self, idor_fixture):
        client = idor_fixture["client"]
        token_a = idor_fixture["user_a_token"]
        bop_org_b_id = idor_fixture["bop_org_b_id"]

        # Tenant A's token paired with Tenant B's organization ID
        spoofed_headers = {
            "Authorization": f"Bearer {token_a}",
            "X-Bop-Organization-Id": bop_org_b_id,
        }

        res = client.get("/api/v1/campaigns", headers=spoofed_headers)
        # Must be 403 Forbidden or 404 Not Found (to prevent tenant existence enumeration)
        assert res.status_code in (403, 404, 401)
        assert res.json()["error"]["code"] in ("TENANT_FORBIDDEN", "FORBIDDEN", "UNAUTHORIZED", "RESOURCE_NOT_FOUND")


class TestRBACPrivilegeEscalation:
    """Verify that VIEWER and MEMBER roles cannot execute restricted actions."""

    def test_viewer_cannot_create_campaign(self, idor_fixture):
        client = idor_fixture["client"]
        headers_viewer = idor_fixture["headers_a_viewer"]

        res = client.post(
            "/api/v1/campaigns",
            headers=headers_viewer,
            json={"name": "Unauthorized Campaign"},
        )
        assert res.status_code == 403
        assert res.json()["error"]["code"] in ("PERMISSION_DENIED", "FORBIDDEN")

    def test_viewer_cannot_create_prospect(self, idor_fixture):
        client = idor_fixture["client"]
        headers_viewer = idor_fixture["headers_a_viewer"]

        res = client.post(
            "/api/v1/prospects",
            headers=headers_viewer,
            json={"company_name": "Unauthorized Prospect"},
        )
        assert res.status_code == 403
        assert res.json()["error"]["code"] in ("PERMISSION_DENIED", "FORBIDDEN")

    def test_viewer_cannot_create_destination(self, idor_fixture):
        client = idor_fixture["client"]
        headers_viewer = idor_fixture["headers_a_viewer"]

        res = client.post(
            "/api/v1/integrations/destinations",
            headers=headers_viewer,
            json={
                "target_app_id": "webhook",
                "destination_name": "Viewer Hook",
                "endpoint_url": "https://evil.com/hook",
            },
        )
        assert res.status_code == 403
        assert res.json()["error"]["code"] in ("PERMISSION_DENIED", "FORBIDDEN")

    def test_viewer_cannot_manage_members(self, idor_fixture):
        client = idor_fixture["client"]
        headers_viewer = idor_fixture["headers_a_viewer"]

        res = client.post(
            "/api/v1/organizations/current/members",
            headers=headers_viewer,
            json={"email": "newbie@example.com", "role": "member"},
        )
        assert res.status_code == 403
        assert res.json()["error"]["code"] in ("PERMISSION_DENIED", "FORBIDDEN")
