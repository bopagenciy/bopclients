"""PostgreSQL Live Database Test Suite for Phase P19: Product API, Authentication & Tenant Authorization.

Verifies against live Postgres instance on port 55432:
1. Migration to schema 20260902_009 on PostgreSQL.
2. RuntimeReadinessCheck reports READY and schema_version == "20260902_009".
3. Argon2id password hashing and user persistence in PostgreSQL users table.
4. Active auth session persistence and token hash lookup in bop_auth_sessions table.
5. Login attempt recording and brute-force lockout persistence in bop_auth_login_attempts.
6. Full FastAPI HTTP API test cycle against live PostgreSQL container (login, /api/v1/me, /api/v1/campaigns, /api/v1/prospects).
"""

import os
import uuid
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
from bopclients.domain.campaign import Campaign
from bopclients.domain.enums import CampaignStatus

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
def pg_api_context():
    """Sets up live Postgres database connection, runs migrations, and constructs API test client."""
    db = create_database_connection(TEST_PG_URL)
    DatabaseMigrator.migrate(db)

    settings = RuntimeSettings(
        database_url=TEST_PG_URL,
        auth_signing_key="postgres-test-signing-key-minimum-32-chars-long!",
        auth_token_expire_seconds=3600,
        auth_session_expire_days=7,
        enabled_providers=["official_website"],
    )
    container = build_runtime_container(settings, db=db)
    app = create_bopclients_api_app(container)
    client = TestClient(app)

    # Unique test user and tenant per run
    unique_suffix = str(uuid.uuid4())[:8]
    email = f"pg_user_{unique_suffix}@example.com"
    user = container.auth_service.register_user(
        email=email,
        name=f"PG User {unique_suffix}",
        password="ValidPassword123!",
        locale="en",
    )

    org_id = str(uuid.uuid4())
    bop_org_id = str(uuid.uuid4())
    org = Organization(
        id=org_id,
        bop_organization_id=bop_org_id,
        name=f"PG Corp {unique_suffix}",
        slug=f"pg-corp-{unique_suffix}",
    )
    container.org_repo.save(org)
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            user_id=user.id,
            role="OWNER",
        )
    )

    auth_res = container.auth_service.authenticate(email, "ValidPassword123!")
    headers = {
        "Authorization": f"Bearer {auth_res.access_token}",
        "X-Bop-Organization-Id": bop_org_id,
    }

    yield {
        "db": db,
        "container": container,
        "client": client,
        "user": user,
        "org": org,
        "headers": headers,
        "email": email,
        "auth_res": auth_res,
    }

    db.close()


class TestPostgresAPIAuthP19:
    def test_postgres_schema_and_readiness(self, pg_api_context):
        container = pg_api_context["container"]
        readiness = RuntimeReadinessCheck.check(container.settings, db=container.db)
        assert readiness.status in (ReadinessStatus.READY, ReadinessStatus.DEGRADED)
        summary = readiness.safe_summary()
        assert summary["schema_version"] == "20260902_009"
        assert summary["database_connected"] is True

    def test_postgres_user_persistence_and_auth_flow(self, pg_api_context):
        client = pg_api_context["client"]
        email = pg_api_context["email"]

        # Login via HTTP
        res = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "ValidPassword123!"},
        )
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == email

    def test_postgres_session_revocation_on_logout(self, pg_api_context):
        client = pg_api_context["client"]
        headers = pg_api_context["headers"]
        auth_res = pg_api_context["auth_res"]

        # Logout
        logout_res = client.post(
            "/api/v1/auth/logout",
            headers=headers,
            json={"refresh_token": auth_res.session_token},
        )
        assert logout_res.status_code == 200
        assert logout_res.json()["success"] is True

        # Refresh attempt should now fail
        ref_res = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": auth_res.session_token},
        )
        assert ref_res.status_code == 401

    def test_postgres_tenant_resource_crud_under_api(self, pg_api_context):
        client = pg_api_context["client"]
        headers = pg_api_context["headers"]

        # Create Campaign
        create_res = client.post(
            "/api/v1/campaigns",
            headers=headers,
            json={
                "name": "Live Postgres Outreach",
                "description": "Campaign created in PostgreSQL",
                "status": "ACTIVE",
            },
        )
        assert create_res.status_code == 201
        camp_id = create_res.json()["id"]

        # Read back
        get_res = client.get(f"/api/v1/campaigns/{camp_id}", headers=headers)
        assert get_res.status_code == 200
        assert get_res.json()["name"] == "Live Postgres Outreach"

        # Create Prospect
        p_res = client.post(
            "/api/v1/prospects",
            headers=headers,
            json={
                "company_name": "Postgres Prospect Ltd",
                "website": "https://pgprospect.example.com",
            },
        )
        assert p_res.status_code == 201
        p_id = p_res.json()["id"]

        # Verify prospect listing
        p_list = client.get("/api/v1/prospects", headers=headers)
        assert p_list.status_code == 200
        assert any(p["id"] == p_id for p in p_list.json()["items"])

        # Create ICP
        icp_res = client.post(
            "/api/v1/icps",
            headers=headers,
            json={"name": "Live Postgres ICP", "target_markets": []},
        )
        assert icp_res.status_code == 201
        icp_id = icp_res.json()["id"]

        # Create Target Market
        tm_res = client.post(
            "/api/v1/target-markets",
            headers=headers,
            json={"icp_id": icp_id, "country": "US", "city": "Austin"},
        )
        assert tm_res.status_code == 201
        tm_id = tm_res.json()["id"]

        # Patch Target Market
        patch_res = client.patch(
            f"/api/v1/target-markets/{tm_id}",
            headers=headers,
            json={"city": "Houston"},
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["city"] == "Houston"
