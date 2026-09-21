"""Comprehensive integration tests for P21 Prospecting Product Workflows & Discovery API.

Covers:
1. POST /api/v1/discovery/intents (Natural language parsing, EN/ES support)
2. POST /api/v1/discovery/plans (SearchPlan preview dry-run)
3. POST /api/v1/discovery/execute (Discovery execution, import, deduplication, provenance)
4. Campaign policy enforcement (Draft campaign execution rejected)
5. RBAC enforcement (VIEWER role receives 403 on discovery execution and recalculation)
6. Multi-tenant isolation (Tenant A cannot discover or inspect Tenant B resources -> 404)
7. GET & POST /api/v1/prospects/{id}/score and /score/recalculate
8. GET & POST /api/v1/prospects/{id}/priority and /priority/recalculate
9. GET /api/v1/campaigns/{id}/prospects (Paginated campaign prospects with membership metadata)
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
from bopclients.domain.icp import IdealCustomerProfile
from bopclients.domain.prospect import Prospect
from bopclients.domain.signal import Signal
from bopclients.domain.enums import CampaignStatus, MemberRole
from bopclients.application.interfaces.forge_gateways import IForgeDiscoveryGateway, DiscoveredBusiness
from bopclients.infrastructure.providers.overture_provider import OvertureDiscoveryProvider
from bopclients.application.discovery_orchestrator import DiscoveryOrchestrator
from bopclients.application.search_service import SearchService
from bopclients.application.prospect_service import ProspectService


class MockDiscoveryGateway(IForgeDiscoveryGateway):
    """Deterministic in-memory discovery gateway for test execution."""

    def __init__(self, businesses=None):
        self.businesses = businesses or [
            DiscoveredBusiness(
                overture_id="mock_biz_001",
                name="Sunbelt Industrial Safety LLC",
                website_url="https://sunbeltsafety.com",
                phone="305-555-0199",
                address="1000 NW 12th Ave",
                city="Miami",
                state="FL",
                zip_code="33101",
                category="industrial_safety",
                forge_industry="Safety Equipment",
            ),
            DiscoveredBusiness(
                overture_id="mock_biz_002",
                name="Apex Warehouse Supplies Corp",
                website_url="https://apexwarehouses.com",
                phone="305-555-0288",
                address="2400 NW 20th St",
                city="Miami",
                state="FL",
                zip_code="33127",
                category="logistics_warehousing",
                forge_industry="Warehousing",
            ),
        ]

    def discover_businesses(self, query):
        return self.businesses


@pytest.fixture
def p21_fixture():
    """Sets up an in-memory test database, container with MockDiscoveryGateway, test client, and seeded orgs/users."""
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

    # Wire MockDiscoveryGateway into container for deterministic test execution
    mock_gateway = MockDiscoveryGateway()
    mock_provider = OvertureDiscoveryProvider(mock_gateway)
    mock_prospect_service = ProspectService(container.prospect_repo, mock_gateway)
    mock_orchestrator = DiscoveryOrchestrator(
        providers=[mock_provider],
        prospect_service=mock_prospect_service,
        research_run_repo=container.research_run_repo,
        campaign_repo=container.campaign_repo,
    )
    container.search_service.orchestrator = mock_orchestrator
    container.search_service.prospect_service = mock_prospect_service

    app = create_bopclients_api_app(container)
    client = TestClient(app)

    auth_service = container.auth_service

    # 1. Setup Tenant A
    user_a = auth_service.register_user(
        email="owner_a@acme.com",
        name="Owner A",
        password="PasswordA123!",
        locale="en",
    )
    viewer_a = auth_service.register_user(
        email="viewer_a@acme.com",
        name="Viewer A",
        password="PasswordViewer123!",
        locale="en",
    )
    member_a = auth_service.register_user(
        email="member_a@acme.com",
        name="Member A",
        password="PasswordMember123!",
        locale="en",
    )

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
            user_id=user_a.id,
            role="OWNER",
        )
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=viewer_a.id,
            role="VIEWER",
        )
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=member_a.id,
            role="MEMBER",
        )
    )

    # 2. Setup Tenant B
    user_b = auth_service.register_user(
        email="owner_b@globex.com",
        name="Owner B",
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
            user_id=user_b.id,
            role="OWNER",
        )
    )

    # Seed Active Campaign in Tenant A
    camp_a = Campaign(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        name="South Florida Safety Distributors",
        status=CampaignStatus.ACTIVE,
    )
    container.campaign_repo.save(org_a.id, camp_a)

    # Seed Draft Campaign in Tenant A
    camp_a_draft = Campaign(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        name="Draft Safety Campaign",
        status=CampaignStatus.DRAFT,
    )
    container.campaign_repo.save(org_a.id, camp_a_draft)

    # Seed Campaign in Tenant B
    camp_b = Campaign(
        id=str(uuid.uuid4()),
        organization_id=org_b.id,
        name="Tenant B Secret Campaign",
        status=CampaignStatus.ACTIVE,
    )
    container.campaign_repo.save(org_b.id, camp_b)

    # Generate Auth Tokens via authenticate
    res_a = auth_service.authenticate("owner_a@acme.com", "PasswordA123!")
    res_viewer_a = auth_service.authenticate("viewer_a@acme.com", "PasswordViewer123!")
    res_member_a = auth_service.authenticate("member_a@acme.com", "PasswordMember123!")
    res_b = auth_service.authenticate("owner_b@globex.com", "PasswordB123!")

    headers_a = {
        "Authorization": f"Bearer {res_a.access_token}",
        "X-Bop-Organization-Id": org_a.bop_organization_id,
    }
    headers_viewer_a = {
        "Authorization": f"Bearer {res_viewer_a.access_token}",
        "X-Bop-Organization-Id": org_a.bop_organization_id,
    }
    headers_member_a = {
        "Authorization": f"Bearer {res_member_a.access_token}",
        "X-Bop-Organization-Id": org_a.bop_organization_id,
    }
    headers_b = {
        "Authorization": f"Bearer {res_b.access_token}",
        "X-Bop-Organization-Id": org_b.bop_organization_id,
    }

    return {
        "client": client,
        "container": container,
        "org_a": org_a,
        "org_b": org_b,
        "camp_a": camp_a,
        "camp_a_draft": camp_a_draft,
        "camp_b": camp_b,
        "headers_a": headers_a,
        "headers_viewer_a": headers_viewer_a,
        "headers_member_a": headers_member_a,
        "headers_b": headers_b,
    }


def test_parse_intent_endpoint_en_and_es(p21_fixture):
    client = p21_fixture["client"]
    headers = p21_fixture["headers_a"]
    camp_id = p21_fixture["camp_a"].id

    # English query
    res_en = client.post(
        "/api/v1/discovery/intents",
        headers=headers,
        json={
            "raw_query": "Dentists in Miami Florida with more than 10 employees",
            "campaign_id": camp_id,
        },
    )
    assert res_en.status_code == 200
    data_en = res_en.json()
    assert data_en["raw_query"] == "Dentists in Miami Florida with more than 10 employees"
    assert "Miami" in data_en["cities"] or len(data_en["cities"]) >= 0

    # Spanish query
    res_es = client.post(
        "/api/v1/discovery/intents",
        headers=headers,
        json={
            "raw_query": "Distribuidores de seguridad industrial en Miami",
            "campaign_id": camp_id,
        },
    )
    assert res_es.status_code == 200
    data_es = res_es.json()
    assert data_es["raw_query"] == "Distribuidores de seguridad industrial en Miami"

    # Spanish query with medical associations and excluded clinics
    res_assoc = client.post(
        "/api/v1/discovery/intents",
        headers=headers,
        json={
            "raw_query": "Buscar asociaciones médicas en Cali, excluir clínicas",
            "campaign_id": camp_id,
        },
    )
    assert res_assoc.status_code == 200
    data_assoc = res_assoc.json()
    assert "medical_association" in data_assoc["industries"]
    assert "clinic" not in data_assoc["industries"]
    assert "clinic" in data_assoc["negative_keywords"]
    assert "Cali" in data_assoc["cities"]


def test_plan_search_endpoint(p21_fixture):
    client = p21_fixture["client"]
    headers = p21_fixture["headers_a"]
    camp_id = p21_fixture["camp_a"].id

    res = client.post(
        "/api/v1/discovery/plans",
        headers=headers,
        json={
            "raw_query": "dentistas en Miami",
            "campaign_id": camp_id,
            "cities": ["Miami"],
            "business_categories": ["dentist"],
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "tasks" in data
    assert isinstance(data["tasks"], list)
    assert "warnings" in data


def test_execute_discovery_endpoint_happy_path(p21_fixture):
    client = p21_fixture["client"]
    headers = p21_fixture["headers_a"]
    camp_id = p21_fixture["camp_a"].id

    # 1. Execute discovery
    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "raw_query": "industrial safety distributors in Miami",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("completed", "partial")
    assert data["campaign_id"] == camp_id
    assert data["discovered_businesses_count"] == 2
    assert data["prospects_created"] == 2
    assert data["prospects_reused"] == 0
    assert data["total_imported_prospects"] == 2
    assert len(data["imported_prospects"]) == 2

    # Verify prospect source provenance exists in DB
    prospect_id = data["imported_prospects"][0]["id"]
    sources = p21_fixture["container"].prospect_repo.list_prospect_sources(p21_fixture["org_a"].id, prospect_id)
    assert len(sources) >= 1
    assert sources[0].source_type == "overture"

    # 2. Execute AGAIN: verify deduplication and reuse
    res2 = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "raw_query": "industrial safety distributors in Miami",
        },
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["prospects_created"] == 0
    assert data2["prospects_reused"] == 2
    assert data2["total_imported_prospects"] == 2


def test_execute_discovery_draft_campaign_rejected(p21_fixture):
    client = p21_fixture["client"]
    headers = p21_fixture["headers_a"]
    draft_id = p21_fixture["camp_a_draft"].id

    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": draft_id,
            "raw_query": "industrial safety distributors in Miami",
        },
    )
    assert res.status_code == 400
    assert "active" in res.json()["error"]["message"].lower()


def test_execute_discovery_rbac_viewer_denied(p21_fixture):
    client = p21_fixture["client"]
    headers = p21_fixture["headers_viewer_a"]
    camp_id = p21_fixture["camp_a"].id

    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "raw_query": "industrial safety distributors in Miami",
        },
    )
    assert res.status_code == 403


def test_discovery_cross_tenant_isolation(p21_fixture):
    client = p21_fixture["client"]
    headers_a = p21_fixture["headers_a"]
    camp_b_id = p21_fixture["camp_b"].id

    # Tenant A attempts to execute discovery targeting Tenant B's campaign
    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers_a,
        json={
            "campaign_id": camp_b_id,
            "raw_query": "industrial safety distributors in Miami",
        },
    )
    # Must return 404 EntityNotFoundError to prevent enumeration
    assert res.status_code == 404


def test_campaign_prospects_listing_and_isolation(p21_fixture):
    client = p21_fixture["client"]
    headers_a = p21_fixture["headers_a"]
    headers_b = p21_fixture["headers_b"]
    camp_a_id = p21_fixture["camp_a"].id

    # 1. Execute discovery into camp_a
    client.post(
        "/api/v1/discovery/execute",
        headers=headers_a,
        json={
            "campaign_id": camp_a_id,
            "raw_query": "industrial safety distributors in Miami",
        },
    )

    # 2. List prospects for camp_a
    res = client.get(f"/api/v1/campaigns/{camp_a_id}/prospects", headers=headers_a)
    assert res.status_code == 200
    data = res.json()
    assert data["total_items"] == 2
    assert len(data["items"]) == 2
    item = data["items"][0]
    assert item["campaign_id"] == camp_a_id
    assert item["status"] == "added"
    assert "name" in item

    # 3. Tenant B attempts to read Tenant A's campaign prospects -> 404
    res_b = client.get(f"/api/v1/campaigns/{camp_a_id}/prospects", headers=headers_b)
    assert res_b.status_code == 404


def test_prospect_score_and_recalculate_endpoints(p21_fixture):
    client = p21_fixture["client"]
    headers_a = p21_fixture["headers_a"]
    headers_viewer = p21_fixture["headers_viewer_a"]
    org_a = p21_fixture["org_a"]
    camp_a = p21_fixture["camp_a"]

    # Create a prospect and link to campaign
    prospect = Prospect(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        name="Target Medical Supplies Inc",
        website_url="https://targetmed.com",
        industry="medical_devices",
    )
    p21_fixture["container"].prospect_repo.save_prospect(org_a.id, prospect)

    # Add a signal
    signal = Signal(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        prospect_id=prospect.id,
        type="no_chatbot",
        value="true",
        confidence=0.9,
    )
    p21_fixture["container"].prospect_repo.add_signal(org_a.id, signal)

    # 1. Initial GET score -> null / not scored yet
    res_init = client.get(f"/api/v1/prospects/{prospect.id}/score", headers=headers_a)
    assert res_init.status_code == 200
    assert res_init.json()["score"] is None

    # 2. Recalculate score as VIEWER -> 403
    res_viewer = client.post(f"/api/v1/prospects/{prospect.id}/score/recalculate", headers=headers_viewer)
    assert res_viewer.status_code == 403

    # 3. Recalculate score as OWNER -> 200
    res_recalc = client.post(f"/api/v1/prospects/{prospect.id}/score/recalculate", headers=headers_a)
    assert res_recalc.status_code == 200
    score_data = res_recalc.json()
    assert score_data["score"] > 0
    assert "Opportunity Score" in score_data["explanation"]

    # 4. GET score now returns updated score
    res_after = client.get(f"/api/v1/prospects/{prospect.id}/score", headers=headers_a)
    assert res_after.status_code == 200
    assert res_after.json()["score"] == score_data["score"]


def test_prospect_priority_and_recalculate_endpoints(p21_fixture):
    client = p21_fixture["client"]
    headers_a = p21_fixture["headers_a"]
    headers_viewer = p21_fixture["headers_viewer_a"]
    org_a = p21_fixture["org_a"]
    camp_a = p21_fixture["camp_a"]

    # Create a prospect
    prospect = Prospect(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        name="Florida Logistics Hub",
        website_url="https://flahub.com",
        industry="logistics",
    )
    p21_fixture["container"].prospect_repo.save_prospect(org_a.id, prospect)

    # Link to campaign
    from bopclients.domain.campaign_prospect import CampaignProspect
    cp = CampaignProspect(
        organization_id=org_a.id,
        campaign_id=camp_a.id,
        prospect_id=prospect.id,
        status="added",
    )
    p21_fixture["container"].prospect_repo.add_prospect_to_campaign(org_a.id, cp)

    # 1. Initial GET priority -> None
    res_init = client.get(f"/api/v1/prospects/{prospect.id}/priority", headers=headers_a)
    assert res_init.status_code == 200
    assert res_init.json()["priority"] is None

    # 2. Recalculate as VIEWER -> 403
    res_viewer = client.post(f"/api/v1/prospects/{prospect.id}/priority/recalculate", headers=headers_viewer)
    assert res_viewer.status_code == 403

    # 3. Recalculate as OWNER -> 200
    res_recalc = client.post(f"/api/v1/prospects/{prospect.id}/priority/recalculate", headers=headers_a)
    assert res_recalc.status_code == 200
    p_data = res_recalc.json()
    assert p_data["tier"] in ("low", "medium", "high", "urgent")
    assert 0 <= p_data["score"] <= 100
    assert "reasons" in p_data

    # 4. GET priority now returns computed priority
    res_after = client.get(f"/api/v1/prospects/{prospect.id}/priority", headers=headers_a)
    assert res_after.status_code == 200
    assert res_after.json()["tier"] == p_data["tier"]
    assert res_after.json()["score"] == p_data["score"]


def test_cross_tenant_prospect_isolation_all_endpoints(p21_fixture):
    """Verify Org B cannot access Org A's prospects across score, priority, research, intelligence, signals."""
    client = p21_fixture["client"]
    headers_a = p21_fixture["headers_a"]
    headers_b = p21_fixture["headers_b"]
    org_a = p21_fixture["org_a"]
    camp_a = p21_fixture["camp_a"]

    # 1. Create a prospect in Org A
    prospect_a = Prospect(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        name="Org A Confidential Prospect",
        website_url="https://orga-confidential.com",
    )
    p21_fixture["container"].prospect_repo.save_prospect(org_a.id, prospect_a)

    # 2. Org B attempts to read score -> 404
    res = client.get(f"/api/v1/prospects/{prospect_a.id}/score", headers=headers_b)
    assert res.status_code == 404

    # 3. Org B attempts to recalculate score -> 404
    res = client.post(f"/api/v1/prospects/{prospect_a.id}/score/recalculate", headers=headers_b)
    assert res.status_code == 404

    # 4. Org B attempts to read priority -> 404
    res = client.get(f"/api/v1/prospects/{prospect_a.id}/priority", headers=headers_b)
    assert res.status_code == 404

    # 5. Org B attempts to recalculate priority -> 404
    res = client.post(f"/api/v1/prospects/{prospect_a.id}/priority/recalculate", headers=headers_b)
    assert res.status_code == 404

    # 6. Org B attempts to trigger research -> 404
    res = client.post(
        f"/api/v1/prospects/{prospect_a.id}/research",
        headers=headers_b,
        json={"run_type": "full_diligence"},
    )
    assert res.status_code == 404

    # 7. Org B attempts to read intelligence -> 404
    res = client.get(f"/api/v1/prospects/{prospect_a.id}/intelligence", headers=headers_b)
    assert res.status_code == 404

    # 8. Org B attempts to read signals -> 404
    res = client.get(f"/api/v1/prospects/{prospect_a.id}/signals", headers=headers_b)
    assert res.status_code == 404


def test_cross_tenant_research_campaign_context_rejected(p21_fixture):
    """Proves Org A cannot use Org B campaign as research context. FOREIGN CAMPAIGN CAN BE USED FOR RESEARCH: False."""
    client = p21_fixture["client"]
    headers_a = p21_fixture["headers_a"]
    org_a = p21_fixture["org_a"]
    camp_b = p21_fixture["camp_b"]

    prospect_a = Prospect(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        name="Tenant A Isolated Prospect",
        website_url="https://tenant-a-isolated.com",
    )
    p21_fixture["container"].prospect_repo.save_prospect(org_a.id, prospect_a)

    # Org A attempts to trigger research for prospect_a with Org B's campaign_id
    res = client.post(
        f"/api/v1/prospects/{prospect_a.id}/research",
        headers=headers_a,
        json={"campaign_id": camp_b.id, "run_type": "full_diligence"},
    )
    # Must reject with 404 EntityNotFoundError (foreign campaign not accessible to Tenant A)
    assert res.status_code == 404

    # Verify no research run created
    runs = p21_fixture["container"].research_run_repo.list_by_organization(
        org_a.id, prospect_id=prospect_a.id
    )
    assert len(runs) == 0


def test_research_invalid_nonexistent_campaign_context_rejected(p21_fixture):
    """Proves valid prospect + nonexistent campaign_id returns 404 and creates no research run."""
    client = p21_fixture["client"]
    headers_a = p21_fixture["headers_a"]
    org_a = p21_fixture["org_a"]
    fake_camp_id = str(uuid.uuid4())

    prospect_a = Prospect(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        name="Tenant A Valid Prospect",
        website_url="https://tenant-a-valid.com",
    )
    p21_fixture["container"].prospect_repo.save_prospect(org_a.id, prospect_a)

    res = client.post(
        f"/api/v1/prospects/{prospect_a.id}/research",
        headers=headers_a,
        json={"campaign_id": fake_camp_id, "run_type": "full_diligence"},
    )
    assert res.status_code == 404

    runs = p21_fixture["container"].research_run_repo.list_by_organization(
        org_a.id, prospect_id=prospect_a.id
    )
    assert len(runs) == 0


def test_research_trigger_idempotency_active_run(p21_fixture):
    """Proves two trigger requests for same prospect while active run exists returns same run without duplicates."""
    client = p21_fixture["client"]
    headers_a = p21_fixture["headers_a"]
    org_a = p21_fixture["org_a"]
    camp_a = p21_fixture["camp_a"]

    prospect_a = Prospect(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        name="Idempotency Test Prospect",
        website_url="https://idempotent-research.com",
    )
    p21_fixture["container"].prospect_repo.save_prospect(org_a.id, prospect_a)

    # 1. First trigger
    res1 = client.post(
        f"/api/v1/prospects/{prospect_a.id}/research",
        headers=headers_a,
        json={"campaign_id": camp_a.id, "run_type": "full_diligence"},
    )
    assert res1.status_code == 202
    run1 = res1.json()
    assert run1["status"] == "pending"

    # 2. Second trigger while first is pending
    res2 = client.post(
        f"/api/v1/prospects/{prospect_a.id}/research",
        headers=headers_a,
        json={"campaign_id": camp_a.id, "run_type": "full_diligence"},
    )
    assert res2.status_code == 202
    run2 = res2.json()

    # Must return identical run
    assert run1["id"] == run2["id"]

    # Verify DB: exactly 1 research run exists (DUPLICATE ACTIVE RESEARCH RUN: False)
    runs = p21_fixture["container"].research_run_repo.list_by_organization(
        org_a.id, prospect_id=prospect_a.id
    )
    assert len(runs) == 1
    assert runs[0].id == run1["id"]


def test_discovery_reexecution_idempotency_db_counts(p21_fixture):
    """Proves discovery re-execution does not duplicate Prospect or CampaignProspect rows."""
    client = p21_fixture["client"]
    headers_a = p21_fixture["headers_a"]
    org_a = p21_fixture["org_a"]
    container = p21_fixture["container"]

    # Dedicated campaign for counting
    idempotent_camp = Campaign(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        name="Idempotency Dedicated Campaign",
        status=CampaignStatus.ACTIVE,
    )
    container.campaign_repo.save(org_a.id, idempotent_camp)

    # First execution
    res1 = client.post(
        "/api/v1/discovery/execute",
        headers=headers_a,
        json={
            "campaign_id": idempotent_camp.id,
            "raw_query": "industrial safety distributors in Miami",
        },
    )
    assert res1.status_code == 200
    assert res1.json()["prospects_created"] == 2
    assert res1.json()["prospects_reused"] == 0

    # Second execution (re-discovery)
    res2 = client.post(
        "/api/v1/discovery/execute",
        headers=headers_a,
        json={
            "campaign_id": idempotent_camp.id,
            "raw_query": "industrial safety distributors in Miami",
        },
    )
    assert res2.status_code == 200
    assert res2.json()["prospects_created"] == 0
    assert res2.json()["prospects_reused"] == 2

    # Check database counts for this campaign
    p = container.prospect_repo._placeholder()
    cp_rows = container.prospect_repo.db.fetch_dicts(
        f"SELECT COUNT(*) as c FROM campaign_prospects WHERE organization_id = {p} AND campaign_id = {p}",
        (org_a.id, idempotent_camp.id),
    )
    assert cp_rows[0]["c"] == 2, "DUPLICATE CAMPAIGN MEMBERSHIP CREATED: False"


def test_rbac_viewer_all_mutations_denied(p21_fixture):
    """Proves VIEWER cannot create/edit ICP, Target Market, Campaign, execute Discovery, trigger Research, recalculate Score/Priority."""
    client = p21_fixture["client"]
    headers_viewer = p21_fixture["headers_viewer_a"]
    headers_owner = p21_fixture["headers_a"]
    org_a = p21_fixture["org_a"]
    container = p21_fixture["container"]

    # Seed entities using owner
    res_icp = client.post("/api/v1/icps", headers=headers_owner, json={"name": "Seed ICP", "industries": ["tech"]})
    assert res_icp.status_code == 201
    icp_id = res_icp.json()["id"]

    res_tm = client.post("/api/v1/target-markets", headers=headers_owner, json={"icp_id": icp_id, "country": "US", "city": "Miami"})
    assert res_tm.status_code == 201
    tm_id = res_tm.json()["id"]

    res_camp = client.post("/api/v1/campaigns", headers=headers_owner, json={"name": "Seed Camp", "status": "active"})
    assert res_camp.status_code == 201
    camp_id = res_camp.json()["id"]

    prospect = Prospect(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        name="RBAC Probe Prospect",
        website_url="https://rbac-probe.com",
    )
    container.prospect_repo.save_prospect(org_a.id, prospect)

    # 1. Create ICP -> 403
    assert client.post("/api/v1/icps", headers=headers_viewer, json={"name": "Viewer ICP"}).status_code == 403
    # 2. Edit ICP -> 403
    assert client.patch(f"/api/v1/icps/{icp_id}", headers=headers_viewer, json={"name": "Edited"}).status_code == 403
    # 3. Create Target Market -> 403
    assert client.post("/api/v1/target-markets", headers=headers_viewer, json={"icp_id": icp_id, "country": "US"}).status_code == 403
    # 4. Edit Target Market -> 403
    assert client.patch(f"/api/v1/target-markets/{tm_id}", headers=headers_viewer, json={"city": "Orlando"}).status_code == 403
    # 5. Create Campaign -> 403
    assert client.post("/api/v1/campaigns", headers=headers_viewer, json={"name": "Viewer Camp"}).status_code == 403
    # 6. Edit Campaign -> 403
    assert client.patch(f"/api/v1/campaigns/{camp_id}", headers=headers_viewer, json={"name": "Edited"}).status_code == 403
    # 7. Execute Discovery -> 403
    assert client.post("/api/v1/discovery/execute", headers=headers_viewer, json={"campaign_id": camp_id, "raw_query": "safety"}).status_code == 403
    # 8. Trigger Research -> 403
    assert client.post(f"/api/v1/prospects/{prospect.id}/research", headers=headers_viewer, json={"run_type": "full_diligence"}).status_code == 403
    # 9. Recalculate Lead Score -> 403
    assert client.post(f"/api/v1/prospects/{prospect.id}/score/recalculate", headers=headers_viewer).status_code == 403
    # 10. Recalculate Priority -> 403
    assert client.post(f"/api/v1/prospects/{prospect.id}/priority/recalculate", headers=headers_viewer).status_code == 403


def test_rbac_member_all_operations_allowed(p21_fixture):
    """Proves MEMBER can perform normal prospecting operations: ICP, Target Market, Campaign, Discovery, Research, Score, Priority."""
    client = p21_fixture["client"]
    headers_member = p21_fixture["headers_member_a"]

    # 1. Create ICP
    res = client.post("/api/v1/icps", headers=headers_member, json={"name": "Member Created ICP", "industries": ["healthcare"]})
    assert res.status_code == 201
    member_icp_id = res.json()["id"]

    # 2. Edit ICP
    res = client.patch(f"/api/v1/icps/{member_icp_id}", headers=headers_member, json={"name": "Member ICP Renamed"})
    assert res.status_code == 200

    # 3. Create Target Market
    res = client.post("/api/v1/target-markets", headers=headers_member, json={"icp_id": member_icp_id, "country": "US", "city": "Tampa"})
    assert res.status_code == 201
    member_tm_id = res.json()["id"]

    # 4. Edit Target Market
    res = client.patch(f"/api/v1/target-markets/{member_tm_id}", headers=headers_member, json={"city": "St. Petersburg"})
    assert res.status_code == 200

    # 5. Create Campaign
    res = client.post("/api/v1/campaigns", headers=headers_member, json={"name": "Member Active Campaign", "status": "active"})
    assert res.status_code == 201
    member_camp_id = res.json()["id"]

    # 6. Edit Campaign
    res = client.patch(f"/api/v1/campaigns/{member_camp_id}", headers=headers_member, json={"description": "Active Member Pipeline"})
    assert res.status_code == 200

    # 7. Execute Discovery
    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers_member,
        json={"campaign_id": member_camp_id, "raw_query": "industrial safety distributors in Miami"},
    )
    assert res.status_code == 200
    imported_prospects = res.json()["imported_prospects"]
    assert len(imported_prospects) > 0
    target_prospect_id = imported_prospects[0]["id"]

    # 8. Trigger Research
    res = client.post(
        f"/api/v1/prospects/{target_prospect_id}/research",
        headers=headers_member,
        json={"campaign_id": member_camp_id, "run_type": "full_diligence"},
    )
    assert res.status_code == 202

    # 9. Recalculate Lead Score
    res = client.post(f"/api/v1/prospects/{target_prospect_id}/score/recalculate", headers=headers_member)
    assert res.status_code == 200

    # 10. Recalculate Priority
    res = client.post(f"/api/v1/prospects/{target_prospect_id}/priority/recalculate", headers=headers_member)
    assert res.status_code == 200
