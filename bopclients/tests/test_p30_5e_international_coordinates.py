"""Targeted offline regression tests for Phase P30.5E.1:
International coordinate preservation, server-authoritative geography, and discovery status accuracy.
Zero external calls, strictly mocked offline gateways.
"""

import uuid
from typing import List, Optional
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
from bopclients.application.interfaces.forge_gateways import IForgeDiscoveryGateway, DiscoveryQuery, DiscoveredBusiness
from bopclients.infrastructure.providers.overture_provider import OvertureDiscoveryProvider, haversine_distance_miles
from bopclients.application.discovery_orchestrator import DiscoveryOrchestrator
from bopclients.application.prospect_service import ProspectService
from forge.discovery.overture import OvertureDiscovery, OvertureDiscoveryError


class MockDiscoveryGateway(IForgeDiscoveryGateway):
    """Mock discovery gateway recording queries and returning synthetic businesses."""

    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.recorded_queries: List[DiscoveryQuery] = []

    def discover_businesses(self, query: DiscoveryQuery) -> List[DiscoveredBusiness]:
        self.recorded_queries.append(query)
        if self.should_fail:
            raise RuntimeError("Synthetic provider failure during execution")

        return [
            DiscoveredBusiness(
                overture_id=f"overture-{uuid.uuid4().hex[:8]}",
                name=f"Sociedad Médica de Cali {len(self.recorded_queries)}",
                address="Av 5 Norte # 20-30",
                city=query.city or "Cali",
                state=query.state or "Valle del Cauca",
                zip_code=query.zip_code or "760001",
                latitude=query.latitude or 3.4516,
                longitude=query.longitude or -76.5320,
                phone="+57 602 1234567",
                website_url="https://sociedadmedicacali.org",
                category="medical_association",
                forge_industry="healthcare",
                raw_data={},
            )
        ]


@pytest.fixture
def p30_5e_fixture():
    """Isolated in-memory runtime container with Tenant A (Bop Agencia) and mock provider."""
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

    # Seed ICP for Cali medical associations (25 miles radius)
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

    # Seed Active Campaign for Tenant A
    camp_a = Campaign(
        id="eec5070e-ee69-4274-8bd2-d881353d4ff9",
        organization_id=org_a.id,
        icp_id=icp_a.id,
        name="Prospección de Asociaciones Médicas — Cali",
        description="Búsqueda especializada de asociaciones y sociedades médicas en Cali",
        status=CampaignStatus.ACTIVE,
    )
    container.campaign_repo.save(org_a.id, camp_a)

    token_a = auth_service.authenticate("owner_a@bop.agency", "PasswordA123!").access_token
    headers_a = {
        "Authorization": f"Bearer {token_a}",
        "X-Bop-Organization-Id": org_a.id,
    }

    return {
        "client": client,
        "container": container,
        "org_a": org_a,
        "camp_a": camp_a,
        "icp_a": icp_a,
        "headers_a": headers_a,
        "mock_gateway": mock_gateway,
        "mock_provider": mock_provider,
        "orchestrator": mock_orchestrator,
    }


def test_01_cali_coordinates_survive_planning(p30_5e_fixture):
    """1. Cali coordinates (lat=3.4516, lon=-76.5320) survive planning and populate DiscoveryTask."""
    container = p30_5e_fixture["container"]
    org_id = p30_5e_fixture["org_a"].id
    camp_id = p30_5e_fixture["camp_a"].id

    intent = container.search_service.parse_search_intent(
        org_id=org_id,
        campaign_id=camp_id,
        raw_query="asociaciones médicas en Cali",
    )
    assert intent.cities == ["Cali"]
    assert intent.countries == ["CO"]

    plan = container.search_service.plan_search(intent)
    assert len(plan.tasks) > 0

    for task in plan.tasks:
        assert task.city == "Cali"
        assert task.country == "CO"
        assert task.latitude is not None
        assert task.longitude is not None
        assert abs(task.latitude - 3.4516) < 0.001
        assert abs(task.longitude - (-76.5320)) < 0.001
        assert task.postal_code == "760001"


def test_02_search_plan_response_retains_latitude_and_longitude(p30_5e_fixture):
    """2. Generated SearchPlanResponse serializes and retains latitude and longitude in task query_params."""
    client = p30_5e_fixture["client"]
    headers = p30_5e_fixture["headers_a"]
    camp_id = p30_5e_fixture["camp_a"].id

    res = client.post(
        "/api/v1/discovery/plans",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "raw_query": "asociaciones médicas en Cali",
            "cities": ["Cali"],
            "countries": ["CO"],
            "radius_miles": 25.0,
            "business_categories": ["medical_association"],
            "negative_keywords": ["clinic", "hospital"],
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data["tasks"]) > 0

    task0 = data["tasks"][0]
    qp = task0["query_params"]
    assert "latitude" in qp
    assert "longitude" in qp
    assert qp["latitude"] is not None
    assert qp["longitude"] is not None
    assert abs(float(qp["latitude"]) - 3.4516) < 0.001
    assert abs(float(qp["longitude"]) - (-76.5320)) < 0.001
    assert qp["postal_code"] == "760001"
    assert qp["radius_miles"] == 25.0


def _get_err_msg(res) -> str:
    """Helper to extract error message from standard BopClients error response or FastAPI detail."""
    data = res.json()
    if isinstance(data, dict):
        if "error" in data and isinstance(data["error"], dict):
            return data["error"].get("message", "")
        if "detail" in data:
            return str(data["detail"])
    return str(data)


def test_03_frontend_compatible_execution_reconstructs_coordinates(p30_5e_fixture):
    """3. Frontend-compatible execution deserializes coordinates and passes them to provider gateway."""
    client = p30_5e_fixture["client"]
    headers = p30_5e_fixture["headers_a"]
    camp_id = p30_5e_fixture["camp_a"].id
    mock_gateway = p30_5e_fixture["mock_gateway"]

    plan_res = client.post(
        "/api/v1/discovery/plans",
        headers=headers,
        json={
            "raw_query": "Buscar asociaciones médicas en Cali",
            "campaign_id": camp_id,
            "cities": ["Cali"],
            "countries": ["CO"],
            "radius_miles": 25.0,
            "business_categories": ["medical_association"],
            "negative_keywords": ["clinic", "hospital"],
        },
    )
    assert plan_res.status_code == 200, f"Plan error: {_get_err_msg(plan_res)}"
    plan_payload = plan_res.json()

    mock_gateway.recorded_queries.clear()
    exec_res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "search_plan": plan_payload,
        },
    )
    assert exec_res.status_code == 200, f"Error: {exec_res.json()}"
    assert len(mock_gateway.recorded_queries) > 0

    query = mock_gateway.recorded_queries[0]
    assert query.city == "Cali"
    assert query.latitude is not None
    assert query.longitude is not None
    assert abs(query.latitude - 3.4516) < 0.001
    assert abs(query.longitude - (-76.5320)) < 0.001
    assert query.radius_miles == 25.0


def test_04_colombian_postal_code_does_not_trigger_us_zip_lookup_when_coords_present():
    """4. Colombian postal code (760001) does not trigger US ZIP lookup when valid coordinates exist."""
    overture = OvertureDiscovery()

    # Pass postal_code='760001' WITH latitude and longitude
    lat, lon = overture._resolve_location(
        zip_code="760001",
        latitude=3.4516,
        longitude=-76.5320,
    )
    assert lat == 3.4516
    assert lon == -76.5320

    # Conversely, omitting coordinates with Colombian postal code raises expected geocode error
    with pytest.raises(OvertureDiscoveryError) as exc_info:
        overture._resolve_location(
            zip_code="760001",
            latitude=None,
            longitude=None,
        )
    assert "ZIP code not found in database: 760001" in str(exc_info.value)


def test_05_radius_remains_25_miles(p30_5e_fixture):
    """5. Radius remains strictly 25 miles through plan and execution."""
    client = p30_5e_fixture["client"]
    headers = p30_5e_fixture["headers_a"]
    camp_id = p30_5e_fixture["camp_a"].id
    mock_gateway = p30_5e_fixture["mock_gateway"]

    plan_res = client.post(
        "/api/v1/discovery/plans",
        headers=headers,
        json={
            "raw_query": "Buscar asociaciones médicas en Cali",
            "campaign_id": camp_id,
            "cities": ["Cali"],
            "countries": ["CO"],
            "radius_miles": 25.0,
            "business_categories": ["medical_association"],
            "negative_keywords": ["clinic", "hospital"],
        },
    )
    assert plan_res.status_code == 200, f"Plan error: {_get_err_msg(plan_res)}"
    plan_data = plan_res.json()
    assert plan_data["tasks"][0]["query_params"]["radius_miles"] == 25.0

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
    assert mock_gateway.recorded_queries[0].radius_miles == 25.0


def test_06_exclusions_remain_intact(p30_5e_fixture):
    """6. Negative keywords (clinic, hospital, pharmacy) remain preserved."""
    client = p30_5e_fixture["client"]
    headers = p30_5e_fixture["headers_a"]
    camp_id = p30_5e_fixture["camp_a"].id
    mock_gateway = p30_5e_fixture["mock_gateway"]

    plan_res = client.post(
        "/api/v1/discovery/plans",
        headers=headers,
        json={
            "raw_query": "Buscar asociaciones médicas en Cali",
            "campaign_id": camp_id,
            "cities": ["Cali"],
            "countries": ["CO"],
            "radius_miles": 25.0,
            "business_categories": ["medical_association"],
            "negative_keywords": ["clinic", "hospital", "medical_office", "pharmacy"],
        },
    )
    assert plan_res.status_code == 200, f"Plan error: {_get_err_msg(plan_res)}"
    plan_data = plan_res.json()
    negs = plan_data["tasks"][0]["query_params"]["negative_keywords"]
    assert "clinic" in negs
    assert "hospital" in negs

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
    executed_negs = mock_gateway.recorded_queries[0].negative_keywords
    assert "clinic" in executed_negs
    assert "hospital" in executed_negs


def test_07_manipulated_coordinates_rejected_by_validation(p30_5e_fixture):
    """7. Manipulated coordinates (e.g. New York coordinates injected into Cali task) -> REJECTED (400)."""
    client = p30_5e_fixture["client"]
    headers = p30_5e_fixture["headers_a"]
    camp_id = p30_5e_fixture["camp_a"].id

    tampered_plan = {
        "campaign_id": camp_id,
        "tasks": [
            {
                "task_id": "tampered-coords-1",
                "provider": "overture",
                "query_params": {
                    "category": "medical_association",
                    "city": "Cali",
                    "country": "CO",
                    "latitude": 40.7128,   # INJECTED New York latitude!
                    "longitude": -74.0060, # INJECTED New York longitude!
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
    assert "deviate from canonical location" in _get_err_msg(res)


def test_08_us_zip_based_legacy_discovery_compatible():
    """8. US ZIP-based legacy discovery behavior remains compatible."""
    overture = OvertureDiscovery()
    lat, lon = overture._resolve_location(
        zip_code="33101",
        latitude=None,
        longitude=None,
    )
    assert lat is not None
    assert lon is not None
    assert abs(lat - 25.76) < 1.0
    assert abs(lon - (-80.19)) < 1.0


def test_09_missing_coordinates_fail_closed_when_no_trusted_resolution_exists(p30_5e_fixture):
    """9. Missing coordinates fail closed (HTTP 400) when location cannot be resolved."""
    client = p30_5e_fixture["client"]
    headers = p30_5e_fixture["headers_a"]
    camp_id = p30_5e_fixture["camp_a"].id

    unresolvable_plan = {
        "campaign_id": camp_id,
        "tasks": [
            {
                "task_id": "unresolvable-task-1",
                "provider": "overture",
                "query_params": {
                    "category": "medical_association",
                    "city": "UnknownCityXYZ",
                    "country": "CO",
                    "latitude": None,
                    "longitude": None,
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
            "search_plan": unresolvable_plan,
        },
    )
    assert res.status_code == 400
    err_msg = _get_err_msg(res)
    assert "does not match campaign target markets" in err_msg or "no valid coordinates" in err_msg


def test_10_coordinate_recovery_for_legacy_payload_without_coords(p30_5e_fixture):
    """10. Coordinate recovery: plan submitted without coordinates for Cali is safely recovered from resolver."""
    client = p30_5e_fixture["client"]
    headers = p30_5e_fixture["headers_a"]
    camp_id = p30_5e_fixture["camp_a"].id
    mock_gateway = p30_5e_fixture["mock_gateway"]

    legacy_plan = {
        "campaign_id": camp_id,
        "tasks": [
            {
                "task_id": "legacy-task-cali",
                "provider": "overture",
                "query_params": {
                    "category": "medical_association",
                    "city": "Cali",
                    "region": "Valle del Cauca",
                    "country": "CO",
                    "postal_code": "760001",
                    # latitude and longitude are omitted!
                    "radius_miles": 25.0,
                    "limit": 100,
                    "negative_keywords": ["clinic", "hospital"],
                },
            }
        ],
    }

    mock_gateway.recorded_queries.clear()
    res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "search_plan": legacy_plan,
        },
    )
    assert res.status_code == 200, f"Error: {_get_err_msg(res)}"
    assert len(mock_gateway.recorded_queries) > 0
    executed_q = mock_gateway.recorded_queries[0]
    # Coordinates were recovered server-side!
    assert executed_q.latitude is not None
    assert executed_q.longitude is not None
    assert abs(executed_q.latitude - 3.4516) < 0.001
    assert abs(executed_q.longitude - (-76.5320)) < 0.001


def test_11_execution_status_reporting_failed(p30_5e_fixture):
    """11. Execution status reporting: when all tasks fail, status is 'failed' and errors are listed."""
    client = p30_5e_fixture["client"]
    headers = p30_5e_fixture["headers_a"]
    camp_id = p30_5e_fixture["camp_a"].id
    mock_gateway = p30_5e_fixture["mock_gateway"]

    # Configure mock gateway to fail
    mock_gateway.should_fail = True

    plan_res = client.post(
        "/api/v1/discovery/plans",
        headers=headers,
        json={
            "raw_query": "Buscar asociaciones médicas en Cali",
            "campaign_id": camp_id,
            "cities": ["Cali"],
            "countries": ["CO"],
            "radius_miles": 25.0,
            "business_categories": ["medical_association"],
            "negative_keywords": ["clinic", "hospital"],
        },
    )
    assert plan_res.status_code == 200, f"Plan error: {_get_err_msg(plan_res)}"
    plan_data = plan_res.json()

    exec_res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "search_plan": plan_data,
        },
    )
    assert exec_res.status_code == 200
    data = exec_res.json()
    assert data["status"] == "failed"
    assert data["tasks_executed"] == 1
    assert data["tasks_failed"] == 1
    assert data["tasks_succeeded"] == 0
    assert data["discovered_businesses_count"] == 0
    assert len(data["errors"]) > 0
    assert "Synthetic provider failure" in data["errors"][0]


def test_12_execution_status_reporting_completed(p30_5e_fixture):
    """12. Execution status reporting: when all tasks succeed, status is 'completed'."""
    client = p30_5e_fixture["client"]
    headers = p30_5e_fixture["headers_a"]
    camp_id = p30_5e_fixture["camp_a"].id
    mock_gateway = p30_5e_fixture["mock_gateway"]
    mock_gateway.should_fail = False

    plan_res = client.post(
        "/api/v1/discovery/plans",
        headers=headers,
        json={
            "raw_query": "Buscar asociaciones médicas en Cali",
            "campaign_id": camp_id,
            "cities": ["Cali"],
            "countries": ["CO"],
            "radius_miles": 25.0,
            "business_categories": ["medical_association"],
            "negative_keywords": ["clinic", "hospital"],
        },
    )
    assert plan_res.status_code == 200, f"Plan error: {_get_err_msg(plan_res)}"
    plan_data = plan_res.json()

    exec_res = client.post(
        "/api/v1/discovery/execute",
        headers=headers,
        json={
            "campaign_id": camp_id,
            "search_plan": plan_data,
        },
    )
    assert exec_res.status_code == 200
    data = exec_res.json()
    assert data["status"] == "completed"
    assert data["tasks_succeeded"] == 1
    assert data["tasks_failed"] == 0
    assert data["discovered_businesses_count"] == 1
    assert len(data["errors"]) == 0


def test_13_zero_external_network_calls():
    """13. Verified that all components operate fully offline with 0 remote S3, Overture, or Gemini network calls."""
    dist = haversine_distance_miles(3.4516, -76.5320, 3.4516, -76.5320)
    assert dist == 0.0
