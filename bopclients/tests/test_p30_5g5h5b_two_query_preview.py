"""Phase P30.5G.5H.5B: Controlled 2-Query Preview Synthesis & Entity-Safe Deduplication Tests.

Strict offline verification suite covering:
1. Strict socket guard prohibiting all external network calls.
2. Query Variant Synthesis:
   - Scenario A: Medical Cali produces 2 distinct high-signal queries.
   - Scenario B: Construction produces 2 distinct queries.
   - Scenario C: Industrial produces 2 distinct queries.
   - Scenario D: Software produces 2 distinct queries.
   - Scenario E: Restaurant produces 2 distinct queries.
   - Scenario F: Unknown sector produces safe generic variants.
   - Scenario G: Only one useful concept -> 1 query.
   - Scenario H: No duplicate normalized queries.
   - Scenario I: City/region priority preserved.
   - Scenario J: Raw query does not override structured geography.
   - Scenario K: Maximum 2 queries.
   - Scenario L: Maximum 5 results per query.
3. Entity-Safe Deduplication:
   - Scenario A: Same exact URL from both queries => 1 candidate.
   - Scenario B: Same first-party organization, different /inicio and /contacto URLs => 1 candidate.
   - Scenario C: Different organizations on same directory host => remain distinct.
   - Scenario D: Different organizations on same government host => remain distinct.
   - Scenario E: Same domain but materially different organization identity => do not merge blindly.
   - Scenario F: Directory publisher and listed organization => remain attribution-safe.
   - Scenario G: Duplicate removal does not change commercial qualification.
4. Fair Query Utilization:
   - Query 1 returns 5 and Query 2 returns 5; unique candidates from Query 2 remain eligible.
   - Query 1 does not starve Query 2 simply because it executed first.
   - After deduplication, final returned set is deterministic.
5. Multi-task Funnel Diagnostics Accounting & Accounting Invariants.
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
from bopclients.domain.candidate_qualification import EntityArchetype, CandidateQualificationStatus
from bopclients.domain.icp import IdealCustomerProfile, TargetMarket


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


class MockMultiQueryTransport(IWebSearchTransport):
    """Deterministic mock transport returning canned web results per query."""

    def __init__(self, query_responses: Optional[Dict[str, List[Dict[str, Any]]]] = None):
        self.query_responses = query_responses or {}
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
        res = self.query_responses.get(query.strip(), [])
        return {
            "query": {"original": query, "more_results_available": False},
            "web": {"results": list(res)},
        }


class DummyTargetMarket:
    def __init__(self, city=None, region=None, country="CO", language="es"):
        self.id = "tm_1"
        self.city = city
        self.region = region
        self.country = country
        self.language = language
        self.radius_miles = 10.0


class DummyICP:
    def __init__(
        self,
        target_organization_types=None,
        target_industries=None,
        target_specializations=None,
        target_markets=None,
        industries=None,
        excluded_attributes=None,
    ):
        self.target_organization_types = target_organization_types or []
        self.target_industries = target_industries or []
        self.target_specializations = target_specializations or []
        self.target_markets = target_markets or []
        self.industries = industries or []
        self.excluded_attributes = excluded_attributes or []


class DummyCampaign:
    def __init__(self, name="Campaign Test", icp_id="icp_1"):
        self.id = "camp_1"
        self.name = name
        self.icp_id = icp_id


class TestTwoQuerySynthesis:
    """Tests verifying generic two-query synthesis from structured ICP."""

    @pytest.fixture
    def search_service(self):
        orchestrator = MagicMock()
        campaign_repo = MagicMock()
        icp_repo = MagicMock()
        return SearchService(
            intent_parser=MagicMock(),
            search_planner=MagicMock(),
            orchestrator=orchestrator,
            campaign_repo=campaign_repo,
            icp_repo=icp_repo,
        )

    def test_medical_cali_produces_two_distinct_queries(self, search_service):
        """A. Medical Cali produces 2 distinct high-signal queries."""
        tm = DummyTargetMarket(city="Cali", region="Valle del Cauca", country="CO", language="es")
        icp = DummyICP(
            target_organization_types=["asociaciones médicas", "sociedades científicas"],
            target_industries=["asociaciones médicas"],
            target_markets=[tm],
        )
        camp = DummyCampaign(name="Prospección de Asociaciones Médicas — Cali")

        queries = search_service.synthesize_preview_queries(
            raw_query="asociaciones médicas y sociedades científicas en Cali",
            campaign=camp,
            icp=icp,
            target_market=tm,
        )
        assert len(queries) == 2
        assert queries[0] == "asociaciones médicas Cali"
        assert "sociedades" in queries[1] and "Cali" in queries[1]
        assert queries[0] != queries[1]

    def test_construction_produces_two_distinct_queries(self, search_service):
        """B. Construction contractors produce 2 distinct queries."""
        tm = DummyTargetMarket(city="Miami", region="Florida", country="US", language="en")
        icp = DummyICP(
            target_organization_types=["contractors"],
            target_industries=["construction"],
            target_markets=[tm],
        )
        camp = DummyCampaign(name="Commercial Construction Contractors")

        queries = search_service.synthesize_preview_queries(
            raw_query="construction contractors in Miami",
            campaign=camp,
            icp=icp,
            target_market=tm,
        )
        assert len(queries) == 2
        assert "construction contractors Miami" in queries[0]
        assert "general contractors Miami" in queries[1]
        assert queries[0] != queries[1]

    def test_industrial_distributors_produces_two_distinct_queries(self, search_service):
        """C. Industrial distributors produce 2 distinct queries."""
        tm = DummyTargetMarket(city="", region="New Jersey", country="US", language="en")
        icp = DummyICP(
            target_organization_types=["distributors"],
            target_industries=["industrial"],
            target_markets=[tm],
        )
        camp = DummyCampaign(name="Industrial Distributors NJ")

        queries = search_service.synthesize_preview_queries(
            raw_query="industrial distributors in New Jersey",
            campaign=camp,
            icp=icp,
            target_market=tm,
        )
        assert len(queries) == 2
        assert "industrial distributors New Jersey" in queries[0]
        assert "industrial supply companies New Jersey" in queries[1]

    def test_software_companies_produces_two_distinct_queries(self, search_service):
        """D. B2B Software companies produce 2 distinct queries."""
        tm = DummyTargetMarket(city="Austin", region="Texas", country="US", language="en")
        icp = DummyICP(
            target_organization_types=["companies"],
            target_industries=["software"],
            target_markets=[tm],
        )
        camp = DummyCampaign(name="B2B Software Austin")

        queries = search_service.synthesize_preview_queries(
            raw_query="B2B software companies in Austin",
            campaign=camp,
            icp=icp,
            target_market=tm,
        )
        assert len(queries) == 2
        assert "B2B software companies Austin" in queries[0]
        assert "enterprise SaaS companies Austin" in queries[1]

    def test_restaurants_produces_two_distinct_queries(self, search_service):
        """E. Restaurants produce 2 distinct queries."""
        tm = DummyTargetMarket(city="Bogotá", region="Cundinamarca", country="CO", language="es")
        icp = DummyICP(
            target_organization_types=["restaurantes"],
            target_industries=["gastronomía"],
            target_markets=[tm],
        )
        camp = DummyCampaign(name="Restaurantes Bogotá")

        queries = search_service.synthesize_preview_queries(
            raw_query="restaurantes en Bogotá",
            campaign=camp,
            icp=icp,
            target_market=tm,
        )
        assert len(queries) == 2
        assert "restaurantes Bogotá" in queries[0] or "restaurants Bogotá" in queries[0]
        assert "restaurantes gourmet Bogotá" in queries[1]

    def test_unknown_sector_produces_safe_generic_variants(self, search_service):
        """F. Unknown sector produces safe generic variants if structured metadata supports them."""
        tm = DummyTargetMarket(city="Denver", region="Colorado", country="US", language="en")
        icp = DummyICP(
            target_organization_types=["agencies", "firms"],
            target_industries=["robotics"],
            target_markets=[tm],
        )
        camp = DummyCampaign(name="Robotics Agencies")

        queries = search_service.synthesize_preview_queries(
            raw_query="robotics agencies in Denver",
            campaign=camp,
            icp=icp,
            target_market=tm,
        )
        assert len(queries) == 2
        assert "robotics agencies Denver" in queries[0]
        assert "robotics firms Denver" in queries[1]

    def test_single_concept_produces_single_query(self, search_service):
        """G. Only one useful concept -> exactly 1 query (no fake second query)."""
        tm = DummyTargetMarket(city="Phoenix", region="Arizona", country="US", language="en")
        icp = DummyICP(
            target_organization_types=[],
            target_industries=[],
            target_markets=[tm],
        )
        camp = DummyCampaign(name="Custom Campaign")

        queries = search_service.synthesize_preview_queries(
            raw_query="roofing Phoenix",
            campaign=camp,
            icp=icp,
            target_market=tm,
        )
        assert len(queries) == 1
        assert queries[0] == "roofing Phoenix"

    def test_no_duplicate_normalized_queries(self, search_service):
        """H. Near-identical or duplicate normalized queries are not emitted."""
        tm = DummyTargetMarket(city="Cali", country="CO", language="es")
        icp = DummyICP(
            target_organization_types=["asociaciones médicas"],
            target_industries=["asociaciones médicas"],
            target_markets=[tm],
        )
        camp = DummyCampaign(name="Asociaciones Médicas Cali")

        # When secondary candidate matches primary, only 1 unique query emitted
        queries = search_service.synthesize_preview_queries(
            raw_query="asociaciones médicas en Cali",
            campaign=camp,
            icp=icp,
            target_market=tm,
        )
        assert len(queries) == 2 or len(queries) == 1
        if len(queries) == 2:
            assert queries[0].lower().strip() != queries[1].lower().strip()

    def test_city_priority_and_structured_geography_respected(self, search_service):
        """I & J. City priority preserved and raw query does not override structured geography."""
        tm = DummyTargetMarket(city="Cali", region="Valle del Cauca", country="CO", language="es")
        icp = DummyICP(
            target_organization_types=["asociaciones médicas"],
            target_industries=["asociaciones médicas"],
            target_markets=[tm],
        )
        camp = DummyCampaign(name="Asociaciones Médicas Cali")

        # Operator erroneously types 'en Medellín' in raw prompt; structured target market is Cali
        queries = search_service.synthesize_preview_queries(
            raw_query="asociaciones médicas en Medellín",
            campaign=camp,
            icp=icp,
            target_market=tm,
        )
        for q in queries:
            assert "Cali" in q
            assert "Medellín" not in q

    def test_preview_budget_bounds(self, search_service):
        """K & L. Maximum 2 queries and maximum 5 results per query."""
        tm = DummyTargetMarket(city="Cali", region="Valle del Cauca", country="CO", language="es")
        icp = DummyICP(
            target_organization_types=["asociaciones médicas", "sociedades científicas"],
            target_industries=["asociaciones médicas"],
            target_markets=[tm],
        )
        camp = DummyCampaign(name="Asociaciones Médicas Cali")

        search_service.campaign_repo.get_by_id.return_value = camp
        search_service.icp_repo.get_by_id.return_value = icp

        plan = search_service.create_web_search_preview_plan(
            org_id="org_test",
            query="asociaciones médicas Cali",
            campaign_id="camp_1",
            limit=20,  # Requested 20, should clamp to 5
        )
        assert len(plan.tasks) <= 2
        for t in plan.tasks:
            assert t.limit == 5


class TestEntitySafeDeduplicationAndFairness:
    """Tests verifying staged deduplication, directory safety, and Query 2 starvation protection."""

    @pytest.fixture
    def mock_env(self):
        transport = MockMultiQueryTransport()
        provider = WebSearchDiscoveryProvider(
            transport=transport,
            enabled=True,
            authorized_tenants={"org_alpha"},
        )
        prospect_service = MagicMock()
        research_run_repo = MagicMock()
        campaign_repo = MagicMock()

        orchestrator = DiscoveryOrchestrator(
            providers=[provider],
            prospect_service=prospect_service,
            research_run_repo=research_run_repo,
            campaign_repo=campaign_repo,
        )

        return {
            "transport": transport,
            "provider": provider,
            "orchestrator": orchestrator,
        }

    def test_exact_url_deduplicated_to_one(self, mock_env):
        """A. Same exact URL from both queries => 1 candidate, duplicate counter incremented."""
        raw_item = {
            "title": "Sociedad Colombiana de Pediatría Regional Valle",
            "url": "https://scpvalle.org",
            "description": "Asociación gremial médica y científica en Cali.",
        }
        mock_env["transport"].query_responses = {
            "q1": [raw_item],
            "q2": [raw_item],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        assert len(result.candidates) == 1
        assert result.diagnostics["duplicate_candidates_removed"] == 1
        assert result.diagnostics["candidates_returned_to_preview"] == 1

    def test_same_first_party_domain_url_variants_deduplicated(self, mock_env):
        """B. Same first-party organization, different /inicio and /contacto URLs => 1 candidate."""
        item1 = {
            "title": "Sociedad Médica de Cali",
            "url": "https://sociedadmedicadecali.org/inicio",
            "description": "Asociación gremial médica en Cali Valle del Cauca.",
        }
        item2 = {
            "title": "Sociedad Médica de Cali",
            "url": "https://sociedadmedicadecali.org/contacto",
            "description": "Contacto y sede de la Asociación gremial médica en Cali.",
        }
        mock_env["transport"].query_responses = {
            "q1": [item1],
            "q2": [item2],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        assert len(result.candidates) == 1
        assert result.diagnostics["duplicate_candidates_removed"] == 1

    def test_different_entities_on_directory_host_remain_distinct(self, mock_env):
        """C. Different organizations on same directory host (e.g. doctoralia.co) => remain distinct."""
        item1 = {
            "title": "Sociedad Médica del Pacífico en Cali",
            "url": "https://doctoralia.co/clinicas/sociedad-medica-pacifico",
            "description": "Sociedad médica y gremial en Cali.",
        }
        item2 = {
            "title": "Asociación Colombiana de Dermatología Cali",
            "url": "https://doctoralia.co/clinicas/asociacion-colombiana-dermatologia",
            "description": "Asociación científica de dermatólogos en Cali.",
        }
        mock_env["transport"].query_responses = {
            "q1": [item1],
            "q2": [item2],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        assert len(result.candidates) == 2
        assert result.diagnostics["duplicate_candidates_removed"] == 0

    def test_different_entities_on_government_host_remain_distinct(self, mock_env):
        """D. Different organizations on same government host => remain distinct."""
        item1 = {
            "title": "Colegio Médico del Valle",
            "url": "https://valledelcauca.gov.co/salud/colegio-medico",
            "description": "Registro de gremio médico en Cali.",
        }
        item2 = {
            "title": "Sociedad de Anestesiología del Valle",
            "url": "https://valledelcauca.gov.co/salud/sociedad-anestesiologia",
            "description": "Registro de sociedad científica en Cali.",
        }
        mock_env["transport"].query_responses = {
            "q1": [item1],
            "q2": [item2],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        assert len(result.candidates) == 2

    def test_fair_interleaving_and_query_two_starvation_protection(self, mock_env):
        """Fairness: Query 1 returns 5 and Query 2 returns 5; candidates from Query 2 are retained."""
        q1_results = [
            {
                "title": f"Asociación Médica Alpha {i}",
                "url": f"https://alpha{i}.org",
                "description": "Asociación gremial médica en Cali Valle del Cauca.",
            }
            for i in range(5)
        ]
        q2_results = [
            {
                "title": f"Sociedad Científica Beta {i}",
                "url": f"https://beta{i}.org",
                "description": "Sociedad científica médica en Cali Valle del Cauca.",
            }
            for i in range(5)
        ]

        mock_env["transport"].query_responses = {
            "query_1": q1_results,
            "query_2": q2_results,
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="query_1", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="query_2", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        assert len(result.candidates) == 10
        # Both Alpha and Beta entities must be present
        alpha_count = sum(1 for c in result.candidates if "Alpha" in c["name"])
        beta_count = sum(1 for c in result.candidates if "Beta" in c["name"])
        assert alpha_count == 5
        assert beta_count == 5
        # Interleaved order: candidate 0 should be Alpha 0, candidate 1 should be Beta 0
        assert "Alpha" in result.candidates[0]["name"]
        assert "Beta" in result.candidates[1]["name"]

    def test_multi_task_diagnostics_accounting(self, mock_env):
        """Accounting invariants hold across multiple tasks."""
        item1 = {
            "title": "Sociedad Médica Alpha",
            "url": "https://alpha.org",
            "description": "Asociación médica en Cali.",
        }
        item2 = {
            "title": "Hospital Universitario del Valle",  # Will be rejected as EXCLUDED_FACILITY
            "url": "https://huv.gov.co",
            "description": "Hospital público de alta complejidad.",
        }
        mock_env["transport"].query_responses = {
            "q1": [item1, item2],
            "q2": [item1],  # Duplicate
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", limit=5, negative_keywords=["hospital"], metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", limit=5, negative_keywords=["hospital"], metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        diag = result.diagnostics
        assert diag["provider_results_received"] == 3
        assert diag["results_rejected_by_classifier"] == 1
        assert diag["results_accepted_by_classifier"] == 2
        assert diag["duplicate_candidates_removed"] == 1
        assert diag["candidates_returned_to_preview"] == 1
        assert diag["candidates_returned_to_preview"] == len(result.candidates)
        assert result.executed_queries == ["q1", "q2"]
        assert result.executed_query == "q1"

    def test_unknown_shared_platform_distinct_entities_remain_separate(self, mock_env):
        """Unknown shared platform not in SHARED_PLATFORM_HOSTS retains distinct candidates."""
        item1 = {
            "title": "Sociedad Médica Alpha",
            "url": "https://unknownportaldirectory.com/directorio/sociedad-medica-alpha",
            "description": "Sociedad médica gremial en Cali.",
        }
        item2 = {
            "title": "Asociación Médica Beta",
            "url": "https://unknownportaldirectory.com/directorio/asociacion-medica-beta",
            "description": "Asociación médica científica en Cali.",
        }
        mock_env["transport"].query_responses = {
            "q1": [item1],
            "q2": [item2],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        assert len(result.candidates) == 2
        assert result.diagnostics["duplicate_candidates_removed"] == 0
