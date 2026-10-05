"""Phase P30.5G.5H.4C: Discovery Query Transparency Tests.

Strict offline verification suite covering:
1. Strict socket guard prohibiting all external network calls.
2. Query Transparency Scenarios A through I:
   - Scenario A: Preview response includes executed_query matching the synthesized query dispatched to provider.
   - Scenario B: Raw user query differs from synthesized query (raw vs synthesized comparison).
   - Scenario C: executed_query is None if no tasks executed.
   - Scenario D: executed_query preserves UTF-8 accents and non-ASCII characters ("asociaciones médicas Cali").
   - Scenario E: Exactly one provider task executed during preview.
   - Scenario F: Maximum 5 results budget preserved.
   - Scenario G: Zero live external requests (strict socket interception).
   - Scenario H: Zero prospect inserts, zero source inserts, zero DB writes.
   - Scenario I: Missing/None executed_query in mock responses is backward-compatible.
"""

import socket
import pytest
from unittest.mock import MagicMock
from typing import Dict, Any, List, Optional

from bopclients.application.search_dto import DiscoveryTask, SearchPlan, SearchExecutionResult
from bopclients.application.discovery_orchestrator import DiscoveryOrchestrator
from bopclients.infrastructure.providers.web_search_provider import (
    WebSearchDiscoveryProvider,
    IWebSearchTransport,
)
from bopclients.application.search_service import SearchService
from bopclients.api.schemas.discovery import DiscoveryPreviewResponse


@pytest.fixture(autouse=True)
def block_external_sockets(monkeypatch):
    """Enforce strict offline operation for all qualification tests."""
    orig_connect = socket.socket.connect

    def guarded_connect(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) and address else address
        if host not in ("127.0.0.1", "localhost", "testserver", "::1"):
            raise RuntimeError(f"UNAUTHORIZED_EXTERNAL_NETWORK_CALL: Attempted connection to {host}")
        return orig_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


class MockWebSearchTransport(IWebSearchTransport):
    """Deterministic mock transport returning canned web results."""

    def __init__(self, canned_results: Optional[List[Dict[str, Any]]] = None, raise_error: bool = False):
        self.canned_results = canned_results if canned_results is not None else []
        self.raise_error = raise_error
        self.recorded_queries: List[str] = []

    def search(
        self,
        query: str,
        country: Optional[str] = None,
        search_lang: Optional[str] = None,
        count: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        self.recorded_queries.append(query)
        if self.raise_error:
            raise RuntimeError("Simulated provider connection failure")
        return {
            "query": {"original": query, "more_results_available": False},
            "web": {"results": list(self.canned_results)},
        }


class DummyTargetMarket:
    def __init__(self, city=None, region=None, country=None):
        self.city = city
        self.region = region
        self.country = country


class DummyICP:
    def __init__(self, target_organization_types=None, target_industries=None, target_markets=None):
        self.target_organization_types = target_organization_types or []
        self.target_industries = target_industries or []
        self.target_markets = target_markets or []
        self.industries = []
        self.excluded_attributes = []


class DummyCampaign:
    def __init__(self, name="Prospección de Asociaciones Médicas — Cali", icp_id="icp_1"):
        self.id = "camp_1"
        self.name = name
        self.icp_id = icp_id


class TestQueryTransparency:
    """Verification of ephemeral executed_query propagation and transparency."""

    @pytest.fixture
    def mock_env(self):
        transport = MockWebSearchTransport(
            canned_results=[
                {
                    "title": "Sociedad Colombiana de Pediatría Regional Valle",
                    "url": "https://scpvalle.org",
                    "description": "Asociación gremial médica y científica en Cali.",
                }
            ]
        )
        provider = WebSearchDiscoveryProvider(
            transport=transport,
            enabled=True,
            authorized_tenants={"org_alpha"},
        )
        prospect_service = MagicMock()
        research_run_repo = MagicMock()
        campaign_repo = MagicMock()
        icp_repo = MagicMock()

        orchestrator = DiscoveryOrchestrator(
            providers=[provider],
            prospect_service=prospect_service,
            research_run_repo=research_run_repo,
            campaign_repo=campaign_repo,
        )

        search_service = SearchService(
            intent_parser=MagicMock(),
            search_planner=MagicMock(),
            orchestrator=orchestrator,
            campaign_repo=campaign_repo,
            icp_repo=icp_repo,
        )

        return {
            "transport": transport,
            "provider": provider,
            "orchestrator": orchestrator,
            "search_service": search_service,
            "prospect_service": prospect_service,
            "research_run_repo": research_run_repo,
            "campaign_repo": campaign_repo,
            "icp_repo": icp_repo,
        }

    def test_scenario_a_preview_includes_executed_query(self, mock_env):
        """Scenario A: Preview response includes executed_query matching the synthesized query dispatched to provider."""
        task = DiscoveryTask(
            id="t_1",
            provider="web_search",
            query="asociaciones médicas Cali",
            category="medical_association",
            country="CO",
            city="Cali",
            limit=5,
            metadata={"organization_id": "org_alpha", "preview": True},
        )
        plan = SearchPlan(
            id="plan_1",
            organization_id="org_alpha",
            tasks=[task],
        )

        result = mock_env["orchestrator"].preview_plan(plan)

        assert result.executed_query == "asociaciones médicas Cali"
        assert len(mock_env["transport"].recorded_queries) == 1
        assert mock_env["transport"].recorded_queries[0] == "asociaciones médicas Cali"

    def test_scenario_b_raw_query_differs_from_synthesized_query(self, mock_env):
        """Scenario B: Raw user query differs from synthesized query; both are accessible/verifiable."""
        raw_prompt = "Asociaciones médicas y sociedades científicas de especialidades médicas en Cali, Colombia"
        camp = DummyCampaign(name="Prospección de Asociaciones Médicas — Cali")
        tm = DummyTargetMarket(city="Cali", region="Valle del Cauca", country="CO")
        icp = DummyICP(
            target_organization_types=["asociaciones médicas", "sociedades científicas"],
            target_industries=["asociaciones médicas"],
            target_markets=[tm],
        )

        mock_env["campaign_repo"].get_by_id.return_value = camp
        mock_env["icp_repo"].get_by_id.return_value = icp

        plan = mock_env["search_service"].create_web_search_preview_plan(
            org_id="org_alpha",
            query=raw_prompt,
            campaign_id="camp_1",
        )

        assert len(plan.tasks) == 1
        synth_query = plan.tasks[0].query
        assert synth_query == "asociaciones médicas Cali"
        assert synth_query != raw_prompt

        result = mock_env["search_service"].preview_search("org_alpha", "camp_1", plan)
        assert result.executed_query == "asociaciones médicas Cali"
        assert result.executed_query == synth_query

    def test_scenario_c_executed_query_is_none_if_no_tasks_executed(self, mock_env):
        """Scenario C: executed_query is None if no tasks executed."""
        empty_plan = SearchPlan(
            id="plan_empty",
            organization_id="org_alpha",
            tasks=[],
        )
        result = mock_env["orchestrator"].preview_plan(empty_plan)
        assert result.executed_query is None
        assert result.tasks_total == 0

    def test_scenario_d_preserves_utf8_accents_and_non_ascii(self, mock_env):
        """Scenario D: executed_query preserves UTF-8 accents and non-ASCII characters."""
        query_with_accents = "asociaciones médicas y científicas Bogotá"
        task = DiscoveryTask(
            id="t_utf8",
            provider="web_search",
            query=query_with_accents,
            category="medical_association",
            country="CO",
            city="Bogotá",
            limit=5,
            metadata={"organization_id": "org_alpha", "preview": True},
        )
        plan = SearchPlan(
            id="plan_utf8",
            organization_id="org_alpha",
            tasks=[task],
        )

        result = mock_env["orchestrator"].preview_plan(plan)
        assert result.executed_query == query_with_accents
        assert "é" in result.executed_query
        assert "í" in result.executed_query
        assert "á" in result.executed_query

    def test_scenario_e_exactly_one_provider_task_executed(self, mock_env):
        """Scenario E: Exactly one provider task executed during preview."""
        camp = DummyCampaign()
        tm = DummyTargetMarket(city="Cali")
        icp = DummyICP(target_markets=[tm])

        mock_env["campaign_repo"].get_by_id.return_value = camp
        mock_env["icp_repo"].get_by_id.return_value = icp

        plan = mock_env["search_service"].create_web_search_preview_plan(
            org_id="org_alpha",
            query="asociaciones médicas en Cali",
            campaign_id="camp_1",
        )

        assert len(plan.tasks) == 1
        result = mock_env["search_service"].preview_search("org_alpha", "camp_1", plan)
        assert result.tasks_total == 1
        assert result.tasks_succeeded == 1
        assert len(mock_env["transport"].recorded_queries) == 1

    def test_scenario_f_maximum_5_results_budget_preserved(self, mock_env):
        """Scenario F: Maximum 5 results budget preserved."""
        camp = DummyCampaign()
        tm = DummyTargetMarket(city="Cali")
        icp = DummyICP(target_markets=[tm])

        mock_env["campaign_repo"].get_by_id.return_value = camp
        mock_env["icp_repo"].get_by_id.return_value = icp

        plan = mock_env["search_service"].create_web_search_preview_plan(
            org_id="org_alpha",
            query="asociaciones médicas",
            campaign_id="camp_1",
            limit=100,  # attempt to request more than 5
        )

        assert plan.tasks[0].limit <= 5

    def test_scenario_g_zero_external_network_requests(self, mock_env):
        """Scenario G: Zero live external requests (guarded by block_external_sockets fixture)."""
        # Running the test inherently verifies that no socket opened to external hosts
        task = DiscoveryTask(
            id="t_socket",
            provider="web_search",
            query="test query offline",
            category="medical_association",
            country="CO",
            limit=5,
            metadata={"organization_id": "org_alpha", "preview": True},
        )
        plan = SearchPlan(
            id="plan_socket",
            organization_id="org_alpha",
            tasks=[task],
        )
        result = mock_env["orchestrator"].preview_plan(plan)
        assert result.executed_query == "test query offline"

    def test_scenario_h_zero_persistence_and_zero_db_writes(self, mock_env):
        """Scenario H: Zero prospect inserts, zero source inserts, zero DB writes."""
        task = DiscoveryTask(
            id="t_persist",
            provider="web_search",
            query="asociaciones médicas Cali",
            category="medical_association",
            country="CO",
            city="Cali",
            limit=5,
            metadata={"organization_id": "org_alpha", "preview": True},
        )
        plan = SearchPlan(
            id="plan_persist",
            organization_id="org_alpha",
            tasks=[task],
        )

        result = mock_env["orchestrator"].preview_plan(plan)

        assert result.prospects_created == 0
        assert result.prospects_reused == 0
        assert result.total_imported_prospects == 0
        assert len(result.imported_prospects) == 0
        mock_env["prospect_service"].create_prospect.assert_not_called()
        mock_env["research_run_repo"].create.assert_not_called()

    def test_scenario_i_backward_compatible_response_schema(self):
        """Scenario I: Missing/None executed_query in mock responses is backward-compatible."""
        # 1. Without executed_query (defaults to None)
        resp_default = DiscoveryPreviewResponse(
            status="completed",
            organization_id="org_1",
            provider="web_search",
            tasks_executed=1,
            candidates_count=0,
            candidates=[],
        )
        assert resp_default.executed_query is None
        data = resp_default.model_dump()
        assert data["executed_query"] is None

        # 2. With executed_query
        resp_with_query = DiscoveryPreviewResponse(
            status="completed",
            organization_id="org_1",
            provider="web_search",
            tasks_executed=1,
            candidates_count=0,
            candidates=[],
            executed_query="asociaciones médicas Cali",
        )
        assert resp_with_query.executed_query == "asociaciones médicas Cali"
        data_with_query = resp_with_query.model_dump()
        assert data_with_query["executed_query"] == "asociaciones médicas Cali"
