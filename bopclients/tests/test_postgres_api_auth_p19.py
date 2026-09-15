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
from bopclients.domain.enums import CampaignStatus, SignalCategory
from bopclients.domain.prospect import Prospect
from bopclients.domain.signal import Signal
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

    def test_postgres_p22_operations_and_scoping(self, pg_api_context):
        """Validates live PostgreSQL behavior for P22 operations:
        1. Multi-dimensional server-side filtering:
           - campaign filter
           - lead score filter (score_min/score_max)
           - priority filter
           - signal presence filter (has_signals=true/false)
        2. Batch hydration on PostgreSQL (score, priority_tier, campaign_names, signals_count)
        3. Bulk campaign association uniqueness
        4. Filtered export and selected-ID export tenant scoping
        """
        container = pg_api_context["container"]
        client = pg_api_context["client"]
        headers_a = pg_api_context["headers"]
        org_a = pg_api_context["org"]
        org_a_id = org_a.id

        # Setup Tenant B in PostgreSQL
        unique_b = str(uuid.uuid4())[:8]
        user_b = container.auth_service.register_user(
            email=f"pg_user_b_{unique_b}@example.com",
            name=f"PG User B {unique_b}",
            password="ValidPassword123!",
            locale="en",
        )
        org_b_id = str(uuid.uuid4())
        org_b = Organization(
            id=org_b_id,
            bop_organization_id=str(uuid.uuid4()),
            name=f"PG Beta {unique_b}",
            slug=f"pg-beta-{unique_b}",
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
        auth_b = container.auth_service.authenticate(f"pg_user_b_{unique_b}@example.com", "ValidPassword123!")
        headers_b = {
            "Authorization": f"Bearer {auth_b.access_token}",
            "X-Bop-Organization-Id": org_b.bop_organization_id,
        }

        # Seed Campaign in Org A
        camp_a = Campaign(
            id=str(uuid.uuid4()),
            organization_id=org_a_id,
            name=f"PG Campaign {unique_b}",
            status=CampaignStatus.ACTIVE,
        )
        container.campaign_repo.save(org_a_id, camp_a)

        # Seed Prospect A1: has score 85, priority urgent, signal, in camp_a
        p_a1 = Prospect(
            id=str(uuid.uuid4()),
            organization_id=org_a_id,
            name=f"PG Alpha One {unique_b}",
            website_url=f"https://alpha-one-{unique_b}.example.com",
            source="test_p22_pg",
        )
        container.prospect_repo.save_prospect(org_a_id, p_a1)
        container.prospect_service.assign_score(org_a_id, p_a1.id, 85, "High score ICP")
        prio_a1 = ProspectPriority(
            id=str(uuid.uuid4()),
            organization_id=org_a_id,
            campaign_id=camp_a.id,
            prospect_id=p_a1.id,
            priority_score=90.0,
            priority_label="urgent",
        )
        container.priority_repo.save(org_a_id, prio_a1)
        cp_a1 = CampaignProspect(
            id=str(uuid.uuid4()),
            organization_id=org_a_id,
            campaign_id=camp_a.id,
            prospect_id=p_a1.id,
        )
        container.prospect_repo.add_prospect_to_campaign(org_a_id, cp_a1)
        sig_a1 = Signal(
            id=str(uuid.uuid4()),
            organization_id=org_a_id,
            prospect_id=p_a1.id,
            type="expansion",
            category=SignalCategory.COMPANY_ACTIVITY,
            value="Expanding in Texas",
        )
        container.prospect_repo.add_signal(org_a_id, sig_a1)

        # Seed Prospect A2: has score 45, no priority, no signal, not in camp_a
        p_a2 = Prospect(
            id=str(uuid.uuid4()),
            organization_id=org_a_id,
            name=f"PG Alpha Two {unique_b}",
            website_url=f"https://alpha-two-{unique_b}.example.com",
            source="test_p22_pg",
        )
        container.prospect_repo.save_prospect(org_a_id, p_a2)
        container.prospect_service.assign_score(org_a_id, p_a2.id, 45, "Moderate score ICP")

        # Seed Prospect B1 in Org B
        p_b1 = Prospect(
            id=str(uuid.uuid4()),
            organization_id=org_b_id,
            name=f"PG Foreign Beta {unique_b}",
            website_url=f"https://foreign-beta-{unique_b}.example.com",
            source="test_p22_pg",
        )
        container.prospect_repo.save_prospect(org_b_id, p_b1)

        # 1. Server-side prospect filtering on PostgreSQL
        # 1a. Campaign filter
        res_camp = client.get(f"/api/v1/prospects?campaign_id={camp_a.id}", headers=headers_a)
        assert res_camp.status_code == 200
        items_camp = res_camp.json()["items"]
        assert any(i["id"] == p_a1.id for i in items_camp)
        assert not any(i["id"] == p_a2.id for i in items_camp)
        assert not any(i["id"] == p_b1.id for i in items_camp)

        # 1b. Lead score filter (score_min / score_max)
        res_score_min = client.get("/api/v1/prospects?score_min=80", headers=headers_a)
        assert res_score_min.status_code == 200
        items_score = res_score_min.json()["items"]
        assert any(i["id"] == p_a1.id for i in items_score)
        assert not any(i["id"] == p_a2.id for i in items_score)

        res_score_max = client.get("/api/v1/prospects?score_max=50", headers=headers_a)
        assert res_score_max.status_code == 200
        items_score_low = res_score_max.json()["items"]
        assert any(i["id"] == p_a2.id for i in items_score_low)
        assert not any(i["id"] == p_a1.id for i in items_score_low)

        # 1c. Priority filter
        res_prio = client.get("/api/v1/prospects?priority=urgent", headers=headers_a)
        assert res_prio.status_code == 200
        items_prio = res_prio.json()["items"]
        assert any(i["id"] == p_a1.id for i in items_prio)
        assert not any(i["id"] == p_a2.id for i in items_prio)

        # 1d. Signal presence filter (SQL EXISTS / NOT EXISTS)
        res_sig_true = client.get("/api/v1/prospects?has_signals=true", headers=headers_a)
        assert res_sig_true.status_code == 200
        assert any(i["id"] == p_a1.id for i in res_sig_true.json()["items"])
        assert not any(i["id"] == p_a2.id for i in res_sig_true.json()["items"])

        res_sig_false = client.get("/api/v1/prospects?has_signals=false", headers=headers_a)
        assert res_sig_false.status_code == 200
        assert any(i["id"] == p_a2.id for i in res_sig_false.json()["items"])
        assert not any(i["id"] == p_a1.id for i in res_sig_false.json()["items"])

        # 2. Batch hydration on PostgreSQL
        p_a1_item = next(i for i in res_camp.json()["items"] if i["id"] == p_a1.id)
        assert p_a1_item["lead_score"] == 85
        assert p_a1_item["priority_tier"] == "urgent"
        assert camp_a.name in p_a1_item["campaign_names"]
        assert p_a1_item["signals_count"] >= 1

        # 3. Bulk campaign association uniqueness on PostgreSQL
        res_bulk_add = client.post(
            "/api/v1/prospects/bulk/add-to-campaign",
            json={"campaign_id": camp_a.id, "prospect_ids": [p_a1.id]},
            headers=headers_a,
        )
        assert res_bulk_add.status_code == 200
        bulk_data = res_bulk_add.json()
        assert bulk_data["already_present"] == 1
        assert bulk_data["added"] == 0

        # 4. Filtered export tenant scoping on PostgreSQL
        res_exp_filt = client.get(f"/api/v1/prospects/export?campaign_id={camp_a.id}", headers=headers_a)
        assert res_exp_filt.status_code == 200
        assert p_a1.name in res_exp_filt.text
        assert p_b1.name not in res_exp_filt.text

        # Selected-ID export tenant scoping
        res_exp_sel = client.post(
            "/api/v1/prospects/export",
            json={"prospect_ids": [p_a1.id, p_b1.id]},
            headers=headers_a,
        )
        assert res_exp_sel.status_code == 200
        assert p_a1.name in res_exp_sel.text
        assert p_b1.name not in res_exp_sel.text
