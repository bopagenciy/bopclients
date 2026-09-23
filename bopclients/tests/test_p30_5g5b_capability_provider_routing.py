"""Targeted offline tests for Phase P30.5G.5B:
Capability-Based Discovery Provider Routing.

Validates provider selection based on structured ICP, organization type, geographic scope,
and provider capabilities across Scenarios A through O.
Zero external calls, strictly mocked offline gateways.
"""

import uuid
import pytest
from typing import List, Optional, Set, Dict, Any
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
from bopclients.domain.search_intent import SearchIntent
from bopclients.domain.provider_capability import (
    ProviderCapability,
    ProviderCapabilityRegistry,
    SearchGeographicScope,
    get_overture_capability,
    get_web_search_capability,
)
from bopclients.domain.exceptions import DiscoveryExecutionError, TenantAccessError, SearchPlanningError
from bopclients.application.search_planner import DefaultSearchPlanner
from bopclients.application.search_dto import DiscoveryTask, SearchPlan
from bopclients.application.interfaces.forge_gateways import IForgeDiscoveryGateway, DiscoveryQuery, DiscoveredBusiness
from bopclients.infrastructure.location.static_location_resolver import StaticLocationResolver
from bopclients.infrastructure.providers.overture_provider import OvertureDiscoveryProvider
from bopclients.infrastructure.providers.web_search_provider import (
    WebSearchDiscoveryProvider,
    OfflineFixtureWebSearchTransport,
)
from bopclients.application.discovery_orchestrator import DiscoveryOrchestrator
from bopclients.application.prospect_service import ProspectService


class MockDiscoveryGateway(IForgeDiscoveryGateway):
    """Mock discovery gateway recording queries and returning synthetic businesses."""

    def __init__(self):
        self.recorded_queries: List[DiscoveryQuery] = []

    def discover_businesses(self, query: DiscoveryQuery) -> List[DiscoveredBusiness]:
        self.recorded_queries.append(query)
        return [
            DiscoveredBusiness(
                overture_id=f"overture-{uuid.uuid4().hex[:8]}",
                name=f"Sociedad Médica de Cali {len(self.recorded_queries)}",
                address="Av 5 Norte # 20-30",
                city=query.city or "Cali",
                state=query.state or "Valle del Cauca",
                zip_code=getattr(query, "zip_code", None) or "760001",
                latitude=query.latitude or 3.4516,
                longitude=query.longitude or -76.5320,
                category="association_or_organization",
            )
        ]


@pytest.fixture
def p30_5g5b_env():
    """Isolated in-memory test environment for capability-based provider routing tests."""
    db = create_database_connection(":memory:")
    DatabaseMigrator.migrate(db)

    settings = RuntimeSettings(
        environment="test",
        database_url=":memory:",
        auth_signing_key="test_secret_key_32_bytes_minimum_length_required",
        tavily_enabled=False,
    )
    container = build_runtime_container(settings=settings, db=db)
    app = create_bopclients_api_app(container=container)
    client = TestClient(app)

    auth_service = container.auth_service

    # Setup Tenant A
    user_a = auth_service.register_user(
        email="admin_a@tenant-a.com",
        name="Admin A",
        password="PasswordA123!",
        locale="en",
    )
    org_a = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name="Agencia Prospectos A",
        slug="agencia-a",
    )
    container.org_repo.save(org_a)
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=user_a.id,
            role=MemberRole.ADMIN,
        )
    )

    # Setup Tenant B
    user_b = auth_service.register_user(
        email="admin_b@tenant-b.com",
        name="Admin B",
        password="PasswordB123!",
        locale="en",
    )
    org_b = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name="Agencia Prospectos B",
        slug="agencia-b",
    )
    container.org_repo.save(org_b)
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_b.id,
            user_id=user_b.id,
            role=MemberRole.ADMIN,
        )
    )

    token_a = auth_service.authenticate("admin_a@tenant-a.com", "PasswordA123!").access_token
    headers_a = {"Authorization": f"Bearer {token_a}", "X-Bop-Organization-Id": org_a.id}

    token_b = auth_service.authenticate("admin_b@tenant-b.com", "PasswordB123!").access_token
    headers_b = {"Authorization": f"Bearer {token_b}", "X-Bop-Organization-Id": org_b.id}

    # Campaign for Tenant A
    icp_a = IdealCustomerProfile(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        name="Medical Associations ICP",
        industries=["medical_association", "scientific_society"],
        excluded_organization_types=["clinic", "hospital"],
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

    camp_a = Campaign(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        icp_id=icp_a.id,
        name="Camp A - Asociaciones Cali",
        status=CampaignStatus.ACTIVE,
    )
    container.campaign_repo.save(org_a.id, camp_a)

    resolver = StaticLocationResolver()
    planner = DefaultSearchPlanner(location_resolver=resolver)

    return {
        "client": client,
        "container": container,
        "org_a": org_a,
        "org_b": org_b,
        "camp_a": camp_a,
        "icp_a": icp_a,
        "headers_a": headers_a,
        "headers_b": headers_b,
        "resolver": resolver,
        "planner": planner,
    }


def test_scenario_a_medical_associations_in_cali(p30_5g5b_env):
    """Scenario A: Medical associations in Cali route to Overture with coordinates."""
    planner = p30_5g5b_env["planner"]
    intent = SearchIntent(
        organization_id=p30_5g5b_env["org_a"].id,
        raw_query="asociaciones médicas en Cali",
        industries=["medical_association"],
        cities=["Cali"],
        countries=["CO"],
        negative_keywords=["clinic", "hospital"],
    )
    plan = planner.plan(intent)

    assert len(plan.tasks) == 1
    task = plan.tasks[0]
    assert task.provider == "overture"
    assert task.category == "medical_association"
    assert task.city == "Cali"
    assert task.country == "CO"
    assert task.latitude is not None
    assert abs(task.latitude - 3.4516) < 0.001
    assert task.longitude is not None
    assert abs(task.longitude - (-76.5320)) < 0.001
    assert "clinic" in task.negative_keywords


def test_scenario_b_construction_companies_in_florida(p30_5g5b_env):
    """Scenario B: Construction companies in Florida route to Web Search without fabricated coordinates."""
    planner = p30_5g5b_env["planner"]
    intent = SearchIntent(
        organization_id=p30_5g5b_env["org_a"].id,
        raw_query="construction companies in Florida",
        industries=["construction"],
        regions=["FL"],
        countries=["US"],
    )
    plan = planner.plan(intent)

    assert len(plan.tasks) == 1
    task = plan.tasks[0]
    assert task.provider == "web_search"
    assert task.category == "construction"
    assert task.region == "FL"
    assert task.country == "US"
    assert task.latitude is None  # Zero fabricated coordinates
    assert task.longitude is None  # Zero fabricated coordinates
    assert task.postal_code is None
    assert "construction" in task.query.lower()


def test_scenario_c_industrial_distributors_in_new_jersey(p30_5g5b_env):
    """Scenario C: Industrial distributors in NJ route to Web Search without fabricated coordinates."""
    planner = p30_5g5b_env["planner"]
    intent = SearchIntent(
        organization_id=p30_5g5b_env["org_a"].id,
        raw_query="industrial distributors in New Jersey",
        industries=["industrial_distributor"],
        regions=["NJ"],
        countries=["US"],
    )
    plan = planner.plan(intent)

    assert len(plan.tasks) == 1
    task = plan.tasks[0]
    assert task.provider == "web_search"
    assert task.category == "industrial_distributor"
    assert task.region == "NJ"
    assert task.country == "US"
    assert task.latitude is None
    assert task.longitude is None
    assert "industrial distributor" in task.query.lower()


def test_scenario_d_b2b_software_companies_in_colombia(p30_5g5b_env):
    """Scenario D: B2B software companies in Colombia route to Web Search at country level."""
    planner = p30_5g5b_env["planner"]
    intent = SearchIntent(
        organization_id=p30_5g5b_env["org_a"].id,
        raw_query="empresas de software en Colombia",
        industries=["b2b_software"],
        countries=["CO"],
    )
    plan = planner.plan(intent)

    assert len(plan.tasks) == 1
    task = plan.tasks[0]
    assert task.provider == "web_search"
    assert task.category == "b2b_software"
    assert task.country == "CO"
    assert task.city is None
    assert task.latitude is None
    assert task.longitude is None


def test_scenario_e_local_restaurants_with_coordinates(p30_5g5b_env):
    """Scenario E: Local restaurants in Miami with coordinates route to Overture."""
    planner = p30_5g5b_env["planner"]
    intent = SearchIntent(
        organization_id=p30_5g5b_env["org_a"].id,
        raw_query="restaurantes en Miami",
        industries=["restaurant"],
        cities=["Miami"],
        countries=["US"],
    )
    plan = planner.plan(intent)

    assert len(plan.tasks) == 1
    task = plan.tasks[0]
    assert task.provider == "overture"
    assert task.category == "restaurant"
    assert task.city == "Miami"
    assert task.country == "US"
    assert task.latitude is not None
    assert abs(task.latitude - 25.7617) < 0.001
    assert task.longitude is not None
    assert abs(task.longitude - (-80.1918)) < 0.001


def test_scenario_f_unsupported_overture_category(p30_5g5b_env):
    """Scenario F: Category unsupported by Overture is never assigned to Overture."""
    resolver = p30_5g5b_env["resolver"]
    # Capability registry with only Overture enabled
    registry = ProviderCapabilityRegistry({
        "overture": get_overture_capability(enabled=True),
    })
    planner = DefaultSearchPlanner(location_resolver=resolver, capability_registry=registry)

    intent = SearchIntent(
        organization_id=p30_5g5b_env["org_a"].id,
        raw_query="crypto arbitrage firms in Miami",
        industries=["crypto_arbitrage_firm"],
        cities=["Miami"],
        countries=["US"],
    )
    plan = planner.plan(intent)

    # Overture is not assigned merely because it is enabled
    assert len(plan.tasks) == 0
    assert any(w.code == "UNSUPPORTED_CATEGORY" for w in plan.warnings)


def test_scenario_g_disabled_web_provider(p30_5g5b_env):
    """Scenario G: Disabled web provider emits warning during planning and fails closed during execution."""
    resolver = p30_5g5b_env["resolver"]
    registry = ProviderCapabilityRegistry({
        "overture": get_overture_capability(enabled=True),
        "web_search": get_web_search_capability(enabled=False),
    })
    planner = DefaultSearchPlanner(location_resolver=resolver, capability_registry=registry)

    intent = SearchIntent(
        organization_id=p30_5g5b_env["org_a"].id,
        raw_query="construction companies in Florida",
        industries=["construction"],
        regions=["FL"],
        countries=["US"],
    )
    plan = planner.plan(intent)

    assert len(plan.tasks) == 1
    assert plan.tasks[0].provider == "web_search"
    assert any(w.code == "PROVIDER_DISABLED" for w in plan.warnings)

    # Execution fails closed
    provider = WebSearchDiscoveryProvider(enabled=False)
    with pytest.raises(DiscoveryExecutionError) as exc_info:
        provider.discover(plan.tasks[0])
    assert "disabled by default" in str(exc_info.value).lower()


def test_scenario_h_no_permitted_source(p30_5g5b_env):
    """Scenario H: When no discovery provider can satisfy criteria, emit explicit diagnostic and 0 tasks."""
    resolver = p30_5g5b_env["resolver"]
    empty_registry = ProviderCapabilityRegistry({})
    empty_registry._capabilities.clear()
    planner = DefaultSearchPlanner(location_resolver=resolver, capability_registry=empty_registry)

    intent = SearchIntent(
        organization_id=p30_5g5b_env["org_a"].id,
        raw_query="industrial distributors in New Jersey",
        industries=["industrial_distributor"],
        regions=["NJ"],
        countries=["US"],
    )
    plan = planner.plan(intent)

    assert len(plan.tasks) == 0
    assert any(w.code == "NO_SUITABLE_PROVIDER" for w in plan.warnings)


def test_scenario_i_unauthorized_provider_injection(p30_5g5b_env):
    """Scenario I: Anti-tamper validation rejects unauthorized provider injection in discovery plan."""
    client = p30_5g5b_env["client"]
    headers = p30_5g5b_env["headers_a"]
    camp_id = p30_5g5b_env["camp_a"].id

    payload = {
        "campaign_id": camp_id,
        "search_plan": {
            "tasks": [
                {
                    "task_id": str(uuid.uuid4()),
                    "provider": "google_maps_scrape",
                    "priority": 1,
                    "query_params": {
                        "category": "medical_association",
                        "city": "Cali",
                        "country": "CO",
                        "limit": 50,
                    },
                }
            ]
        },
    }
    resp = client.post("/api/v1/discovery/execute", json=payload, headers=headers)
    assert resp.status_code == 400
    assert "unsupported discovery provider" in resp.text.lower()


def test_scenario_j_cross_tenant_authorization(p30_5g5b_env):
    """Scenario J: Cross-tenant authorization is strictly blocked for both execution and preview."""
    client = p30_5g5b_env["client"]
    headers_b = p30_5g5b_env["headers_b"]
    camp_a_id = p30_5g5b_env["camp_a"].id  # Belongs to Tenant A

    # Tenant B tries to execute Tenant A's campaign
    payload = {
        "campaign_id": camp_a_id,
        "raw_query": "asociaciones médicas en Cali",
    }
    resp = client.post("/api/v1/discovery/execute", json=payload, headers=headers_b)
    assert resp.status_code in (403, 404)

    # Web search unauthorized tenant check
    web_prov = WebSearchDiscoveryProvider(
        enabled=True,
        authorized_tenants={p30_5g5b_env["org_a"].id},
    )
    task = DiscoveryTask(
        provider="web_search",
        category="construction",
        country="US",
        region="FL",
        metadata={"organization_id": p30_5g5b_env["org_b"].id},
    )
    with pytest.raises(TenantAccessError):
        web_prov.discover(task)


def test_scenario_k_explicit_negative_filters(p30_5g5b_env):
    """Scenario K: Explicit negative filters from ICP and caller are preserved in planned tasks."""
    planner = p30_5g5b_env["planner"]
    intent = SearchIntent(
        organization_id=p30_5g5b_env["org_a"].id,
        raw_query="asociaciones médicas en Cali sin clínicas ni hospitales",
        industries=["medical_association"],
        cities=["Cali"],
        countries=["CO"],
        negative_keywords=["clinic", "hospital", "consultorio", "ips", "eps"],
    )
    plan = planner.plan(intent)

    assert len(plan.tasks) > 0
    for task in plan.tasks:
        for nk in ["clinic", "hospital", "consultorio", "ips", "eps"]:
            assert nk in task.negative_keywords


def test_scenario_l_raw_query_campaign_fallback(p30_5g5b_env):
    """Scenario L: Reconstructing empty-task search plan restores campaign ICP and routes based on capabilities."""
    container = p30_5g5b_env["container"]
    org_id = p30_5g5b_env["org_a"].id
    camp_id = p30_5g5b_env["camp_a"].id

    intent = container.search_service.parse_search_intent(
        org_id=org_id,
        campaign_id=camp_id,
        raw_query="asociaciones médicas en Cali",
    )
    plan = container.search_service.plan_search(intent)

    assert len(plan.tasks) > 0
    assert plan.tasks[0].provider == "overture"
    assert plan.tasks[0].category in ("medical_association", "scientific_society")
    assert plan.tasks[0].city == "Cali"
    assert plan.tasks[0].latitude is not None


def test_scenario_m_existing_overture_plan_execution(p30_5g5b_env):
    """Scenario M: Existing Overture plan execution remains fully operational."""
    container = p30_5g5b_env["container"]
    mock_gateway = MockDiscoveryGateway()
    overture_provider = OvertureDiscoveryProvider(discovery_gateway=mock_gateway)
    prospect_service = ProspectService(container.prospect_repo, mock_gateway)
    orchestrator = DiscoveryOrchestrator(
        providers=[overture_provider],
        prospect_service=prospect_service,
        research_run_repo=container.research_run_repo,
        campaign_repo=container.campaign_repo,
    )

    task = DiscoveryTask(
        provider="overture",
        category="medical_association",
        country="CO",
        region="VALLE",
        city="Cali",
        postal_code="760001",
        latitude=3.4516,
        longitude=-76.5320,
        radius_miles=25.0,
        limit=10,
        negative_keywords=["clinic", "hospital"],
    )
    plan = SearchPlan(
        organization_id=p30_5g5b_env["org_a"].id,
        campaign_id=p30_5g5b_env["camp_a"].id,
        tasks=[task],
    )
    result = orchestrator.execute_plan(plan)

    assert result.tasks_succeeded == 1
    assert result.total_discovered_raw > 0
    assert len(mock_gateway.recorded_queries) == 1
    assert mock_gateway.recorded_queries[0].city == "Cali"


def test_scenario_n_tavily_preview_remains_import_blocked(p30_5g5b_env):
    """Scenario N: Direct prospect import via Tavily or Web Search in live execution mode fails closed."""
    client = p30_5g5b_env["client"]
    headers = p30_5g5b_env["headers_a"]
    camp_id = p30_5g5b_env["camp_a"].id

    payload = {
        "campaign_id": camp_id,
        "search_plan": {
            "tasks": [
                {
                    "task_id": str(uuid.uuid4()),
                    "provider": "web_search",
                    "priority": 1,
                    "query_params": {
                        "category": "medical_association",
                        "city": "Cali",
                        "country": "CO",
                        "limit": 5,
                    },
                }
            ]
        },
    }
    resp = client.post("/api/v1/discovery/execute", json=payload, headers=headers)
    assert resp.status_code == 400
    assert "preview mode only" in resp.text.lower()


def test_scenario_o_zero_live_external_requests(p30_5g5b_env):
    """Scenario O: Verifies strictly zero live external HTTP or network requests occur."""
    import socket

    orig_socket = socket.socket

    def guard_socket(*args, **kwargs):
        sock = orig_socket(*args, **kwargs)
        orig_connect = sock.connect

        def guarded_connect(address):
            host = address[0] if isinstance(address, tuple) else address
            if host not in ("127.0.0.1", "localhost", "::1"):
                raise RuntimeError(f"Forbidden live external network attempt to: {address}")
            return orig_connect(address)

        sock.connect = guarded_connect
        return sock

    socket.socket = guard_socket
    try:
        planner = p30_5g5b_env["planner"]
        for ind, loc in [
            (["medical_association"], {"cities": ["Cali"], "countries": ["CO"]}),
            (["construction"], {"regions": ["FL"], "countries": ["US"]}),
            (["industrial_distributor"], {"regions": ["NJ"], "countries": ["US"]}),
            (["b2b_software"], {"countries": ["CO"]}),
            (["restaurant"], {"cities": ["Miami"], "countries": ["US"]}),
        ]:
            intent = SearchIntent(
                organization_id=p30_5g5b_env["org_a"].id,
                raw_query=f"{ind[0]} discovery query",
                industries=ind,
                **loc,
            )
            plan = planner.plan(intent)
            assert len(plan.tasks) >= 1
    finally:
        socket.socket = orig_socket
