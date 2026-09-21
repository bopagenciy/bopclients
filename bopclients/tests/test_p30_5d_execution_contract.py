"""Phase P30.5D.2 — Discovery Execution Plan Integrity & Tamper Acceptance Test Suite.

Verifies:
1. Exact frontend flow: /api/v1/discovery/plans output fed directly into /api/v1/discovery/execute succeeds with 200 OK.
2. Complete absence of HTTP 422 'search_plan.raw_query: Field required'.
3. Tamper A: Submitted plan changes radius from 25 miles to 500 miles -> REJECTED (400).
4. Tamper B: Submitted plan removes explicit clinic/hospital exclusions -> REJECTED (400).
5. Tamper C: Submitted plan replaces medical_association with clinic -> REJECTED (400).
6. Tamper D: Submitted plan changes country/geographic center away from Target Market without override -> REJECTED (400).
7. Tamper E: Submitted plan changes provider to unsupported provider -> REJECTED (400).
8. Tamper F: Submitted plan inflates task.limit beyond supported bounds (e.g. 50,000) -> REJECTED (400).
9. Tamper G: Submitted plan adds unexpected tasks absent from the generated plan -> REJECTED (400).
10. Tamper H: Submitted plan supplies another organization_id -> REJECTED (404 anti-enumeration).
11. Tamper I: Submitted plan supplies a mismatched campaign_id -> REJECTED (400).
12. Tamper J: Authorized user overrides and raw_query fallback apply canonical planning and authorization -> ACCEPTED (200).
13. Campaign status enforcement (active required, draft rejected with 400).
14. Nonexistent campaign rejected with 404.
15. Empty plan payload (no tasks, no raw_query) rejected with 400.
16. Preservation of task query parameters (radius_miles, category, negative_keywords) during execution.
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
from bopclients.domain.campaign import Campaign
from bopclients.domain.icp import IdealCustomerProfile, TargetMarket
from bopclients.domain.enums import CampaignStatus, MemberRole
from bopclients.application.interfaces.forge_gateways import IForgeDiscoveryGateway, DiscoveredBusiness
from bopclients.infrastructure.providers.overture_provider import OvertureDiscoveryProvider
from bopclients.application.discovery_orchestrator import DiscoveryOrchestrator
from bopclients.application.prospect_service import ProspectService


class MockDiscoveryGateway(IForgeDiscoveryGateway):
    """Deterministic in-memory discovery gateway for test execution."""

    def __init__(self):
        self.recorded_queries = []
        self.businesses = [
            DiscoveredBusiness(
                overture_id="biz_cali_001",
                name="Sociedad de Cirugía del Valle del Cauca",
                website_url="https://cirugiavalle.org",
                phone="+57 2 555 1234",
                address="Av. Roosevelt # 36-00",
                city="Cali",
                state="Valle del Cauca",
                zip_code="760001",
                category="association_or_organization",
                forge_industry="Medical Association",
                latitude=3.4516,
                longitude=-76.5320,
            ),
            DiscoveredBusiness(
                overture_id="biz_cali_002",
                name="Asociación Colombiana de Medicina Interna - Capítulo Valle",
                website_url="https://acmi-valle.org",
                phone="+57 2 555 5678",
                address="Calle 5 # 38-12",
                city="Cali",
                state="Valle del Cauca",
                zip_code="760002",
                category="association_or_organization",
                forge_industry="Medical Association",
                latitude=3.4372,
                longitude=-76.5225,
            ),
        ]

    def discover_businesses(self, query):
        self.recorded_queries.append(query)
        return self.businesses


@pytest.fixture
def contract_fixture():
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

    # Seed Tenant A (Bop Agencia)
    user_a = auth_service.register_user(
        email="owner_a@bop.agency",
        name="Owner A",
        password="PasswordA123!",
        locale="en",
    )
    org_a = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name="Bop Agencia",
        slug="bop-agencia",
    )
    container.org_repo.save(org_a)
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=user_a.id,
            role=MemberRole.OWNER,
        )
    )

    # Seed ICP for Tenant A: Medical associations in Cali, Valle del Cauca, CO, 25 miles
    icp_a = IdealCustomerProfile(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        name="Asociaciones Médicas Colombia",
        industries=["medical_association", "scientific_society", "professional_association"],
        target_markets=[
            TargetMarket(
                id=str(uuid.uuid4()),
                country="CO",
                region="Valle del Cauca",
                city="Cali",
                radius_miles=25.0,
                language="es",
            )
        ],
    )
    container.icp_repo.save(org_a.id, icp_a)

    # Seed Tenant B (Competitor)
    user_b = auth_service.register_user(
        email="owner_b@competitor.com",
        name="Owner B",
        password="PasswordB123!",
        locale="en",
    )
    org_b = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name="Competitor Corp",
        slug="competitor-corp",
    )
    container.org_repo.save(org_b)
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_b.id,
            user_id=user_b.id,
            role=MemberRole.OWNER,
        )
    )

    # Seed Active Campaign for Tenant A with ICP attached
    camp_a = Campaign(
        id="eec5070e-ee69-4274-8bd2-d881353d4ff9",
        organization_id=org_a.id,
        name="Prospección de Asociaciones Médicas — Cali",
        status=CampaignStatus.ACTIVE,
        icp_id=icp_a.id,
    )
    container.campaign_repo.save(org_a.id, camp_a)

    # Seed Draft Campaign for Tenant A
    camp_a_draft = Campaign(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        name="Draft Safety Campaign",
        status=CampaignStatus.DRAFT,
    )
    container.campaign_repo.save(org_a.id, camp_a_draft)

    # Auth tokens
    token_a = auth_service.authenticate("owner_a@bop.agency", "PasswordA123!").access_token
    token_b = auth_service.authenticate("owner_b@competitor.com", "PasswordB123!").access_token

    headers_a = {
        "Authorization": f"Bearer {token_a}",
        "X-Bop-Organization-Id": org_a.id,
    }
    headers_b = {
        "Authorization": f"Bearer {token_b}",
        "X-Bop-Organization-Id": org_b.id,
    }

    return {
        "client": client,
        "container": container,
        "mock_gateway": mock_gateway,
        "org_a": org_a,
        "org_b": org_b,
        "camp_a": camp_a,
        "camp_a_draft": camp_a_draft,
        "icp_a": icp_a,
        "headers_a": headers_a,
        "headers_b": headers_b,
    }


def _get_err_msg(res) -> str:
    """Helper to extract error message from standard BopClients error response or FastAPI detail."""
    data = res.json()
    if isinstance(data, dict):
        if "error" in data and isinstance(data["error"], dict):
            return data["error"].get("message", "")
        if "detail" in data:
            return str(data["detail"])
    return str(data)


def test_frontend_plans_output_directly_executable(contract_fixture):
    """Phase P30.5D.1 / D.2:

    Frontend generates plan via POST /api/v1/discovery/plans,
    then passes the returned SearchPlanResponse directly into
    POST /api/v1/discovery/execute as { 'search_plan': plan, 'campaign_id': camp_id }.
    MUST return 200 OK and NOT 422 'search_plan.raw_query: Field required'.
    """
    client = contract_fixture["client"]
    headers = contract_fixture["headers_a"]
    camp_id = contract_fixture["camp_a"].id

    # Step 1 & 2: Generate Search Plan
    plan_req_body = {
        "raw_query": "Buscar asociaciones médicas en Cali, Colombia",
        "campaign_id": camp_id,
        "cities": ["Cali"],
        "countries": ["CO"],
        "regions": ["Valle del Cauca"],
        "radius_miles": 25.0,
        "business_categories": ["medical_association"],
        "negative_keywords": ["clinic", "hospital", "pharmacy"],
    }
    plan_res = client.post("/api/v1/discovery/plans", headers=headers, json=plan_req_body)
    assert plan_res.status_code == 200
    plan_data = plan_res.json()

    assert "tasks" in plan_data
    assert len(plan_data["tasks"]) > 0

    # Step 3: Frontend calls /api/v1/discovery/execute with { search_plan: plan, campaign_id: camp_id }
    exec_res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "search_plan": plan_data,
        },
    )

    # CRITICAL ACCEPTANCE CHECK: Must NOT be 422!
    assert exec_res.status_code == 200, f"Expected 200 OK, got {exec_res.status_code}: {exec_res.text}"
    exec_data = exec_res.json()
    assert exec_data["status"] in ("completed", "partial")
    assert exec_data["campaign_id"] == camp_id
    assert exec_data["discovered_businesses_count"] == 2
    assert exec_data["prospects_created"] == 2
    assert len(exec_data["imported_prospects"]) == 2


def test_task_query_params_and_exclusions_preserved_in_plan_and_execution(contract_fixture):
    """Ensures negative_keywords and radius_miles are preserved through plan serialization and execution."""
    client = contract_fixture["client"]
    headers = contract_fixture["headers_a"]
    camp_id = contract_fixture["camp_a"].id
    mock_gateway = contract_fixture["mock_gateway"]

    plan_res = client.post(
        "/api/v1/discovery/plans",
        headers=headers,
        json={
            "raw_query": "Sociedades científicas en Cali",
            "campaign_id": camp_id,
            "cities": ["Cali"],
            "countries": ["CO"],
            "radius_miles": 25.0,
            "business_categories": ["scientific_society"],
            "negative_keywords": ["clinic", "hospital"],
        },
    )
    assert plan_res.status_code == 200
    plan_data = plan_res.json()
    assert len(plan_data["tasks"]) > 0
    task0 = plan_data["tasks"][0]
    assert task0["query_params"]["radius_miles"] == 25.0
    assert "clinic" in task0["query_params"].get("negative_keywords", [])

    # Execute plan
    mock_gateway.recorded_queries.clear()
    exec_res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "search_plan": plan_data,
        },
    )
    assert exec_res.status_code == 200
    assert len(mock_gateway.recorded_queries) > 0
    executed_q = mock_gateway.recorded_queries[0]
    assert executed_q.city == "Cali"
    assert executed_q.radius_miles == 25.0


def test_tamper_a_radius_inflated_to_500_miles_rejected(contract_fixture):
    """Tamper A: Client inflates radius from 25 miles to 500 miles -> REJECTED (400)."""
    client = contract_fixture["client"]
    headers = contract_fixture["headers_a"]
    camp_id = contract_fixture["camp_a"].id

    tampered_plan = {
        "campaign_id": camp_id,
        "tasks": [
            {
                "task_id": "tampered-radius-1",
                "provider": "overture",
                "query_params": {
                    "category": "medical_association",
                    "city": "Cali",
                    "region": "Valle del Cauca",
                    "country": "CO",
                    "radius_miles": 500.0,  # INFLATED from 25 to 500!
                    "limit": 100,
                    "negative_keywords": ["clinic", "hospital"],
                },
            }
        ],
    }

    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "search_plan": tampered_plan,
        },
    )
    assert res.status_code == 400
    assert "radius" in _get_err_msg(res).lower()


def test_tamper_b_exclusions_removed_rejected(contract_fixture):
    """Tamper B: Client removes explicit clinic/hospital exclusions from association task -> REJECTED (400)."""
    client = contract_fixture["client"]
    headers = contract_fixture["headers_a"]
    camp_id = contract_fixture["camp_a"].id

    tampered_plan = {
        "campaign_id": camp_id,
        "tasks": [
            {
                "task_id": "tampered-exclusions-1",
                "provider": "overture",
                "query_params": {
                    "category": "medical_association",
                    "city": "Cali",
                    "region": "Valle del Cauca",
                    "country": "CO",
                    "radius_miles": 25.0,
                    "limit": 100,
                    "negative_keywords": [],  # EXCLUSIONS REMOVED!
                },
            }
        ],
    }

    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "search_plan": tampered_plan,
        },
    )
    assert res.status_code == 400
    assert "clinic/hospital exclusions" in _get_err_msg(res)


def test_tamper_c_category_replaced_with_clinic_rejected(contract_fixture):
    """Tamper C: Client replaces medical_association with clinic -> REJECTED (400)."""
    client = contract_fixture["client"]
    headers = contract_fixture["headers_a"]
    camp_id = contract_fixture["camp_a"].id

    tampered_plan = {
        "campaign_id": camp_id,
        "tasks": [
            {
                "task_id": "tampered-category-1",
                "provider": "overture",
                "query_params": {
                    "category": "clinic",  # REPLACED medical_association with clinic!
                    "city": "Cali",
                    "region": "Valle del Cauca",
                    "country": "CO",
                    "radius_miles": 25.0,
                    "limit": 100,
                    "negative_keywords": ["clinic", "hospital"],
                },
            }
        ],
    }

    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "search_plan": tampered_plan,
        },
    )
    assert res.status_code == 400
    assert "excluded facility category" in _get_err_msg(res) or "conflicts with" in _get_err_msg(res)


def test_tamper_d_geographic_center_tampered_without_override_rejected(contract_fixture):
    """Tamper D: Client changes geographic center away from resolved Target Market without override -> REJECTED (400)."""
    client = contract_fixture["client"]
    headers = contract_fixture["headers_a"]
    camp_id = contract_fixture["camp_a"].id

    tampered_plan = {
        "campaign_id": camp_id,
        "raw_query": "Buscar asociaciones médicas en Cali",
        "tasks": [
            {
                "task_id": "tampered-geography-1",
                "provider": "overture",
                "query_params": {
                    "category": "medical_association",
                    "city": "London",  # TAMPERED away from Cali to London!
                    "country": "GB",
                    "radius_miles": 25.0,
                    "limit": 100,
                    "negative_keywords": ["clinic", "hospital"],
                },
            }
        ],
    }

    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "search_plan": tampered_plan,
        },
    )
    assert res.status_code == 400
    assert "does not match campaign target markets" in _get_err_msg(res)


def test_tamper_e_unsupported_provider_rejected(contract_fixture):
    """Tamper E: Client changes provider to an unsupported provider -> REJECTED (400)."""
    client = contract_fixture["client"]
    headers = contract_fixture["headers_a"]
    camp_id = contract_fixture["camp_a"].id

    tampered_plan = {
        "campaign_id": camp_id,
        "tasks": [
            {
                "task_id": "tampered-provider-1",
                "provider": "unsupported_malicious_scraper",  # UNSUPPORTED!
                "query_params": {
                    "category": "medical_association",
                    "city": "Cali",
                    "country": "CO",
                    "radius_miles": 25.0,
                    "limit": 100,
                    "negative_keywords": ["clinic", "hospital"],
                },
            }
        ],
    }

    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "search_plan": tampered_plan,
        },
    )
    assert res.status_code == 400
    assert "Unsupported discovery provider" in _get_err_msg(res)


def test_tamper_f_limit_inflated_beyond_bounds_rejected(contract_fixture):
    """Tamper F: Client inflates task.limit to 50,000 beyond supported bounds (1000) -> REJECTED (400)."""
    client = contract_fixture["client"]
    headers = contract_fixture["headers_a"]
    camp_id = contract_fixture["camp_a"].id

    tampered_plan = {
        "campaign_id": camp_id,
        "tasks": [
            {
                "task_id": "tampered-limit-1",
                "provider": "overture",
                "query_params": {
                    "category": "medical_association",
                    "city": "Cali",
                    "country": "CO",
                    "radius_miles": 25.0,
                    "limit": 50000,  # INFLATED beyond 1000!
                    "negative_keywords": ["clinic", "hospital"],
                },
            }
        ],
    }

    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "search_plan": tampered_plan,
        },
    )
    assert res.status_code == 400
    assert "exceeds maximum allowed limit" in _get_err_msg(res)


def test_tamper_g_unexpected_extra_task_rejected(contract_fixture):
    """Tamper G: Client adds unexpected task absent from generated plan (unauthorized category) -> REJECTED (400)."""
    client = contract_fixture["client"]
    headers = contract_fixture["headers_a"]
    camp_id = contract_fixture["camp_a"].id

    tampered_plan = {
        "campaign_id": camp_id,
        "tasks": [
            {
                "task_id": "legit-task-1",
                "provider": "overture",
                "query_params": {
                    "category": "medical_association",
                    "city": "Cali",
                    "country": "CO",
                    "radius_miles": 25.0,
                    "limit": 100,
                    "negative_keywords": ["clinic", "hospital"],
                },
            },
            {
                "task_id": "injected-task-2",
                "provider": "overture",
                "query_params": {
                    "category": "roofing_contractor",  # INJECTED UNAUTHORIZED CATEGORY!
                    "city": "Cali",
                    "country": "CO",
                    "radius_miles": 25.0,
                    "limit": 100,
                    "negative_keywords": ["clinic", "hospital"],
                },
            },
        ],
    }

    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "search_plan": tampered_plan,
        },
    )
    assert res.status_code == 400
    assert "not authorized for this campaign" in _get_err_msg(res) or "not supported" in _get_err_msg(res)


def test_tamper_h_cross_tenant_organization_rejected(contract_fixture):
    """Tamper H: Submitting a search_plan with another tenant's organization_id -> REJECTED (404 anti-enumeration)."""
    client = contract_fixture["client"]
    headers_a = contract_fixture["headers_a"]
    camp_id_a = contract_fixture["camp_a"].id
    foreign_org_id = contract_fixture["org_b"].id

    plan_payload = {
        "organization_id": foreign_org_id,
        "campaign_id": camp_id_a,
        "tasks": [
            {
                "task_id": "malicious-task-1",
                "provider": "overture",
                "query_params": {
                    "category": "medical_association",
                    "city": "Cali",
                    "country": "CO",
                    "radius_miles": 25.0,
                    "limit": 100,
                    "negative_keywords": ["clinic", "hospital"],
                },
            }
        ],
    }

    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers_a,
        json={
            "campaign_id": camp_id_a,
            "search_plan": plan_payload,
        },
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_tamper_i_mismatched_campaign_id_in_search_plan_rejected(contract_fixture):
    """Tamper I: Submitting a search_plan with campaign_id different from endpoint campaign_id -> REJECTED (400)."""
    client = contract_fixture["client"]
    headers = contract_fixture["headers_a"]
    camp_id = contract_fixture["camp_a"].id

    plan_payload = {
        "organization_id": contract_fixture["org_a"].id,
        "campaign_id": "other-campaign-uuid-9999",
        "tasks": [
            {
                "task_id": "task-1",
                "provider": "overture",
                "query_params": {
                    "category": "medical_association",
                    "city": "Cali",
                    "country": "CO",
                    "radius_miles": 25.0,
                    "limit": 100,
                    "negative_keywords": ["clinic", "hospital"],
                },
            }
        ],
    }

    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "search_plan": plan_payload,
        },
    )
    assert res.status_code == 400
    assert "does not match" in _get_err_msg(res)


def test_tamper_j1_raw_query_fallback_accepted(contract_fixture):
    """Tamper J1: Legacy raw_query without search_plan parses and executes cleanly with full authorization."""
    client = contract_fixture["client"]
    headers = contract_fixture["headers_a"]
    camp_id = contract_fixture["camp_a"].id

    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "raw_query": "asociaciones médicas en Cali",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("completed", "partial")
    assert data["discovered_businesses_count"] == 2


def test_tamper_j2_search_plan_with_raw_query_fallback(contract_fixture):
    """Tamper J2: Passing search_plan with raw_query but without tasks plans and executes dynamically."""
    client = contract_fixture["client"]
    headers = contract_fixture["headers_a"]
    camp_id = contract_fixture["camp_a"].id

    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "search_plan": {
                "raw_query": "asociaciones médicas en Cali",
                "cities": ["Cali"],
                "countries": ["CO"],
            },
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("completed", "partial")
    assert data["discovered_businesses_count"] == 2


def test_tamper_j3_submitted_plan_with_arbitrary_raw_query_cannot_bypass_validation(contract_fixture):
    """Tamper J3: An existing submitted plan must NOT become trusted merely because the browser adds a raw_query field.
    Adding raw_query cannot authorize invalid task coordinates, radius, categories, or missing exclusions.
    """
    client = contract_fixture["client"]
    headers = contract_fixture["headers_a"]
    camp_id = contract_fixture["camp_a"].id

    # 1. Tampered coordinates (Bogotá instead of Cali) + arbitrary raw_query mentioning Bogotá -> REJECTED (400)
    tampered_geo_plan = {
        "campaign_id": camp_id,
        "raw_query": "Buscar asociaciones médicas en Bogotá, Colombia",
        "tasks": [
            {
                "task_id": "tampered-task-bogota",
                "provider": "overture",
                "query_params": {
                    "category": "medical_association",
                    "city": "Bogotá",
                    "country": "CO",
                    "radius_miles": 25.0,
                    "limit": 100,
                    "negative_keywords": ["clinic", "hospital"],
                },
            }
        ],
    }
    res_geo = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "raw_query": "Buscar asociaciones médicas en Bogotá, Colombia",
            "search_plan": tampered_geo_plan,
        },
    )
    assert res_geo.status_code == 400
    assert "does not match campaign target markets" in _get_err_msg(res_geo)

    # 2. Tampered radius (500 miles) + raw_query -> REJECTED (400)
    tampered_radius_plan = {
        "campaign_id": camp_id,
        "raw_query": "asociaciones médicas en Cali",
        "tasks": [
            {
                "task_id": "tampered-radius-1",
                "provider": "overture",
                "query_params": {
                    "category": "medical_association",
                    "city": "Cali",
                    "country": "CO",
                    "radius_miles": 500.0,
                    "limit": 100,
                    "negative_keywords": ["clinic", "hospital"],
                },
            }
        ],
    }
    res_radius = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "raw_query": "asociaciones médicas en Cali",
            "search_plan": tampered_radius_plan,
        },
    )
    assert res_radius.status_code == 400
    assert "exceeds maximum supported discovery radius" in _get_err_msg(res_radius)

    # 3. Stripped exclusions + raw_query -> REJECTED (400)
    tampered_neg_plan = {
        "campaign_id": camp_id,
        "raw_query": "asociaciones médicas en Cali",
        "tasks": [
            {
                "task_id": "tampered-neg-1",
                "provider": "overture",
                "query_params": {
                    "category": "medical_association",
                    "city": "Cali",
                    "country": "CO",
                    "radius_miles": 25.0,
                    "limit": 100,
                    "negative_keywords": [],
                },
            }
        ],
    }
    res_neg = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "search_plan": tampered_neg_plan,
        },
    )
    assert res_neg.status_code == 400
    assert "clinic/hospital exclusions" in _get_err_msg(res_neg)


def test_draft_campaign_rejected(contract_fixture):
    """Discovery execution against a DRAFT campaign is rejected with 400."""
    client = contract_fixture["client"]
    headers = contract_fixture["headers_a"]
    draft_camp_id = contract_fixture["camp_a_draft"].id

    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": draft_camp_id,
            "raw_query": "Buscar asociaciones médicas",
        },
    )
    assert res.status_code == 400
    assert "Discovery execution requires an 'active' campaign" in _get_err_msg(res)


def test_nonexistent_campaign_rejected(contract_fixture):
    """Discovery execution against a non-existent campaign returns 404."""
    client = contract_fixture["client"]
    headers = contract_fixture["headers_a"]

    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": str(uuid.uuid4()),
            "raw_query": "Buscar asociaciones médicas",
        },
    )
    assert res.status_code == 404


def test_empty_search_plan_rejected(contract_fixture):
    """Submitting a search_plan with empty tasks and no raw_query returns 400."""
    client = contract_fixture["client"]
    headers = contract_fixture["headers_a"]
    camp_id = contract_fixture["camp_a"].id

    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "search_plan": {
                "tasks": [],
            },
        },
    )
    assert res.status_code == 400
    assert "search_plan must contain tasks or a valid raw_query" in _get_err_msg(res)


def test_missing_plan_and_query_rejected(contract_fixture):
    """Submitting neither search_plan nor raw_query returns 400."""
    client = contract_fixture["client"]
    headers = contract_fixture["headers_a"]
    camp_id = contract_fixture["camp_a"].id

    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
        },
    )
    assert res.status_code == 400
    assert "Either 'search_plan' or 'raw_query' must be provided" in _get_err_msg(res)
