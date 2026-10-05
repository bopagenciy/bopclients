"""BOPCLIENTS Phase P30.5G.5H.5D: Cross-Source Entity Bundling & Social Profile Aggregation Tests.

Validates:
1. Multi-signal entity bundling across official websites and social profiles (Facebook, X, LinkedIn, Instagram, YouTube).
2. Collision prevention:
   - Same name across different countries
   - National parent organization vs. regional chapter
   - Association vs. foundation with similar names
   - Directory publisher vs. listed organization
   - Different organizations on the same social platform (Facebook, X)
   - Different organizations on government or directory hosts
   - Generic names with insufficient identity tokens (< 3 tokens)
3. Qualification safety:
   - Multi-source bundling does not upgrade qualification or commercial readiness
   - Social profile does not fabricate municipal physical presence (LOCATION_UNVERIFIED preserved)
   - Official website is never overwritten with a social network URL
4. Diagnostics accounting:
   - source_records_bundled tracking
   - duplicate_candidates_removed separation
   - candidates_returned_to_preview reflecting unique bundled entities
5. Exact live UAT sanitized reproduction fixture.
"""

import socket
import pytest
from typing import Dict, Any, List, Optional
from unittest.mock import MagicMock

from bopclients.application.discovery_orchestrator import DiscoveryOrchestrator
from bopclients.application.search_dto import SearchPlan, DiscoveryTask
from bopclients.infrastructure.providers.web_search_provider import WebSearchDiscoveryProvider, IWebSearchTransport


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


@pytest.fixture
def mock_env():
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


class TestPositiveEntityGrouping:
    """19. Positive grouping across diverse sectors and social platforms."""

    def test_medical_association_official_site_and_social_profiles_bundled(self, mock_env):
        """19.A: Medical Association on official site + Facebook + X bundles into 1 entity with 3 sources."""
        item_web = {
            "title": "Asociación Colombiana de Sociedades Científicas",
            "url": "https://sociedadescientificas.com",
            "description": "Gremio y federación médica científica de Colombia.",
        }
        item_fb = {
            "title": "Asociación Colombiana de Sociedades Científicas - Inicio",
            "url": "https://facebook.com/sociedadescientificas",
            "description": "Página oficial de la Asociación Colombiana de Sociedades Científicas en Facebook.",
        }
        item_x = {
            "title": "Asociación Colombiana de Sociedades Científicas (@acsc_colombia)",
            "url": "https://x.com/acsc_colombia",
            "description": "Cuenta oficial de la Asociación Colombiana de Sociedades Científicas.",
        }

        mock_env["transport"].query_responses = {
            "q1": [item_web, item_fb],
            "q2": [item_x],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        assert len(result.candidates) == 1
        cand = result.candidates[0]
        assert "Asociación Colombiana de Sociedades Científicas" in cand["name"]
        assert cand["sources_count"] == 3
        assert len(cand["sources"]) == 3
        assert cand["organization_website"] == "https://sociedadescientificas.com"

        source_hosts = {s["source_host"] for s in cand["sources"]}
        assert "sociedadescientificas.com" in source_hosts
        assert "facebook.com" in source_hosts
        assert "x.com" in source_hosts

        diag = result.diagnostics
        assert diag["candidates_returned_to_preview"] == 1
        assert diag["source_records_bundled"] == 2

    def test_construction_company_official_site_and_linkedin_bundled(self, mock_env):
        """19.B: Construction company official site + LinkedIn bundles into 1 entity with 2 sources."""
        item_web = {
            "title": "Coastal Construction Group",
            "url": "https://coastalconstruction.com",
            "description": "General contractors and commercial construction enterprise in Miami, FL.",
        }
        item_li = {
            "title": "Coastal Construction Group | LinkedIn",
            "url": "https://linkedin.com/company/coastal-construction-group",
            "description": "Official company profile for Coastal Construction Group.",
        }

        mock_env["transport"].query_responses = {
            "q1": [item_web],
            "q2": [item_li],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", category="construction", country="US", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", category="construction", country="US", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        assert len(result.candidates) == 1
        cand = result.candidates[0]
        assert cand["sources_count"] == 2
        assert cand["organization_website"] == "https://coastalconstruction.com"
        assert result.diagnostics["source_records_bundled"] == 1

    def test_industrial_distributor_official_site_and_x_bundled(self, mock_env):
        """19.C: Industrial distributor official site + X bundles into 1 entity with 2 sources."""
        item_web = {
            "title": "Apex Industrial Supply Corp",
            "url": "https://apexindustrialsupply.com",
            "description": "Distributors of industrial equipment and safety supplies in New Jersey.",
        }
        item_x = {
            "title": "Apex Industrial Supply Corp (@apexindustrial)",
            "url": "https://x.com/apexindustrial",
            "description": "Industrial distributor updates and inventory announcements.",
        }

        mock_env["transport"].query_responses = {
            "q1": [item_web],
            "q2": [item_x],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", category="industrial_distributor", country="US", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", category="industrial_distributor", country="US", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        assert len(result.candidates) == 1
        assert result.candidates[0]["sources_count"] == 2
        assert result.diagnostics["source_records_bundled"] == 1

    def test_software_company_official_site_and_youtube_bundled(self, mock_env):
        """19.D: Software company official site + YouTube/LinkedIn bundles into 1 entity."""
        item_web = {
            "title": "CloudScale Enterprise Software Inc",
            "url": "https://cloudscalesoftware.com",
            "description": "B2B SaaS platform for automated logistics and workflow intelligence.",
        }
        item_yt = {
            "title": "CloudScale Enterprise Software Inc - YouTube",
            "url": "https://youtube.com/@cloudscalesoftware",
            "description": "Official video tutorials and product demonstrations.",
        }

        mock_env["transport"].query_responses = {
            "q1": [item_web],
            "q2": [item_yt],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", category="b2b_software", country="US", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", category="b2b_software", country="US", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        assert len(result.candidates) == 1
        assert result.candidates[0]["sources_count"] == 2
        assert result.diagnostics["source_records_bundled"] == 1

    def test_restaurant_official_site_and_instagram_bundled(self, mock_env):
        """19.E: Restaurant official site + Instagram bundles into 1 entity."""
        item_web = {
            "title": "Restaurante Ringlete Cocina Tradicional",
            "url": "https://restauranteringlete.com",
            "description": "Restaurante de cocina tradicional vallecaucana en Cali.",
        }
        item_ig = {
            "title": "Restaurante Ringlete Cocina Tradicional (@ringletecali)",
            "url": "https://instagram.com/ringletecali",
            "description": "Platos típicos del Valle del Cauca y menú diario.",
        }

        mock_env["transport"].query_responses = {
            "q1": [item_web],
            "q2": [item_ig],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", category="restaurant", country="CO", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", category="restaurant", country="CO", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        assert len(result.candidates) == 1
        assert result.candidates[0]["sources_count"] == 2
        assert result.diagnostics["source_records_bundled"] == 1


class TestCollisionSafety:
    """20. Verification that differing entities are never collapsed."""

    def test_collision_a_same_name_different_countries_remain_separate(self, mock_env):
        """20.A: Same organization name in different countries must NOT bundle."""
        item_co = {
            "title": "Colegio Médico Gremial",
            "url": "https://colegiomedico.org.co",
            "description": "Gremio y asociación de médicos en Colombia.",
        }
        item_cl = {
            "title": "Colegio Médico Gremial",
            "url": "https://colegiomedico.cl",
            "description": "Gremio y asociación de médicos en Chile.",
        }

        mock_env["transport"].query_responses = {
            "q1": [item_co],
            "q2": [item_cl],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", country="CO", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", country="CL", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        assert len(result.candidates) == 2
        assert result.diagnostics["source_records_bundled"] == 0

    def test_collision_b_national_vs_regional_chapter_remain_separate(self, mock_env):
        """20.B: National organization vs regional chapter must NOT bundle."""
        item_national = {
            "title": "Sociedad Colombiana de Pediatría",
            "url": "https://scp.com.co",
            "description": "Asociación médica y científica nacional de pediatras en Colombia.",
        }
        item_regional = {
            "title": "Sociedad Colombiana de Pediatría Regional Valle",
            "url": "https://scpvalle.org",
            "description": "Asociación gremial médica y seccional regional en Cali Valle del Cauca.",
        }

        mock_env["transport"].query_responses = {
            "q1": [item_national],
            "q2": [item_regional],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        assert len(result.candidates) == 2
        assert result.diagnostics["source_records_bundled"] == 0

    def test_collision_c_association_vs_foundation_remain_separate(self, mock_env):
        """20.C: Association vs foundation with similar names must NOT bundle."""
        item_assoc = {
            "title": "Asociación Médica del Valle",
            "url": "https://asomedicavalle.org",
            "description": "Asociación profesional de médicos en Cali.",
        }
        item_found = {
            "title": "Fundación Médica del Valle",
            "url": "https://fundacionmedicavalle.org",
            "description": "Fundación sin ánimo de lucro en Cali para investigación médica.",
        }

        mock_env["transport"].query_responses = {
            "q1": [item_assoc],
            "q2": [item_found],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        assert len(result.candidates) == 2
        assert result.diagnostics["source_records_bundled"] == 0

    def test_collision_d_directory_publisher_vs_listed_organization_remain_separate(self, mock_env):
        """20.D: Directory publisher vs listed organization must NOT bundle."""
        item_dir = {
            "title": "Directorio de Sociedades Médicas en Colombia",
            "url": "https://directoriomedico.co/sociedades",
            "description": "Directorio de agremiaciones y sociedades científicas en Colombia.",
        }
        item_assoc = {
            "title": "Sociedad Médica del Pacífico en Cali",
            "url": "https://sociedadmedicadelpacifico.org",
            "description": "Sociedad gremial médica en Cali Valle del Cauca.",
        }

        mock_env["transport"].query_responses = {
            "q1": [item_dir],
            "q2": [item_assoc],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        assert len(result.candidates) == 2
        assert result.diagnostics["source_records_bundled"] == 0

    def test_collision_e_two_different_organizations_on_facebook_remain_separate(self, mock_env):
        """20.E: Two distinct organizations on Facebook must NOT bundle."""
        item_fb1 = {
            "title": "Sociedad Médica Alpha de Cali - Inicio",
            "url": "https://facebook.com/sociedadmedicaalpha",
            "description": "Página en Facebook de Sociedad Médica Alpha en Cali.",
        }
        item_fb2 = {
            "title": "Asociación Médica Beta del Valle - Inicio",
            "url": "https://facebook.com/asociacionmedicabeta",
            "description": "Página en Facebook de Asociación Médica Beta en Cali.",
        }

        mock_env["transport"].query_responses = {
            "q1": [item_fb1],
            "q2": [item_fb2],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        assert len(result.candidates) == 2
        assert result.diagnostics["source_records_bundled"] == 0

    def test_collision_f_same_government_host_different_associations_remain_separate(self, mock_env):
        """20.F: Different associations on the same government host must NOT bundle."""
        item_gov1 = {
            "title": "Colegio Médico del Valle",
            "url": "https://valledelcauca.gov.co/salud/colegio-medico",
            "description": "Registro oficial de gremio médico en Cali.",
        }
        item_gov2 = {
            "title": "Sociedad de Anestesiología del Valle",
            "url": "https://valledelcauca.gov.co/salud/sociedad-anestesiologia",
            "description": "Registro oficial de sociedad médica en Cali.",
        }

        mock_env["transport"].query_responses = {
            "q1": [item_gov1],
            "q2": [item_gov2],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        assert len(result.candidates) == 2
        assert result.diagnostics["source_records_bundled"] == 0

    def test_collision_g_same_directory_host_different_businesses_remain_separate(self, mock_env):
        """20.G: Different businesses on the same directory host must NOT bundle."""
        item_dir1 = {
            "title": "Sociedad Médica del Pacífico en Cali",
            "url": "https://doctoralia.co/clinicas/sociedad-medica-pacifico",
            "description": "Sociedad médica y gremial en Cali.",
        }
        item_dir2 = {
            "title": "Asociación Colombiana de Dermatología Cali",
            "url": "https://doctoralia.co/clinicas/asociacion-colombiana-dermatologia",
            "description": "Asociación científica de dermatólogos en Cali.",
        }

        mock_env["transport"].query_responses = {
            "q1": [item_dir1],
            "q2": [item_dir2],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        assert len(result.candidates) == 2
        assert result.diagnostics["source_records_bundled"] == 0

    def test_collision_h_generic_name_insufficient_tokens_remain_separate(self, mock_env):
        """20.H: Generic names with fewer than 3 significant tokens must NOT bundle."""
        item1 = {
            "title": "Phoenix Construction",
            "url": "https://phoenixconstruction1.com",
            "description": "General construction enterprise in Phoenix, AZ.",
        }
        item2 = {
            "title": "Phoenix Construction",
            "url": "https://facebook.com/phoenixconstruction",
            "description": "Construction services in Phoenix.",
        }

        mock_env["transport"].query_responses = {
            "q1": [item1],
            "q2": [item2],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", category="construction", country="US", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", category="construction", country="US", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        # Because 'phoenix' and 'construction' only provide 2 significant tokens, bundling is unsafe
        assert len(result.candidates) == 2
        assert result.diagnostics["source_records_bundled"] == 0


class TestQualificationSafety:
    """21. Restricted evidence transfer and qualification immutability."""

    def test_matching_sources_do_not_upgrade_qualification_or_readiness(self, mock_env):
        """Bundling multiple sources does NOT upgrade SEARCH_MATCH to READY_FOR_COMMERCIAL_REVIEW."""
        item_web = {
            "title": "Asociación Colombiana de Sociedades Científicas",
            "url": "https://sociedadescientificas.com",
            "description": "Gremio y federación médica científica de Colombia.",
        }
        item_fb = {
            "title": "Asociación Colombiana de Sociedades Científicas - Inicio",
            "url": "https://facebook.com/sociedadescientificas",
            "description": "Página en Facebook.",
        }

        mock_env["transport"].query_responses = {
            "q1": [item_web],
            "q2": [item_fb],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", city="Cali", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", city="Cali", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        assert len(result.candidates) == 1
        cand = result.candidates[0]
        # Must strictly remain SEARCH_MATCH with is_commercial_review_ready=False
        assert cand["qualification_status"] == "SEARCH_MATCH"
        assert cand["is_commercial_review_ready"] is False

    def test_social_profile_does_not_upgrade_geographic_verification(self, mock_env):
        """Social presence does NOT convert LOCATION_UNVERIFIED into VERIFIED_LOCAL_PRESENCE."""
        item_web = {
            "title": "Sociedad de Médicos Especialistas",
            "url": "https://medicosespecialistas.org",
            "description": "Sociedad científica médica.",
        }
        item_x = {
            "title": "Sociedad de Médicos Especialistas (@medicosesp)",
            "url": "https://x.com/medicosesp",
            "description": "Cuenta en X de médicos especialistas.",
        }

        mock_env["transport"].query_responses = {
            "q1": [item_web],
            "q2": [item_x],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", city="Cali", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", city="Cali", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        cand = result.candidates[0]
        assert cand["geographic_evidence_status"] == "LOCATION_UNVERIFIED"
        assert cand.get("city") is None

    def test_official_website_not_overwritten_by_social_url(self, mock_env):
        """Social URL never overwrites organization_website."""
        # Even if the social profile was processed first in Query 1
        item_fb = {
            "title": "Asociación Colombiana de Sociedades Científicas - Inicio",
            "url": "https://facebook.com/sociedadescientificas",
            "description": "Página en Facebook.",
        }
        item_web = {
            "title": "Asociación Colombiana de Sociedades Científicas",
            "url": "https://sociedadescientificas.com",
            "description": "Sitio web de federación médica científica.",
        }

        mock_env["transport"].query_responses = {
            "q1": [item_fb],
            "q2": [item_web],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="q1", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="q2", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        assert len(result.candidates) == 1
        cand = result.candidates[0]
        # Canonical selection upgrades the display fields to the verified official website
        assert cand["organization_website"] == "https://sociedadescientificas.com"
        assert cand["source_host"] == "sociedadescientificas.com"
        assert cand["sources_count"] == 2


class TestLiveUATRegressionFixture:
    """22. Sanitized synthetic reproduction fixture of the live UAT observation."""

    def test_live_uat_acsc_duplicate_group_resolved_to_one_entity(self, mock_env):
        """Exact model of observed live UAT duplicate group: Web + Facebook + X."""
        item_web = {
            "title": "Asociación Colombiana de Sociedades Científicas",
            "url": "https://sociedadescientificas.com",
            "description": "Federación y asociación de sociedades científicas médicas en Colombia.",
        }
        item_fb = {
            "title": "Asociación Colombiana de Sociedades Científicas - Facebook",
            "url": "https://facebook.com/sociedadescientificas",
            "description": "Canal institucional en Facebook de la Asociación Colombiana de Sociedades Científicas.",
        }
        item_x = {
            "title": "Asociación Colombiana de Sociedades Científicas (@acsc_colombia)",
            "url": "https://x.com/acsc_colombia",
            "description": "Perfil institucional en X de la Asociación Colombiana de Sociedades Científicas.",
        }
        # Another distinct genuine association in Cali
        item_distinct = {
            "title": "Sociedad de Cirugía Pediátrica del Valle",
            "url": "https://cirugiadelvalle.org",
            "description": "Sociedad científica médica de especialistas en Cali Valle del Cauca.",
        }

        mock_env["transport"].query_responses = {
            "asociaciones médicas Cali": [item_web, item_fb],
            "sociedades científicas Cali": [item_x, item_distinct],
        }

        task1 = DiscoveryTask(id="t1", provider="web_search", query="asociaciones médicas Cali", limit=5, metadata={"organization_id": "org_alpha"})
        task2 = DiscoveryTask(id="t2", provider="web_search", query="sociedades científicas Cali", limit=5, metadata={"organization_id": "org_alpha"})
        plan = SearchPlan(organization_id="org_alpha", tasks=[task1, task2])

        result = mock_env["orchestrator"].preview_plan(plan)
        # Raw accepted items were 4, but ACSC has 3 sources, so candidates returned must be 2 unique entities!
        assert len(result.candidates) == 2
        names = [c["name"] for c in result.candidates]
        assert any("Sociedades Científicas" in n for n in names)
        assert any("Cirugía Pediátrica" in n for n in names)

        acsc_cand = next(c for c in result.candidates if "Sociedades Científicas" in c["name"])
        assert acsc_cand["sources_count"] == 3
        assert len(acsc_cand["sources"]) == 3
        assert acsc_cand["organization_website"] == "https://sociedadescientificas.com"

        diag = result.diagnostics
        assert diag["provider_results_received"] == 4
        assert diag["results_accepted_by_classifier"] == 4
        assert diag["duplicate_candidates_removed"] == 0
        assert diag["source_records_bundled"] == 2
        assert diag["candidates_returned_to_preview"] == 2
