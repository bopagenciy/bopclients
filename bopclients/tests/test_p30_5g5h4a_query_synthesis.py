"""Phase P30.5G.5H.4A: ICP-Anchored Query Synthesis & Directory Precision Tests.

Strict offline verification suite covering:
1. Strict socket guard prohibiting all external network calls.
2. Query Synthesis Scenarios A through N:
   - Scenario A: Medical Cali with city, region, country -> concise query ("asociaciones médicas Cali").
   - Scenario B: Construction in Florida -> ("construction contractors Florida").
   - Scenario C: Industrial in New Jersey -> ("industrial distributors New Jersey").
   - Scenario D: B2B Software in Colombia -> ("B2B software companies Colombia").
   - Scenario E: Restaurants in Miami -> ("restaurants Miami").
   - Scenario F: Missing ICP -> fallback to campaign name or raw query.
   - Scenario G: Missing geo -> concise concept-only query without trailing whitespace or errors.
   - Scenario H: Token deduplication -> query does not repeat city ("Cali Cali" -> "Cali").
   - Scenario I: Raw prompt containing noise -> stripped/ignored in favor of structured synthesis.
   - Scenario J: Spanish language campaign -> Spanish terms.
   - Scenario K: English language campaign -> English terms.
   - Scenario L: Single query task budget preserved -> SearchPlan has exactly 1 task.
   - Scenario M: Max results budget preserved -> task limit clamped to <= 5.
   - Scenario N: Cross-tenant isolation -> synthesis only uses requesting tenant's campaign and ICP.
3. Directory Precision Scenarios A through G:
   - Scenario A: Hispamedic-like medical portal -> DIRECTORY_LISTING, not FEDERATION.
   - Scenario B: Genuine medical federation -> FEDERATION.
   - Scenario C: Construction contractor directory -> DIRECTORY_LISTING.
   - Scenario D: Industrial distributor directory -> DIRECTORY_LISTING.
   - Scenario E: Software directory -> DIRECTORY_LISTING.
   - Scenario F: Genuine association with member mentions -> PROFESSIONAL_ASSOCIATION.
   - Scenario G: Hyphenated name -> correctly attributed and classified.
"""

import socket
import pytest
from unittest.mock import MagicMock
from typing import Optional, List, Any

from bopclients.domain.candidate_qualification import (
    CandidateQualificationStatus,
    EntityArchetype,
    GeographicEvidenceStatus,
    CurrentActivityStatus,
)
from bopclients.application.discovery.candidate_qualifier import (
    OrganizationCandidateQualifier,
)
from bopclients.application.discovery.candidate_classifier import (
    ClassificationDecision,
    CandidateClassificationStatus,
)
from bopclients.application.search_dto import DiscoveryTask, SearchPlan
from bopclients.application.search_service import SearchService


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


# ==============================================================================
# Helper Mock Objects for Query Synthesis
# ==============================================================================

class DummyTargetMarket:
    def __init__(
        self,
        city: Optional[str] = None,
        region: Optional[str] = None,
        country: Optional[str] = None,
        language: Optional[str] = None,
    ):
        self.city = city
        self.region = region
        self.country = country
        self.language = language


class DummyICP:
    def __init__(
        self,
        target_organization_types: Optional[List[str]] = None,
        target_industries: Optional[List[str]] = None,
        target_specializations: Optional[List[str]] = None,
        industries: Optional[List[str]] = None,
        target_markets: Optional[List[Any]] = None,
        excluded_attributes: Optional[List[str]] = None,
    ):
        self.target_organization_types = target_organization_types or []
        self.target_industries = target_industries or []
        self.target_specializations = target_specializations or []
        self.industries = industries or []
        self.target_markets = target_markets or []
        self.excluded_attributes = excluded_attributes or []


class DummyCampaign:
    def __init__(
        self,
        id: str,
        name: str,
        org_id: str,
        icp_id: Optional[str] = None,
        status: str = "active",
    ):
        self.id = id
        self.name = name
        self.org_id = org_id
        self.icp_id = icp_id
        self.status = status


# ==============================================================================
# Test Suite 1: Query Synthesis (Scenarios A through N)
# ==============================================================================

class TestQuerySynthesis:
    @pytest.fixture
    def search_service(self):
        intent_parser = MagicMock()
        search_planner = MagicMock()
        orchestrator = MagicMock()
        campaign_repo = MagicMock()
        icp_repo = MagicMock()
        return SearchService(
            intent_parser=intent_parser,
            search_planner=search_planner,
            orchestrator=orchestrator,
            campaign_repo=campaign_repo,
            icp_repo=icp_repo,
        )

    # Scenario A: Medical Cali with city, region, country
    def test_scenario_a_medical_cali(self, search_service):
        icp = DummyICP(
            target_organization_types=["asociaciones médicas", "sociedades científicas"],
            target_industries=["salud", "asociaciones médicas"],
            target_markets=[DummyTargetMarket(city="Cali", region="Valle del Cauca", country="CO", language="es")],
        )
        campaign = DummyCampaign(id="c-med", name="Prospección Asociaciones Médicas Cali", org_id="org-1")

        query = search_service.synthesize_preview_query(
            raw_query="Asociaciones médicas y sociedades científicas de especialidades médicas en Cali, Colombia",
            campaign=campaign,
            icp=icp,
            target_market=icp.target_markets[0],
        )

        assert query == "asociaciones médicas Cali"
        assert "Colombia" not in query  # Most specific geo (city) used
        assert "Valle" not in query

    # Scenario B: Construction in Florida
    def test_scenario_b_construction_florida(self, search_service):
        icp = DummyICP(
            target_organization_types=["general contractors"],
            target_industries=["construction"],
            target_markets=[DummyTargetMarket(region="Florida", country="US", language="en")],
        )
        campaign = DummyCampaign(id="c-const", name="Commercial Builders FL", org_id="org-1")

        query = search_service.synthesize_preview_query(
            raw_query="Commercial construction contractors in Florida",
            campaign=campaign,
            icp=icp,
            target_market=icp.target_markets[0],
        )

        assert query == "construction contractors Florida"

    # Scenario C: Industrial in New Jersey
    def test_scenario_c_industrial_new_jersey(self, search_service):
        icp = DummyICP(
            target_organization_types=["distributors", "suppliers"],
            target_industries=["industrial equipment"],
            target_markets=[DummyTargetMarket(region="New Jersey", country="US", language="en")],
        )
        campaign = DummyCampaign(id="c-ind", name="Industrial Suppliers NJ", org_id="org-1")

        query = search_service.synthesize_preview_query(
            raw_query="industrial equipment distributors in New Jersey",
            campaign=campaign,
            icp=icp,
            target_market=icp.target_markets[0],
        )

        assert query == "industrial distributors New Jersey"

    # Scenario D: B2B Software in Colombia
    def test_scenario_d_b2b_software_colombia(self, search_service):
        icp = DummyICP(
            target_organization_types=["companies", "enterprises"],
            target_industries=["b2b software"],
            target_markets=[DummyTargetMarket(country="CO", language="es")],
        )
        campaign = DummyCampaign(id="c-soft", name="Software B2B Colombia", org_id="org-1")

        query = search_service.synthesize_preview_query(
            raw_query="empresas de software b2b en colombia",
            campaign=campaign,
            icp=icp,
            target_market=icp.target_markets[0],
        )

        assert query == "B2B software companies Colombia"

    # Scenario E: Restaurants in Miami
    def test_scenario_e_restaurants_miami(self, search_service):
        icp = DummyICP(
            target_organization_types=["restaurants"],
            target_industries=["restaurant & hospitality"],
            target_markets=[DummyTargetMarket(city="Miami", country="US", language="en")],
        )
        campaign = DummyCampaign(id="c-rest", name="Fine Dining Miami", org_id="org-1")

        query = search_service.synthesize_preview_query(
            raw_query="best restaurants in miami",
            campaign=campaign,
            icp=icp,
            target_market=icp.target_markets[0],
        )

        assert query == "restaurants Miami"

    # Scenario F: Missing ICP fallback to campaign name or raw query
    def test_scenario_f_missing_icp_fallback(self, search_service):
        campaign = DummyCampaign(id="c-fallback", name="Prospección de Asociaciones Médicas — Cali", org_id="org-1")

        query = search_service.synthesize_preview_query(
            raw_query="Asociaciones en Cali",
            campaign=campaign,
            icp=None,
            city="Cali",
        )

        assert query == "asociaciones médicas Cali"

        # If campaign is also None, falls back to category or raw query
        query_raw = search_service.synthesize_preview_query(
            raw_query="cardiología clínica",
            campaign=None,
            icp=None,
            city="Cali",
        )
        assert query_raw == "cardiología clínica Cali"

    # Scenario G: Missing geo produces concise concept-only query
    def test_scenario_g_missing_geo(self, search_service):
        icp = DummyICP(
            target_organization_types=["medical associations"],
            target_industries=["healthcare"],
        )
        query = search_service.synthesize_preview_query(
            raw_query="medical associations",
            campaign=None,
            icp=icp,
            target_market=DummyTargetMarket(language="en"),
            city=None,
            region=None,
            country=None,
        )

        assert query == "medical associations"
        assert query == query.strip()
        assert "  " not in query

    # Scenario H: Token deduplication
    def test_scenario_h_token_deduplication(self, search_service):
        query = search_service.synthesize_preview_query(
            raw_query="asociaciones médicas Cali",
            campaign=None,
            icp=None,
            city="Cali",
        )
        assert query == "asociaciones médicas Cali"
        assert "Cali Cali" not in query

    # Scenario I: Raw prompt containing noise
    def test_scenario_i_noise_stripping(self, search_service):
        icp = DummyICP(
            target_organization_types=["asociaciones médicas"],
            target_industries=["salud"],
            target_markets=[DummyTargetMarket(city="Cali", country="CO", language="es")],
        )
        query = search_service.synthesize_preview_query(
            raw_query="por favor buscar asociaciones en Cali Colombia gracias",
            campaign=None,
            icp=icp,
            target_market=icp.target_markets[0],
        )

        assert query == "asociaciones médicas Cali"
        assert "por favor" not in query
        assert "gracias" not in query

    # Scenario J: Spanish language campaign
    def test_scenario_j_spanish_language(self, search_service):
        icp = DummyICP(
            target_organization_types=["asociaciones"],
            target_industries=["healthcare"],
            target_markets=[DummyTargetMarket(city="Bogotá", country="CO", language="es")],
        )
        query = search_service.synthesize_preview_query(
            raw_query="sociedades de especialistas",
            campaign=None,
            icp=icp,
            target_market=icp.target_markets[0],
        )

        assert "asociaciones médicas" in query
        assert "Bogotá" in query

    # Scenario K: English language campaign
    def test_scenario_k_english_language(self, search_service):
        icp = DummyICP(
            target_organization_types=["associations"],
            target_industries=["healthcare"],
            target_markets=[DummyTargetMarket(city="Boston", country="US", language="en")],
        )
        query = search_service.synthesize_preview_query(
            raw_query="medical societies",
            campaign=None,
            icp=icp,
            target_market=icp.target_markets[0],
        )

        assert "medical associations" in query
        assert "Boston" in query

    # Scenario L: Single query task budget preserved in preview plan
    def test_scenario_l_single_task_budget(self, search_service):
        plan = search_service.create_web_search_preview_plan(
            org_id="org-1",
            query="Asociaciones médicas en Cali",
            category="medical_association",
            country="CO",
            city="Cali",
            limit=5,
        )

        assert isinstance(plan, SearchPlan)
        assert len(plan.tasks) == 1
        assert plan.tasks[0].provider == "web_search"
        assert plan.tasks[0].query == "asociaciones médicas Cali"

    # Scenario M: Max results budget preserved (limit clamped <= 5)
    def test_scenario_m_max_results_budget_clamped(self, search_service):
        # Even if caller passes limit=20, clamped to 5
        plan = search_service.create_web_search_preview_plan(
            org_id="org-1",
            query="Asociaciones médicas en Cali",
            category="medical_association",
            country="CO",
            city="Cali",
            limit=20,
        )

        assert plan.tasks[0].limit == 5

    # Scenario N: Cross-tenant isolation
    def test_scenario_n_cross_tenant_isolation(self, search_service):
        # Configure campaign_repo to return campaign only for matching org_id
        def mock_get_by_id(org_id, campaign_id):
            if org_id == "tenant-a" and campaign_id == "camp-a":
                return DummyCampaign(id="camp-a", name="Tenant A Medical", org_id="tenant-a", icp_id="icp-a")
            return None

        search_service.campaign_repo.get_by_id.side_effect = mock_get_by_id
        search_service.icp_repo.get_by_id.return_value = DummyICP(
            target_organization_types=["asociaciones médicas"],
            target_markets=[DummyTargetMarket(city="Cali", country="CO", language="es")],
        )

        # Tenant B cannot access Tenant A's campaign
        plan = search_service.create_web_search_preview_plan(
            org_id="tenant-b",
            query="query",
            campaign_id="camp-a",
        )

        # Plan organization_id is tenant-b
        assert plan.organization_id == "tenant-b"
        # Since camp-a was not found for tenant-b, it did not use tenant-a's campaign metadata
        search_service.campaign_repo.get_by_id.assert_called_with("tenant-b", "camp-a")

    # Section 2 Edge Case: Stale/administrative campaign name does not override clear raw operator intent
    def test_section_2_stale_campaign_name_does_not_override_raw_query(self, search_service):
        stale_campaign = DummyCampaign(
            id="c-stale",
            name="Prospección de Asociaciones Médicas — Cali",
            org_id="org-1",
        )
        # Clear operator business target for accounting firms
        query = search_service.synthesize_preview_query(
            raw_query="firmas de contabilidad en Cali",
            campaign=stale_campaign,
            icp=None,
            city="Cali",
        )
        assert query == "firmas de contabilidad Cali"
        assert "asociaciones" not in query
        assert "médicas" not in query

    # Section 3 Edge Case: General-purpose unknown ICP categories
    def test_section_3_general_purpose_unknown_categories(self, search_service):
        # Unknown Category 1: Accounting firms
        icp_accounting = DummyICP(
            target_industries=["accounting"],
            target_organization_types=["firms"],
            target_markets=[DummyTargetMarket(city="Cali", country="CO", language="es")],
        )
        q_acc = search_service.synthesize_preview_query(
            raw_query="accounting firms",
            campaign=None,
            icp=icp_accounting,
            target_market=icp_accounting.target_markets[0],
        )
        assert q_acc == "accounting firms Cali"

        # Unknown Category 2: Commercial cleaning companies
        icp_cleaning = DummyICP(
            target_industries=["commercial cleaning"],
            target_organization_types=["companies"],
            target_markets=[DummyTargetMarket(city="Miami", country="US", language="en")],
        )
        q_clean = search_service.synthesize_preview_query(
            raw_query="commercial cleaning companies",
            campaign=None,
            icp=icp_cleaning,
            target_market=icp_cleaning.target_markets[0],
        )
        assert q_clean == "commercial cleaning companies Miami"

    # Section 4 Edge Case: Structured geography prevents raw-query location override
    def test_section_4_structured_geography_prevents_raw_location_override(self, search_service):
        icp = DummyICP(
            target_organization_types=["asociaciones médicas"],
            target_markets=[DummyTargetMarket(city="Cali", country="CO", language="es")],
        )
        # Operator accidentally typed Bogotá in raw query, but target market is Cali
        query = search_service.synthesize_preview_query(
            raw_query="asociaciones médicas Bogotá",
            campaign=None,
            icp=icp,
            target_market=icp.target_markets[0],
        )
        assert query == "asociaciones médicas Cali"
        assert "Bogotá" not in query

    # Section 5 Edge Case: Language safety with unknown language
    def test_section_5_language_safety_unknown_language(self, search_service):
        icp = DummyICP(
            target_industries=["accounting"],
            target_organization_types=["firms"],
            target_markets=[DummyTargetMarket(city="Zurich", country="CH", language="de")],
        )
        query = search_service.synthesize_preview_query(
            raw_query="accounting firms",
            campaign=None,
            icp=icp,
            target_market=icp.target_markets[0],
        )
        # Does not fabricate an invented translation, preserves structured terms + geography
        assert query == "accounting firms Zurich"


# ==============================================================================
# Test Suite 2: Directory Precision Fix (Scenarios A through G)
# ==============================================================================

class TestDirectoryPrecision:
    @pytest.fixture
    def qualifier(self):
        return OrganizationCandidateQualifier()

    @pytest.fixture
    def medical_task(self):
        return DiscoveryTask(
            id="t-med-1",
            provider="web_search",
            query="asociaciones médicas Cali",
            category="medical_association",
            country="CO",
            city="Cali",
            region="Valle del Cauca",
        )

    # Scenario A: Hispamedic-like medical portal
    def test_scenario_a_hispamedic_portal_is_directory(self, qualifier, medical_task):
        decision = ClassificationDecision(
            status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
            is_valid=True,
        )

        result = qualifier.qualify(
            candidate_name="Hispamedic",
            target_intent="medical_association",
            base_classification=decision,
            raw_title="Directorio de Asociaciones Médicas y Sociedades Científicas - Hispamedic",
            url="https://hispamedic.com/directorio-asociaciones",
            snippet="Consulte las sociedades médicas en Colombia: Asociación de Pediatría, Federación Médica Colombiana, Sociedad de Cirugía.",
            task=medical_task,
        )

        # Must classify as DIRECTORY_LISTING, NOT FEDERATION
        assert result.entity_archetype == EntityArchetype.DIRECTORY_LISTING
        assert result.entity_archetype != EntityArchetype.FEDERATION
        assert result.is_commercial_review_ready is False
        assert "UNRESOLVED_COMPOSITE_DIRECTORY_ENTITY" in result.missing_evidence

    # Scenario B: Genuine medical federation
    def test_scenario_b_genuine_medical_federation(self, qualifier, medical_task):
        decision = ClassificationDecision(
            status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
            is_valid=True,
        )

        result = qualifier.qualify(
            candidate_name="Federación Médica Colombiana",
            target_intent="medical_association",
            base_classification=decision,
            raw_title="Federación Médica Colombiana | Entidad gremial nacional",
            url="https://federacionmedicacolombiana.com",
            snippet="Somos la entidad gremial de segundo grado fundada en 1936 que agrupa a los colegios médicos de Colombia en Cali y Bogotá.",
            task=medical_task,
        )

        assert result.entity_archetype == EntityArchetype.FEDERATION
        assert result.organization_website == "https://federacionmedicacolombiana.com"

    # Scenario C: Construction contractor directory
    def test_scenario_c_construction_directory(self, qualifier):
        const_task = DiscoveryTask(
            id="t-const-1",
            provider="web_search",
            query="construction contractors Florida",
            category="construction",
            country="US",
            region="Florida",
        )
        decision = ClassificationDecision(
            status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
            is_valid=True,
        )

        result = qualifier.qualify(
            candidate_name="Florida Builders Guide",
            target_intent="construction",
            base_classification=decision,
            raw_title="Directorio de Constructores de Florida | Top Contractors",
            url="https://floridabuildersguide.com/directorio",
            snippet="Listado de empresas contratistas en Florida. Ranking and list of top 20 commercial builders.",
            task=const_task,
        )

        assert result.entity_archetype == EntityArchetype.DIRECTORY_LISTING
        assert result.is_commercial_review_ready is False

    # Scenario D: Industrial distributor directory
    def test_scenario_d_industrial_distributor_directory(self, qualifier):
        ind_task = DiscoveryTask(
            id="t-ind-1",
            provider="web_search",
            query="industrial distributors New Jersey",
            category="industrial_distributor",
            country="US",
            region="New Jersey",
        )
        decision = ClassificationDecision(
            status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
            is_valid=True,
        )

        result = qualifier.qualify(
            candidate_name="NJ Industrial Portal",
            target_intent="industrial_distributor",
            base_classification=decision,
            raw_title="Guía de Distribuidores Industriales en New Jersey",
            url="https://njindustrialportal.com/suppliers",
            snippet="Consulte los distribuidores y proveedores industriales en New Jersey. Directory of industrial suppliers.",
            task=ind_task,
        )

        assert result.entity_archetype == EntityArchetype.DIRECTORY_LISTING
        assert result.is_commercial_review_ready is False

    # Scenario E: Software directory
    def test_scenario_e_software_directory(self, qualifier):
        soft_task = DiscoveryTask(
            id="t-soft-1",
            provider="web_search",
            query="B2B software companies Colombia",
            category="b2b_software",
            country="CO",
        )
        decision = ClassificationDecision(
            status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
            is_valid=True,
        )

        result = qualifier.qualify(
            candidate_name="Tech Ranking Colombia",
            target_intent="b2b_software",
            base_classification=decision,
            raw_title="Top Software Companies in Colombia",
            url="https://techranking.co/top-software",
            snippet="Directory of software platforms and tech vendors. Ranking of 50 enterprise software companies.",
            task=soft_task,
        )

        assert result.entity_archetype == EntityArchetype.DIRECTORY_LISTING
        assert result.is_commercial_review_ready is False

    # Scenario F: Genuine association with member mentions
    def test_scenario_f_genuine_association_with_members(self, qualifier, medical_task):
        decision = ClassificationDecision(
            status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
            is_valid=True,
        )

        result = qualifier.qualify(
            candidate_name="Asociación Colombiana de Dermatología",
            target_intent="medical_association",
            base_classification=decision,
            raw_title="Asociación Colombiana de Dermatología y Cirugía Dermatológica",
            url="https://asocolderma.org.co",
            snippet="Somos una entidad médica científica. Nuestros miembros asociados cuentan con formación continua en Cali y todo el país.",
            task=medical_task,
        )

        # Must classify as PROFESSIONAL_ASSOCIATION, not directory listing
        assert result.entity_archetype == EntityArchetype.PROFESSIONAL_ASSOCIATION
        assert result.organization_website == "https://asocolderma.org.co"

    # Scenario G: Hyphenated name correctly attributed
    def test_scenario_g_hyphenated_candidate_attribution(self, qualifier, medical_task):
        decision = ClassificationDecision(
            status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
            is_valid=True,
        )

        result = qualifier.qualify(
            candidate_name="ACD - Asociación Colombiana de Dermatología",
            target_intent="medical_association",
            base_classification=decision,
            raw_title="ACD - Asociación Colombiana de Dermatología | Sede Cali",
            url="https://asocolderma.org.co/cali",
            snippet="Capítulo Valle del Cauca con sede en Cali. Promovemos el avance de la dermatología en la región.",
            task=medical_task,
        )

        assert result.entity_archetype == EntityArchetype.PROFESSIONAL_ASSOCIATION
        assert result.geographic_evidence_status == GeographicEvidenceStatus.VERIFIED_LOCAL_PRESENCE
