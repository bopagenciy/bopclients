"""Comprehensive offline tests for P30.5G.4E Tavily Controlled Preview Foundation.

Verifies all 18 mandated requirements:
1. Authorized preview succeeds.
2. Disabled provider fails closed.
3. Missing key fails closed.
4. Unauthorized tenant fails closed.
5. Unauthorized user fails closed.
6. Normal Overture import unchanged.
7. One Tavily query maximum.
8. Five results maximum.
9. Tampered plan rejected.
10. No automatic fallback.
11. No automatic retry.
12. No prospect inserts (Zero Persistence Guarantee).
13. No source inserts (Zero Persistence Guarantee).
14. No campaign membership inserts (Zero Persistence Guarantee).
15. No real response persistence (Zero DB writes).
16. No CRM synchronization.
17. No external calls (socket interception).
18. No credential leakage.
"""

import json
import socket
from unittest.mock import patch, MagicMock
import urllib.request
import urllib.error
import uuid
import pytest
from starlette.testclient import TestClient

from bopclients.api.app import create_bopclients_api_app
from bopclients.application.discovery_orchestrator import DiscoveryOrchestrator
from bopclients.application.interfaces.forge_gateways import IForgeDiscoveryGateway, DiscoveredBusiness
from bopclients.application.prospect_service import ProspectService
from bopclients.application.search_dto import DiscoveryTask, SearchPlan
from bopclients.domain.campaign import Campaign
from bopclients.domain.enums import CampaignStatus, MemberRole
from bopclients.domain.exceptions import DiscoveryExecutionError, TenantAccessError, SearchPlanningError
from bopclients.domain.icp import IdealCustomerProfile, TargetMarket
from bopclients.domain.organization import Organization, OrganizationMember
from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.infrastructure.providers.overture_provider import OvertureDiscoveryProvider
from bopclients.infrastructure.providers.tavily_transport import TavilyWebSearchTransport
from bopclients.infrastructure.providers.web_search_provider import WebSearchDiscoveryProvider, GeographicScope
from bopclients.runtime.container import build_runtime_container
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.settings import RuntimeSettings


# Synthetic Colombian medical association response fixture
MOCK_TAVILY_CALI_PEDIATRICS = {
    "query": "Sociedad Colombiana de Pediatría Cali",
    "results": [
        {
            "title": "Sociedad Colombiana de Pediatría - Regional Valle del Cauca",
            "url": "https://scpvalle.org",
            "content": "Asociación gremial médica y científica que reúne a los médicos pediatras del Valle del Cauca y Cali.",
            "score": 0.99,
        },
        {
            "title": "Sociedad Colombiana de Cardiología - Capítulo Valle",
            "url": "https://sccvalle.org",
            "content": "Sociedad científica de derecho privado para médicos cardiólogos con sede en Cali.",
            "score": 0.95,
        },
        {
            "title": "Asociación Médica del Valle",
            "url": "https://asomedicavalle.org",
            "content": "Gremio profesional y asociación médica sin ánimo de lucro en Cali y la región.",
            "score": 0.90,
        },
        {
            "title": "Clínica Pediátrica Infantil de Cali",
            "url": "https://clinicapediatricacali.com",
            "content": "Hospital privado de atención infantil con urgencias y hospitalización.",
            "score": 0.80,
        },
    ],
    "response_time": 0.25,
}


class MockOvertureGateway(IForgeDiscoveryGateway):
    """Deterministic in-memory discovery gateway for Overture testing."""

    def __init__(self):
        self.recorded_queries = []
        self.businesses = [
            DiscoveredBusiness(
                overture_id="biz_overture_cali_01",
                name="Sociedad de Ortopedia del Valle",
                website_url="https://ortopediavalle.org",
                phone="+57 2 555 9999",
                address="Av. 6N # 24-00",
                city="Cali",
                state="Valle del Cauca",
                zip_code="760001",
                category="association_or_organization",
                forge_industry="Medical Association",
                latitude=3.4516,
                longitude=-76.5320,
            ),
        ]

    def discover_businesses(self, query):
        self.recorded_queries.append(query)
        return self.businesses


@pytest.fixture
def preview_fixture():
    """Build fully wired test environment with database, auth, and mocked transports."""
    db = create_database_connection(":memory:")
    DatabaseMigrator.migrate(db)

    settings = RuntimeSettings(
        database_url=":memory:",
        auth_signing_key="unit-test-signing-key-minimum-32-chars-long!",
        auth_token_expire_seconds=3600,
        auth_session_expire_days=7,
        tavily_api_key="tvly-mock-secret-key-xyz",
        tavily_enabled=True,
        tavily_authorized_tenants=[],
    )
    container = build_runtime_container(settings, db=db)

    # Seed Tenant A: Bop Agencia (Authorized)
    bop_org = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name="Bop Agencia",
        slug="bop-agencia",
    )
    container.org_repo.save(bop_org)

    # Seed Admin User for Bop Agencia
    admin_user = container.auth_service.register_user(
        email="admin@bop.agency",
        name="Bop Admin",
        password="Password123!",
        locale="es",
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=bop_org.id,
            user_id=admin_user.id,
            role=MemberRole.ADMIN,
        )
    )

    # Seed Member User (non-admin) for Bop Agencia
    member_user = container.auth_service.register_user(
        email="member@bop.agency",
        name="Bop Member",
        password="Password123!",
        locale="es",
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=bop_org.id,
            user_id=member_user.id,
            role=MemberRole.MEMBER,
        )
    )

    # Seed Tenant B: Other Organization (Unauthorized for web preview)
    other_org = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name="Other Agency",
        slug="other-agency",
    )
    container.org_repo.save(other_org)

    other_admin = container.auth_service.register_user(
        email="admin@other.agency",
        name="Other Admin",
        password="Password123!",
        locale="en",
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=other_org.id,
            user_id=other_admin.id,
            role=MemberRole.ADMIN,
        )
    )

    # Seed Campaign for Bop Agencia
    camp = Campaign(
        id=str(uuid.uuid4()),
        organization_id=bop_org.id,
        name="Prospección Asociaciones Médicas Cali",
        status=CampaignStatus.ACTIVE,
    )
    container.campaign_repo.save(bop_org.id, camp)

    # Wire Mocked Transports & Providers
    mock_http_calls = []

    def mock_tavily_http(req: urllib.request.Request, timeout: float) -> bytes:
        mock_http_calls.append({
            "url": req.full_url,
            "headers": dict(req.headers),
            "body": json.loads(req.data.decode("utf-8")),
            "timeout": timeout,
        })
        return json.dumps(MOCK_TAVILY_CALI_PEDIATRICS).encode("utf-8")

    tavily_transport = TavilyWebSearchTransport(
        api_key=settings.tavily_api_key,
        enabled=True,
        http_client=mock_tavily_http,
    )

    web_provider = WebSearchDiscoveryProvider(
        transport=tavily_transport,
        enabled=True,
        authorized_tenants={bop_org.id},
        max_queries_per_run=1,
        max_results_per_query=5,
    )

    overture_gw = MockOvertureGateway()
    overture_provider = OvertureDiscoveryProvider(overture_gw)
    prospect_service = ProspectService(container.prospect_repo, overture_gw)

    orchestrator = DiscoveryOrchestrator(
        providers=[overture_provider, web_provider],
        prospect_service=prospect_service,
        research_run_repo=container.research_run_repo,
        campaign_repo=container.campaign_repo,
    )

    container.search_service.orchestrator = orchestrator
    container.discovery_orchestrator = orchestrator

    app = create_bopclients_api_app(container)
    client = TestClient(app)

    # Generate Access Tokens
    admin_token = container.auth_service.authenticate("admin@bop.agency", "Password123!").access_token
    member_token = container.auth_service.authenticate("member@bop.agency", "Password123!").access_token
    other_token = container.auth_service.authenticate("admin@other.agency", "Password123!").access_token

    return {
        "db": db,
        "container": container,
        "orchestrator": orchestrator,
        "web_provider": web_provider,
        "tavily_transport": tavily_transport,
        "overture_gw": overture_gw,
        "mock_http_calls": mock_http_calls,
        "bop_org": bop_org,
        "other_org": other_org,
        "campaign": camp,
        "client": client,
        "admin_token": admin_token,
        "member_token": member_token,
        "other_token": other_token,
    }


class TestP30_5G4E_TavilyControlledPreview:
    """18-case compliance verification suite for Tavily controlled preview."""

    # 1. Authorized preview succeeds
    def test_01_authorized_preview_succeeds(self, preview_fixture):
        f = preview_fixture
        res = f["client"].post(
            "/api/v1/discovery/preview",
            json={
                "campaign_id": f["campaign"].id,
                "raw_query": "Sociedades de Pediatría en Cali",
                "provider": "web_search",
            },
            headers={
                "Authorization": f"Bearer {f['admin_token']}",
                "X-Bop-Organization-Id": f["bop_org"].bop_organization_id,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "completed"
        assert data["provider"] == "web_search"
        assert data["tasks_executed"] == 1
        assert data["candidates_count"] > 0
        assert len(data["candidates"]) <= 5

        # Check candidate structure
        cand = data["candidates"][0]
        assert "candidate_id" in cand
        assert cand["candidate_id"].startswith("web-")
        assert "name" in cand
        assert "website_url" in cand
        assert cand["classification_status"] in ("ACCEPTED_CANDIDATE", "APPROVED_CANDIDATE")
        assert cand["geographic_scope"] in (
            GeographicScope.REGIONAL_COVERAGE_EVIDENCED.value,
            GeographicScope.NATIONAL_SCOPE.value,
            GeographicScope.LOCATION_UNVERIFIED.value,
        )

    # 2. Disabled provider fails closed
    def test_02_disabled_provider_fails_closed(self, preview_fixture):
        f = preview_fixture
        f["web_provider"].enabled = False

        res = f["client"].post(
            "/api/v1/discovery/preview",
            json={"raw_query": "Sociedades Médicas Cali", "provider": "web_search"},
            headers={
                "Authorization": f"Bearer {f['admin_token']}",
                "X-Bop-Organization-Id": f["bop_org"].bop_organization_id,
            },
        )
        assert res.status_code == 400
        data = res.json()
        err_msg = data.get("detail") or data.get("error", {}).get("message", "")
        assert "disabled" in err_msg.lower()

    # 3. Missing key fails closed
    def test_03_missing_key_fails_closed(self, preview_fixture):
        f = preview_fixture
        f["tavily_transport"].api_key = ""

        # Direct orchestrator preview call
        plan = f["container"].search_service.create_web_search_preview_plan(
            org_id=f["bop_org"].id, query="Sociedades Médicas Cali"
        )
        result = f["orchestrator"].preview_plan(plan)
        assert result.tasks_failed == 1
        assert any("Tavily API key is not configured" in err for err in result.errors)

    # 4. Unauthorized tenant fails closed
    def test_04_unauthorized_tenant_fails_closed(self, preview_fixture):
        f = preview_fixture
        # Other Agency is NOT in web_provider.authorized_tenants
        res = f["client"].post(
            "/api/v1/discovery/preview",
            json={"raw_query": "Sociedades Médicas Cali", "provider": "web_search"},
            headers={
                "Authorization": f"Bearer {f['other_token']}",
                "X-Bop-Organization-Id": f["other_org"].bop_organization_id,
            },
        )
        assert res.status_code == 403
        data = res.json()
        assert data["error"]["code"] == "FORBIDDEN"

        # Also verify direct orchestrator enforcement fails closed with TenantAccessError
        plan = f["container"].search_service.create_web_search_preview_plan(
            org_id=f["other_org"].id, query="Sociedades Médicas Cali"
        )
        result = f["orchestrator"].preview_plan(plan)
        assert result.tasks_failed == 1
        assert any("not authorized" in err.lower() for err in result.errors)

    # 5. Unauthorized user fails closed
    def test_05_unauthorized_user_fails_closed(self, preview_fixture):
        f = preview_fixture
        # Member (non-admin) user attempting preview
        res = f["client"].post(
            "/api/v1/discovery/preview",
            json={"raw_query": "Sociedades Médicas Cali", "provider": "web_search"},
            headers={
                "Authorization": f"Bearer {f['member_token']}",
                "X-Bop-Organization-Id": f["bop_org"].bop_organization_id,
            },
        )
        assert res.status_code == 403
        data = res.json()
        err_msg = data.get("detail") or data.get("error", {}).get("message", "")
        assert "administrator" in err_msg.lower() or "permission" in err_msg.lower()

    # 6. Normal Overture import unchanged
    def test_06_normal_overture_import_unchanged(self, preview_fixture):
        f = preview_fixture
        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            city="Cali",
            country="CO",
            limit=10,
            negative_keywords=["clinic", "hospital"],
        )
        plan = SearchPlan(
            organization_id=f["bop_org"].id,
            campaign_id=f["campaign"].id,
            tasks=[task],
        )

        res = f["orchestrator"].execute_plan(plan)
        assert res.tasks_succeeded == 1
        assert res.prospects_created == 1
        assert res.total_imported_prospects == 1

        # Verify DB records were created for Overture directly in database
        prospects = f["db"].fetch_dicts(
            "SELECT * FROM prospects WHERE organization_id = ?", (f["bop_org"].id,)
        )
        assert len(prospects) == 1
        assert prospects[0]["name"] == "Sociedad de Ortopedia del Valle"

    # 7. One Tavily query maximum
    def test_07_one_tavily_query_maximum(self, preview_fixture):
        f = preview_fixture
        t1 = DiscoveryTask(provider="web_search", query="Query 1", limit=5)
        t2 = DiscoveryTask(provider="web_search", query="Query 2", limit=5)
        plan = SearchPlan(
            organization_id=f["bop_org"].id,
            campaign_id=f["campaign"].id,
            tasks=[t1, t2],
        )

        with pytest.raises(DiscoveryExecutionError) as exc:
            f["orchestrator"].preview_plan(plan)
        assert "Maximum 1 web search query allowed" in str(exc.value)

    # 8. Five results maximum
    def test_08_five_results_maximum(self, preview_fixture):
        f = preview_fixture
        # Plan requesting limit of 50 must be rejected
        t1 = DiscoveryTask(provider="web_search", query="Query 1", limit=50)
        plan = SearchPlan(
            organization_id=f["bop_org"].id,
            campaign_id=f["campaign"].id,
            tasks=[t1],
        )

        with pytest.raises(DiscoveryExecutionError) as exc:
            f["orchestrator"].preview_plan(plan)
        assert "exceeds maximum allowed of 5 results" in str(exc.value)

    # 9. Tampered plan rejected
    def test_09_tampered_plan_rejected(self, preview_fixture):
        f = preview_fixture
        # Attempting to execute a Tavily task via live import /execute route
        res = f["client"].post(
            "/api/v1/discovery/execute",
            json={
                "campaign_id": f["campaign"].id,
                "search_plan": {
                    "organization_id": f["bop_org"].id,
                    "campaign_id": f["campaign"].id,
                    "tasks": [
                        {
                            "task_id": "tampered-task-1",
                            "provider": "web_search",
                            "query_params": {
                                "query": "Injected web query",
                                "category": "medical_association",
                                "country": "CO",
                                "city": "Cali",
                                "limit": 100,
                            },
                        }
                    ],
                },
            },
            headers={
                "Authorization": f"Bearer {f['admin_token']}",
                "X-Bop-Organization-Id": f["bop_org"].bop_organization_id,
            },
        )
        assert res.status_code == 400
        data = res.json()
        err_msg = data.get("detail") or data.get("error", {}).get("message", "")
        assert "preview mode only" in err_msg.lower()

        # Direct orchestrator execute_plan call with web_search task must also fail closed
        t_tampered = DiscoveryTask(provider="web_search", query="Direct inject", limit=5)
        plan = SearchPlan(
            organization_id=f["bop_org"].id,
            campaign_id=f["campaign"].id,
            tasks=[t_tampered],
        )
        with pytest.raises(DiscoveryExecutionError) as exc_orch:
            f["orchestrator"].execute_plan(plan)
        assert "preview mode only" in str(exc_orch.value).lower()

    # 10. No automatic fallback
    def test_10_no_automatic_fallback(self, preview_fixture):
        f = preview_fixture
        f["overture_gw"].recorded_queries.clear()

        # Simulate Tavily error
        f["tavily_transport"]._http_client = MagicMock(
            side_effect=urllib.error.HTTPError("https://api.tavily.com", 500, "Server Error", {}, None)
        )

        plan = f["container"].search_service.create_web_search_preview_plan(
            org_id=f["bop_org"].id, query="Query with failing Tavily"
        )
        result = f["orchestrator"].preview_plan(plan)

        assert result.tasks_failed == 1
        # Crucial: Overture gateway was NOT touched as a fallback
        assert len(f["overture_gw"].recorded_queries) == 0

    # 11. No automatic retry
    def test_11_no_automatic_retry(self, preview_fixture):
        f = preview_fixture
        f["mock_http_calls"].clear()

        call_count = [0]

        def counting_failing_client(req: urllib.request.Request, timeout: float) -> bytes:
            call_count[0] += 1
            raise urllib.error.HTTPError("https://api.tavily.com", 500, "Internal Server Error", {}, None)

        f["tavily_transport"]._http_client = counting_failing_client

        plan = f["container"].search_service.create_web_search_preview_plan(
            org_id=f["bop_org"].id, query="Query with single attempt"
        )
        f["orchestrator"].preview_plan(plan)

        # Verified: exactly 1 HTTP attempt made, 0 retries
        assert call_count[0] == 1

    # 12. No prospect inserts (Zero Persistence Guarantee)
    def test_12_no_prospect_inserts(self, preview_fixture):
        f = preview_fixture
        db = f["db"]

        rows_before = db.fetch_dicts("SELECT COUNT(*) as cnt FROM prospects")[0]["cnt"]

        res = f["client"].post(
            "/api/v1/discovery/preview",
            json={"raw_query": "Sociedades Médicas Cali", "provider": "web_search"},
            headers={
                "Authorization": f"Bearer {f['admin_token']}",
                "X-Bop-Organization-Id": f["bop_org"].bop_organization_id,
            },
        )
        assert res.status_code == 200

        rows_after = db.fetch_dicts("SELECT COUNT(*) as cnt FROM prospects")[0]["cnt"]
        assert rows_after == rows_before == 0

    # 13. No source inserts (Zero Persistence Guarantee)
    def test_13_no_source_inserts(self, preview_fixture):
        f = preview_fixture
        db = f["db"]

        rows_before = db.fetch_dicts("SELECT COUNT(*) as cnt FROM prospect_sources")[0]["cnt"]

        res = f["client"].post(
            "/api/v1/discovery/preview",
            json={"raw_query": "Sociedades Médicas Cali", "provider": "web_search"},
            headers={
                "Authorization": f"Bearer {f['admin_token']}",
                "X-Bop-Organization-Id": f["bop_org"].bop_organization_id,
            },
        )
        assert res.status_code == 200

        rows_after = db.fetch_dicts("SELECT COUNT(*) as cnt FROM prospect_sources")[0]["cnt"]
        assert rows_after == rows_before == 0

    # 14. No campaign membership inserts (Zero Persistence Guarantee)
    def test_14_no_campaign_membership_inserts(self, preview_fixture):
        f = preview_fixture
        db = f["db"]

        rows_before = db.fetch_dicts("SELECT COUNT(*) as cnt FROM campaign_prospects")[0]["cnt"]

        res = f["client"].post(
            "/api/v1/discovery/preview",
            json={
                "campaign_id": f["campaign"].id,
                "raw_query": "Sociedades Médicas Cali",
                "provider": "web_search",
            },
            headers={
                "Authorization": f"Bearer {f['admin_token']}",
                "X-Bop-Organization-Id": f["bop_org"].bop_organization_id,
            },
        )
        assert res.status_code == 200

        rows_after = db.fetch_dicts("SELECT COUNT(*) as cnt FROM campaign_prospects")[0]["cnt"]
        assert rows_after == rows_before == 0

    # 15. No real response persistence (Zero DB writes)
    def test_15_no_real_response_persistence(self, preview_fixture):
        f = preview_fixture
        db = f["db"]

        # Verify no research_runs, enrichment_results, or intel persisted
        runs_before = db.fetch_dicts("SELECT COUNT(*) as cnt FROM research_runs")[0]["cnt"]

        res = f["client"].post(
            "/api/v1/discovery/preview",
            json={"raw_query": "Sociedades Médicas Cali", "provider": "web_search"},
            headers={
                "Authorization": f"Bearer {f['admin_token']}",
                "X-Bop-Organization-Id": f["bop_org"].bop_organization_id,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["database_writes"] == 0
        assert data["prospects_inserted"] == 0
        assert data["sources_inserted"] == 0

        runs_after = db.fetch_dicts("SELECT COUNT(*) as cnt FROM research_runs")[0]["cnt"]
        assert runs_after == runs_before == 0

    # 16. No CRM synchronization
    def test_16_no_crm_synchronization(self, preview_fixture):
        f = preview_fixture
        db = f["db"]

        outbox_before = db.fetch_dicts("SELECT COUNT(*) as cnt FROM bop_integration_outbox")[0]["cnt"]

        res = f["client"].post(
            "/api/v1/discovery/preview",
            json={"raw_query": "Sociedades Médicas Cali", "provider": "web_search"},
            headers={
                "Authorization": f"Bearer {f['admin_token']}",
                "X-Bop-Organization-Id": f["bop_org"].bop_organization_id,
            },
        )
        assert res.status_code == 200

        outbox_after = db.fetch_dicts("SELECT COUNT(*) as cnt FROM bop_integration_outbox")[0]["cnt"]
        assert outbox_after == outbox_before == 0

    # 17. No external calls (socket interception)
    def test_17_no_external_calls(self, preview_fixture):
        f = preview_fixture

        # Patch socket.socket.connect to block any external connection while allowing loopback
        orig_connect = socket.socket.connect

        def safe_connect(sock_self, address):
            host = address[0] if isinstance(address, tuple) else address
            if host in ("127.0.0.1", "localhost", "::1"):
                return orig_connect(sock_self, address)
            raise AssertionError(f"Real external socket connection attempted to {address}!")

        with patch.object(socket.socket, "connect", safe_connect):
            res = f["client"].post(
                "/api/v1/discovery/preview",
                json={"raw_query": "Sociedades Médicas Cali", "provider": "web_search"},
                headers={
                    "Authorization": f"Bearer {f['admin_token']}",
                    "X-Bop-Organization-Id": f["bop_org"].bop_organization_id,
                },
            )
            assert res.status_code == 200

    # 18. No credential leakage
    def test_18_no_credential_leakage(self, preview_fixture):
        f = preview_fixture
        raw_key = "tvly-mock-secret-key-xyz"

        # 1. Check repr of transport
        assert raw_key not in repr(f["tavily_transport"])

        # 2. Check preview response JSON
        res = f["client"].post(
            "/api/v1/discovery/preview",
            json={"raw_query": "Sociedades Médicas Cali", "provider": "web_search"},
            headers={
                "Authorization": f"Bearer {f['admin_token']}",
                "X-Bop-Organization-Id": f["bop_org"].bop_organization_id,
            },
        )
        assert raw_key not in res.text
