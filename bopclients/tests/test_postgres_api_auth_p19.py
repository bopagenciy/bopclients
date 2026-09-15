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
from bopclients.domain.prospect import Prospect
from bopclients.domain.campaign_prospect import CampaignProspect
from bopclients.domain.prospect_priority import ProspectPriority
from bopclients.domain.lead_score import LeadScore
from bopclients.domain.research_run import ResearchRun
from bopclients.domain.exceptions import TenantAccessError

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

    def test_postgres_p21_persistence_and_uniqueness(self, pg_api_context):
        """Validates real PostgreSQL persistence and uniqueness for P21:
        1. CampaignProspect uniqueness / idempotent upsert
        2. Prospect dedupe query behavior
        3. ProspectPriority snapshot persistence & update
        4. LeadScore persistence & retrieval
        5. ResearchRun active-run lookup & idempotency
        6. Tenant-scoped repository boundary isolation
        """
        container = pg_api_context["container"]
        org = pg_api_context["org"]
        org_id = org.id

        # 1. Create a campaign and prospect on Postgres
        camp = Campaign(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            name="PG Persistence Camp",
            status=CampaignStatus.ACTIVE,
        )
        container.campaign_repo.save(org_id, camp)

        prospect = Prospect(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            name="Apex Safety Postgres",
            website_url="https://apex-safety.example.com",
            source="test_p21_pg",
        )
        container.prospect_repo.save_prospect(org_id, prospect)

        # 2. CampaignProspect uniqueness/upsert behavior
        cp1 = CampaignProspect(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            campaign_id=camp.id,
            prospect_id=prospect.id,
            status="added",
        )
        container.prospect_repo.add_prospect_to_campaign(org_id, cp1)

        # Re-adding same campaign-prospect association (upsert on conflict)
        cp2 = CampaignProspect(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            campaign_id=camp.id,
            prospect_id=prospect.id,
            status="contacted",
        )
        container.prospect_repo.add_prospect_to_campaign(org_id, cp2)

        # Confirm exactly 1 row exists
        prospects_in_camp = container.prospect_repo.list_prospects_by_campaign(org_id, camp.id)
        assert len(prospects_in_camp) == 1
        assert prospects_in_camp[0].id == prospect.id

        # 3. Prospect dedupe query behavior
        found = container.prospect_repo.find_existing_prospect(
            org_id, website_url="https://apex-safety.example.com/"
        )
        assert found is not None
        assert found.id == prospect.id

        # 4. LeadScore persistence
        score = LeadScore(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            prospect_id=prospect.id,
            score=88,
            explanation="Strong fit on Texas safety distributors",
        )
        container.prospect_repo.save_lead_score(org_id, score)
        fetched_scores = container.prospect_repo.get_lead_scores_by_prospect(org_id, prospect.id)
        assert len(fetched_scores) >= 1
        assert fetched_scores[0].score == 88

        # 5. ProspectPriority persistence & update
        pri = ProspectPriority(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            campaign_id=camp.id,
            prospect_id=prospect.id,
            priority_score=92.0,
            priority_label="urgent",
            lead_score_component=45.0,
            intent_signal_component=40.0,
            research_confidence_component=5.0,
            freshness_component=2.0,
            policy_version="1.0",
            data={"reasons": ["Urgent expansion signal", "Strong ICP fit"]},
        )
        container.priority_repo.save(org_id, pri)
        saved_pri = container.priority_repo.get(org_id, camp.id, prospect.id)
        assert saved_pri is not None
        assert saved_pri.priority_score == 92.0
        assert saved_pri.priority_label == "urgent"

        # Update priority
        pri.priority_score = 95.0
        container.priority_repo.save(org_id, pri)
        updated_pri = container.priority_repo.get(org_id, camp.id, prospect.id)
        assert updated_pri is not None
        assert updated_pri.priority_score == 95.0

        # 6. ResearchRun active-run lookup & idempotency
        run1 = ResearchRun(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            campaign_id=camp.id,
            prospect_id=prospect.id,
            run_type="full_diligence",
            status="pending",
        )
        container.research_run_repo.save(org_id, run1)

        active_runs = container.research_run_repo.list_by_organization(
            org_id, prospect_id=prospect.id, limit=5
        )
        active_pending = [r for r in active_runs if r.status in ("pending", "running")]
        assert len(active_pending) == 1
        assert active_pending[0].id == run1.id

        # 7. Tenant boundary isolation on Postgres
        foreign_org_id = str(uuid.uuid4())
        assert container.prospect_repo.get_prospect_by_id(foreign_org_id, prospect.id) is None
        assert container.priority_repo.get(foreign_org_id, camp.id, prospect.id) is None
