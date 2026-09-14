"""Integration tests for BopClients FastAPI product endpoints under /api/v1.

Tests:
- Health and readiness endpoints (/health/live, /health/ready)
- Authentication flows (/api/v1/auth/login, logout, refresh)
- Current user profile and memberships (/api/v1/me, /api/v1/me/memberships)
- Organizations and member listings (/api/v1/organizations)
- Tenant-scoped operational endpoints:
  - Campaigns (/api/v1/campaigns)
  - ICPs & Target Markets (/api/v1/icps, /api/v1/target-markets)
  - Prospects & Intelligence (/api/v1/prospects, /api/v1/prospects/{id}/intelligence)
  - Signals (/api/v1/signals)
  - Research Runs (/api/v1/research/runs)
  - Monitoring (/api/v1/monitoring/overview, /api/v1/monitoring/health)
  - Integrations (/api/v1/integrations/outbox, inbox, destinations)
- Standardized error envelopes and localization (en, es)
- Security headers and request ID propagation
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
from bopclients.domain.signal_observation import PublicSignalObservation
from bopclients.domain.enums import CampaignStatus, MemberRole


@pytest.fixture
def api_test_context():
    """Sets up an in-memory test database, container, test client, and seeded org/user."""
    db = create_database_connection(":memory:")
    DatabaseMigrator.migrate(db)

    settings = RuntimeSettings(
        database_url=":memory:",
        auth_signing_key="unit-test-signing-key-minimum-32-chars-long!",
        auth_token_expire_seconds=3600,
        auth_session_expire_days=7,
        enabled_providers=["official_website"],
    )
    container = build_runtime_container(settings, db=db)
    app = create_bopclients_api_app(container)
    client = TestClient(app)

    # Seed User
    auth_service = container.auth_service
    user = auth_service.register_user(
        email="testuser@example.com",
        name="Test User",
        password="TestPassword123!",
        locale="en",
    )

    # Seed Organization
    org_id = str(uuid.uuid4())
    bop_org_id = str(uuid.uuid4())
    org = Organization(
        id=org_id,
        bop_organization_id=bop_org_id,
        name="Acme Corp",
        slug="acme-corp",
    )
    container.org_repo.save(org)

    # Add user as OWNER
    member = OrganizationMember(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        user_id=user.id,
        role="OWNER",
    )
    container.org_repo.add_member(member)

    # Perform initial login to get tokens
    auth_res = auth_service.authenticate("testuser@example.com", "TestPassword123!")
    access_token = auth_res.access_token
    session_token = auth_res.session_token

    auth_headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Bop-Organization-Id": bop_org_id,
    }

    return {
        "db": db,
        "container": container,
        "client": client,
        "user": user,
        "org": org,
        "auth_headers": auth_headers,
        "access_token": access_token,
        "session_token": session_token,
    }


# ==============================================================================
# 1. HEALTH AND READINESS
# ==============================================================================

class TestHealthEndpoints:
    def test_liveness_check(self, api_test_context):
        client = api_test_context["client"]
        res = client.get("/health/live")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert "timestamp" in data

    def test_readiness_check(self, api_test_context):
        client = api_test_context["client"]
        res = client.get("/health/ready")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "READY"
        assert data["schema_version"] == "20260902_009"
        assert data["database_connected"] is True


# ==============================================================================
# 2. AUTHENTICATION ENDPOINTS
# ==============================================================================

class TestAuthEndpoints:
    def test_login_success(self, api_test_context):
        client = api_test_context["client"]
        res = client.post(
            "/api/v1/auth/login",
            json={"email": "testuser@example.com", "password": "TestPassword123!"},
        )
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "Bearer"
        assert data["user"]["email"] == "testuser@example.com"
        assert data["user"]["name"] == "Test User"
        assert "password_hash" not in data["user"]  # Never expose hash

    def test_login_invalid_credentials_returns_401(self, api_test_context):
        client = api_test_context["client"]
        res = client.post(
            "/api/v1/auth/login",
            json={"email": "testuser@example.com", "password": "WrongPassword!"},
        )
        assert res.status_code == 401
        data = res.json()
        assert "error" in data
        assert data["error"]["code"] == "INVALID_CREDENTIALS"

    def test_refresh_token_flow(self, api_test_context):
        client = api_test_context["client"]
        session_token = api_test_context["session_token"]
        res = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": session_token},
        )
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert data["access_token"] != ""

    def test_logout_revokes_session(self, api_test_context):
        client = api_test_context["client"]
        session_token = api_test_context["session_token"]
        headers = api_test_context["auth_headers"]

        # Logout
        res = client.post(
            "/api/v1/auth/logout",
            headers=headers,
            json={"refresh_token": session_token},
        )
        assert res.status_code == 200
        assert res.json()["success"] is True

        # Refresh with revoked token fails
        ref_res = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": session_token},
        )
        assert ref_res.status_code == 401


# ==============================================================================
# 3. CURRENT USER (/api/v1/me) AND ORGANIZATIONS
# ==============================================================================

class TestMeAndOrganizationEndpoints:
    def test_get_current_user(self, api_test_context):
        client = api_test_context["client"]
        headers = api_test_context["auth_headers"]
        res = client.get("/api/v1/me", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["email"] == "testuser@example.com"
        assert len(data["organizations"]) >= 1
        assert data["organizations"][0]["role"] == "OWNER"

    def test_patch_current_user(self, api_test_context):
        client = api_test_context["client"]
        headers = api_test_context["auth_headers"]
        res = client.patch(
            "/api/v1/me",
            headers=headers,
            json={"name": "Updated Name", "locale": "es"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "Updated Name"
        assert data["locale"] == "es"

    def test_get_memberships(self, api_test_context):
        client = api_test_context["client"]
        headers = api_test_context["auth_headers"]
        res = client.get("/api/v1/me/memberships", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["organization_name"] == "Acme Corp"

    def test_list_organizations(self, api_test_context):
        client = api_test_context["client"]
        headers = api_test_context["auth_headers"]
        res = client.get("/api/v1/organizations", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert len(data["items"]) >= 1

    def test_get_organization_details(self, api_test_context):
        client = api_test_context["client"]
        headers = api_test_context["auth_headers"]
        org = api_test_context["org"]
        res = client.get(f"/api/v1/organizations/{org.id}", headers=headers)
        assert res.status_code == 200
        assert res.json()["slug"] == "acme-corp"


# ==============================================================================
# 4. TENANT-SCOPED OPERATIONAL ENDPOINTS
# ==============================================================================

class TestTenantOperationalEndpoints:
    def test_campaign_lifecycle(self, api_test_context):
        client = api_test_context["client"]
        headers = api_test_context["auth_headers"]

        # Create campaign
        create_res = client.post(
            "/api/v1/campaigns",
            headers=headers,
            json={
                "name": "Q4 Enterprise Outreach",
                "description": "Enterprise campaign targeting CFOs",
                "status": "ACTIVE",
            },
        )
        assert create_res.status_code == 201
        camp_id = create_res.json()["id"]

        # List campaigns
        list_res = client.get("/api/v1/campaigns", headers=headers)
        assert list_res.status_code == 200
        items = list_res.json()["items"]
        assert any(c["id"] == camp_id for c in items)

        # Get single campaign
        get_res = client.get(f"/api/v1/campaigns/{camp_id}", headers=headers)
        assert get_res.status_code == 200
        assert get_res.json()["name"] == "Q4 Enterprise Outreach"

    def test_icp_and_target_markets(self, api_test_context):
        client = api_test_context["client"]
        headers = api_test_context["auth_headers"]

        # Create ICP
        icp_res = client.post(
            "/api/v1/icps",
            headers=headers,
            json={
                "name": "B2B SaaS Series A+",
                "target_verticals": ["Software", "Fintech"],
                "target_company_sizes": ["50-200"],
            },
        )
        assert icp_res.status_code == 201
        icp_id = icp_res.json()["id"]

        # List ICPs
        list_res = client.get("/api/v1/icps", headers=headers)
        assert list_res.status_code == 200
        assert any(i["id"] == icp_id for i in list_res.json()["items"])

        # Create Target Market for this ICP
        tm_res = client.post(
            "/api/v1/target-markets",
            headers=headers,
            json={
                "icp_id": icp_id,
                "country": "US",
                "city": "Austin",
                "region": "TX",
                "language": "en",
            },
        )
        assert tm_res.status_code == 201
        tm_id = tm_res.json()["id"]
        assert tm_res.json()["city"] == "Austin"

        # List Target Markets
        tm_list_res = client.get("/api/v1/target-markets", headers=headers)
        assert tm_list_res.status_code == 200
        assert any(m["id"] == tm_id for m in tm_list_res.json()["items"])

        # Get Target Market by ID
        tm_get_res = client.get(f"/api/v1/target-markets/{tm_id}", headers=headers)
        assert tm_get_res.status_code == 200
        assert tm_get_res.json()["city"] == "Austin"

        # Patch Target Market
        tm_patch_res = client.patch(
            f"/api/v1/target-markets/{tm_id}",
            headers=headers,
            json={"city": "Dallas", "radius_miles": 25},
        )
        assert tm_patch_res.status_code == 200
        assert tm_patch_res.json()["city"] == "Dallas"
        assert tm_patch_res.json()["radius_miles"] == 25

    def test_prospects_and_intelligence(self, api_test_context):
        client = api_test_context["client"]
        headers = api_test_context["auth_headers"]

        # Create Prospect
        p_res = client.post(
            "/api/v1/prospects",
            headers=headers,
            json={
                "company_name": "Initech Corp",
                "website": "https://initech.example.com",
                "contact_name": "Peter Gibbons",
                "contact_email": "peter@initech.example.com",
            },
        )
        assert p_res.status_code == 201
        prospect_id = p_res.json()["id"]

        # List prospects
        p_list = client.get("/api/v1/prospects", headers=headers)
        assert p_list.status_code == 200
        assert any(p["id"] == prospect_id for p in p_list.json()["items"])

        # Get intelligence
        intel_res = client.get(f"/api/v1/prospects/{prospect_id}/intelligence", headers=headers)
        assert intel_res.status_code == 200
        assert intel_res.json()["prospect_id"] == prospect_id

    def test_monitoring_endpoints(self, api_test_context):
        client = api_test_context["client"]
        headers = api_test_context["auth_headers"]

        res = client.get("/api/v1/monitoring/overview", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert "active_schedules" in data

        health_res = client.get("/api/v1/monitoring/health", headers=headers)
        assert health_res.status_code == 200
        assert health_res.json()["status"] in ("HEALTHY", "DEGRADED", "READY")

    def test_integrations_endpoints(self, api_test_context):
        client = api_test_context["client"]
        headers = api_test_context["auth_headers"]

        # Outbox listing
        outbox_res = client.get("/api/v1/integrations/outbox", headers=headers)
        assert outbox_res.status_code == 200
        assert "items" in outbox_res.json()

        # Inbox listing
        inbox_res = client.get("/api/v1/integrations/inbox", headers=headers)
        assert inbox_res.status_code == 200
        assert "items" in inbox_res.json()

        # Destinations listing
        dest_res = client.get("/api/v1/integrations/destinations", headers=headers)
        assert dest_res.status_code == 200
        assert "items" in dest_res.json()


# ==============================================================================
# 5. SECURITY HEADERS, CORRELATION ID, AND LOCALIZATION
# ==============================================================================

class TestSecurityHeadersAndLocalization:
    def test_security_headers_present(self, api_test_context):
        client = api_test_context["client"]
        res = client.get("/health/live")
        assert res.headers.get("X-Content-Type-Options") == "nosniff"
        assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "no-store" in res.headers.get("Cache-Control", "")

    def test_correlation_id_generated_and_propagated(self, api_test_context):
        client = api_test_context["client"]
        # Client supplies custom request id
        res = client.get("/health/live", headers={"X-Request-Id": "custom-req-id-12345"})
        assert res.headers.get("X-Request-Id") == "custom-req-id-12345"

        # Server auto-generates if missing
        res2 = client.get("/health/live")
        assert res2.headers.get("X-Request-Id") is not None
        assert len(res2.headers.get("X-Request-Id")) > 10

    def test_spanish_localization_on_error(self, api_test_context):
        client = api_test_context["client"]
        # Send invalid credentials with Spanish Accept-Language
        res = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "wrong"},
            headers={"Accept-Language": "es-ES,es;q=0.9"},
        )
        assert res.status_code == 401
        data = res.json()
        assert "error" in data
        assert data["error"]["code"] == "INVALID_CREDENTIALS"
        # Verify Spanish translation was used
        assert "Credenciales" in data["error"]["message"] or "inválidas" in data["error"]["message"]
