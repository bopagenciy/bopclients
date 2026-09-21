"""Unit tests for BopClients P2 - Search Intent & Discovery Pipeline."""

import pytest
from bopclients.domain.search_intent import SearchIntent
from bopclients.domain.organization import Organization
from bopclients.domain.campaign import Campaign
from bopclients.domain.enums import CampaignStatus
from bopclients.domain.exceptions import TenantAccessError, SearchPlanningError, DiscoveryProviderError
from bopclients.domain.normalizers import CategoryNormalizer, CountryNormalizer
from bopclients.application.search_dto import DiscoveryTask, SearchPlan
from bopclients.application.search_intent_parser import RuleBasedSearchIntentParser
from bopclients.application.search_planner import DefaultSearchPlanner
from bopclients.application.search_service import SearchService
from bopclients.application.discovery_orchestrator import DiscoveryOrchestrator
from bopclients.infrastructure.location.static_location_resolver import StaticLocationResolver
from bopclients.infrastructure.providers.overture_provider import OvertureDiscoveryProvider
from bopclients.infrastructure.gateways.forge_gateway import ForgeDiscoveryGatewayAdapter, DiscoveredBusiness
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.application.prospect_service import ProspectService
from bopclients.infrastructure.db.migrations import run_p1_migrations
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend


@pytest.fixture
def memory_db():
    db = ForgeDB(_SQLiteBackend(db_path=":memory:"))
    run_p1_migrations(db)
    return db


class MockDiscoveryGateway:
    """Mock gateway returning predictable DiscoveredBusiness results for testing."""

    def __init__(self, businesses=None, should_fail=False):
        self.businesses = businesses or [
            DiscoveredBusiness(
                overture_id="ov-dentist-101",
                name="Miami Modern Dentistry",
                website_url="https://miamimodern.com",
                phone="305-555-9988",
                city="Miami",
                state="FL",
                zip_code="33101",
                category="dentist",
            )
        ]
        self.should_fail = should_fail

    def discover_businesses(self, query):
        if self.should_fail:
            raise RuntimeError("Mock Gateway simulated connection error")
        return self.businesses


class TestSearchIntentAndPlanner:
    def test_spanish_intent_parsing_dentists_miami(self):
        parser = RuleBasedSearchIntentParser()
        intent = parser.parse("org-1", "camp-1", "Busca dentistas en Miami que necesiten página web y automatización")

        assert "dentist" in intent.industries
        assert "Miami" in intent.cities
        assert "US" in intent.countries
        assert "web_development" in intent.services_to_offer
        assert "old_website" in intent.desired_signals

    def test_spanish_intent_parsing_lawyers_colombia(self):
        parser = RuleBasedSearchIntentParser()
        intent = parser.parse("org-1", None, "Quiero encontrar abogados en Colombia")

        assert "lawyer" in intent.industries
        assert "CO" in intent.countries

    def test_english_intent_parsing_dentists_orlando(self):
        parser = RuleBasedSearchIntentParser()
        intent = parser.parse("org-1", "camp-1", "Find dentist in Orlando Florida for web design")

        assert "dentist" in intent.industries
        assert "Orlando" in intent.cities
        assert "US" in intent.countries

    def test_multi_city_intent_parsing(self):
        parser = RuleBasedSearchIntentParser()
        intent = parser.parse("org-1", "camp-1", "Busca dentistas en Miami y Orlando")

        assert "Miami" in intent.cities
        assert "Orlando" in intent.cities

    def test_company_size_and_language_parsing(self):
        parser = RuleBasedSearchIntentParser()
        intent = parser.parse("org-1", None, "Busca empresas de 10 a 100 empleados en España que hablen español")

        assert intent.company_size_min == 10
        assert intent.company_size_max == 100
        assert "es" in intent.languages
        assert "ES" in intent.countries

    def test_normalizers(self):
        assert CategoryNormalizer.normalize("dentistas") == "dentist"
        assert CategoryNormalizer.normalize("abogados") == "lawyer"
        assert CategoryNormalizer.normalize("restaurante") == "restaurant"
        assert CategoryNormalizer.normalize("asociaciones médicas") == "medical_association"
        assert CategoryNormalizer.normalize("sociedades científicas") == "scientific_society"
        assert CategoryNormalizer.normalize("colegios profesionales") == "professional_association"
        assert CategoryNormalizer.normalize("organizaciones sin fines de lucro") == "non_profit"
        assert CategoryNormalizer.normalize("clínicas") == "clinic"
        assert CategoryNormalizer.normalize("salud") == "healthcare"

        assert CountryNormalizer.normalize("Colombia") == "CO"
        assert CountryNormalizer.normalize("España") == "ES"
        assert CountryNormalizer.normalize("Estados Unidos") == "US"
        assert CountryNormalizer.normalize("Alemania") == "DE"

    def test_semantic_cases_a_through_f(self):
        parser = RuleBasedSearchIntentParser()

        # Case A: Buscar clínicas en Cali. -> clinic positive
        intent_a = parser.parse("org-1", None, "Buscar clínicas en Cali.")
        assert "clinic" in intent_a.industries
        assert intent_a.negative_keywords == []

        # Case B: Excluir clínicas en Cali. -> clinic NOT positive
        intent_b = parser.parse("org-1", None, "Excluir clínicas en Cali.")
        assert "clinic" not in intent_b.industries
        assert "clinic" in intent_b.negative_keywords

        # Case C: Buscar asociaciones médicas en Cali, excluir clínicas. -> associations positive, clinics excluded
        intent_c = parser.parse("org-1", None, "Buscar asociaciones médicas en Cali, excluir clínicas.")
        assert "medical_association" in intent_c.industries
        assert "clinic" not in intent_c.industries
        assert "clinic" in intent_c.negative_keywords

        # Case D: Buscar asociaciones médicas y sociedades científicas en Cali, Colombia. -> both recognized
        intent_d = parser.parse("org-1", None, "Buscar asociaciones médicas y sociedades científicas en Cali, Colombia.")
        assert "medical_association" in intent_d.industries
        assert "scientific_society" in intent_d.industries
        assert intent_d.negative_keywords == []

        # Case E: Buscar asociaciones médicas, no hospitales, no clínicas, no consultorios ni farmacias.
        intent_e = parser.parse("org-1", None, "Buscar asociaciones médicas, no hospitales, no clínicas, no consultorios ni farmacias.")
        assert "medical_association" in intent_e.industries
        assert "clinic" not in intent_e.industries
        assert "hospital" not in intent_e.industries
        assert "medical_office" not in intent_e.industries
        assert "pharmacy" not in intent_e.industries
        assert "hospital" in intent_e.negative_keywords
        assert "clinic" in intent_e.negative_keywords
        assert "medical_office" in intent_e.negative_keywords
        assert "pharmacy" in intent_e.negative_keywords

        # Case F: Buscar clínicas y asociaciones médicas en Cali. -> both affirmative recognized
        intent_f = parser.parse("org-1", None, "Buscar clínicas y asociaciones médicas en Cali.")
        assert "clinic" in intent_f.industries
        assert "medical_association" in intent_f.industries
        assert intent_f.negative_keywords == []

    def test_user_long_and_short_queries(self):
        parser = RuleBasedSearchIntentParser()

        # Short query
        intent_short = parser.parse("org-1", None, "Buscar asociaciones médicas y sociedades científicas en Cali, Colombia.")
        assert "medical_association" in intent_short.industries
        assert "scientific_society" in intent_short.industries
        assert "Cali" in intent_short.cities
        assert "CO" in intent_short.countries
        assert "clinic" not in intent_short.industries

        # Long query
        long_query = (
            "Buscar asociaciones médicas y sociedades científicas en Cali, Colombia, que agrupen "
            "profesionales de la salud. Busco organizaciones gremiales o científicas, no hospitales, "
            "no clínicas, no consultorios ni farmacias."
        )
        intent_long = parser.parse("org-1", None, long_query)
        assert "medical_association" in intent_long.industries
        assert "scientific_society" in intent_long.industries
        assert "professional_association" in intent_long.industries
        assert "clinic" not in intent_long.industries
        assert "hospital" in intent_long.negative_keywords
        assert "clinic" in intent_long.negative_keywords
        assert "medical_office" in intent_long.negative_keywords
        assert "pharmacy" in intent_long.negative_keywords
        assert "Cali" in intent_long.cities
        assert "CO" in intent_long.countries

    def test_search_plan_signal_warning_and_category_separation(self):
        resolver = StaticLocationResolver()
        planner = DefaultSearchPlanner(resolver)

        intent = SearchIntent(
            organization_id="org-1",
            raw_query="dentistas en Miami que necesiten desarrollo web",
            industries=["dentist"],
            countries=["US"],
            cities=["Miami"],
            services_to_offer=["web_development"],
            desired_signals=["old_website"],
        )
        plan = planner.plan(intent)
        assert len(plan.tasks) == 1
        assert plan.tasks[0].category == "dentist"  # Service is NOT category
        assert len(plan.warnings) == 1
        assert plan.warnings[0].code == "SIGNAL_FILTER_REQUIRES_ENRICHMENT"

    def test_plan_without_campaign_allowed(self):
        parser = RuleBasedSearchIntentParser()
        planner = DefaultSearchPlanner(StaticLocationResolver())

        intent = parser.parse("org-1", None, "dentistas en Miami")
        plan = planner.plan(intent)
        assert plan.campaign_id is None
        assert len(plan.tasks) == 1


class TestDiscoveryExecution:
    def test_full_search_execution_pipeline(self, memory_db):
        org_repo = OrganizationRepository(memory_db)
        campaign_repo = CampaignRepository(memory_db)
        prospect_repo = ProspectRepository(memory_db)
        rr_repo = ResearchRunRepository(memory_db)

        org = org_repo.save(Organization(name="Org Exec", slug="org-exec"))
        camp = campaign_repo.save(org.id, Campaign(name="Exec Camp", status=CampaignStatus.ACTIVE))

        parser = RuleBasedSearchIntentParser()
        planner = DefaultSearchPlanner(StaticLocationResolver())

        mock_biz = DiscoveredBusiness(
            overture_id="ov-dentist-999",
            name="Miami Smile Center",
            website_url="https://miamismilecenter.com",
            phone="305-555-4433",
            city="Miami",
            state="FL",
            zip_code="33101",
            category="dentist",
        )
        mock_gateway = MockDiscoveryGateway([mock_biz])
        provider = OvertureDiscoveryProvider(mock_gateway)
        prospect_service = ProspectService(prospect_repo)
        orchestrator = DiscoveryOrchestrator([provider], prospect_service, rr_repo, campaign_repo)

        search_service = SearchService(parser, planner, orchestrator, campaign_repo)

        intent = search_service.parse_search_intent(org.id, camp.id, "dentistas en Miami")
        plan = search_service.plan_search(intent)
        result = search_service.execute_search(org.id, camp.id, plan)

        assert result.total_imported_prospects == 1
        assert result.prospects_created == 1
        assert result.prospects_reused == 0

        # Run pipeline AGAIN to verify prospect reuse and provenance deduplication
        result2 = search_service.execute_search(org.id, camp.id, plan)
        assert result2.total_imported_prospects == 1
        assert result2.prospects_created == 0
        assert result2.prospects_reused == 1

        # Verify only 1 ProspectSource record created
        sources = memory_db.fetch_dicts("SELECT * FROM prospect_sources WHERE prospect_id = ?", (result.imported_prospects[0].id,))
        assert len(sources) == 1

    def test_execute_without_campaign_rejected(self, memory_db):
        org_repo = OrganizationRepository(memory_db)
        campaign_repo = CampaignRepository(memory_db)
        prospect_repo = ProspectRepository(memory_db)
        rr_repo = ResearchRunRepository(memory_db)

        org = org_repo.save(Organization(name="Org Exec", slug="org-exec"))
        parser = RuleBasedSearchIntentParser()
        planner = DefaultSearchPlanner(StaticLocationResolver())
        provider = OvertureDiscoveryProvider(MockDiscoveryGateway())
        prospect_service = ProspectService(prospect_repo)
        orchestrator = DiscoveryOrchestrator([provider], prospect_service, rr_repo, campaign_repo)

        search_service = SearchService(parser, planner, orchestrator, campaign_repo)

        intent = parser.parse(org.id, None, "dentistas en Miami")
        plan = planner.plan(intent)

        with pytest.raises(SearchPlanningError, match="requires an active campaign_id"):
            search_service.execute_search(org.id, None, plan)

    def test_campaign_status_policy(self, memory_db):
        org_repo = OrganizationRepository(memory_db)
        campaign_repo = CampaignRepository(memory_db)
        prospect_repo = ProspectRepository(memory_db)
        rr_repo = ResearchRunRepository(memory_db)

        org = org_repo.save(Organization(name="Org Policy", slug="org-policy"))
        camp_draft = campaign_repo.save(org.id, Campaign(name="Draft Camp", status=CampaignStatus.DRAFT))
        camp_active = campaign_repo.save(org.id, Campaign(name="Active Camp", status=CampaignStatus.ACTIVE))

        parser = RuleBasedSearchIntentParser()
        planner = DefaultSearchPlanner(StaticLocationResolver())
        provider = OvertureDiscoveryProvider(MockDiscoveryGateway())
        prospect_service = ProspectService(prospect_repo)
        orchestrator = DiscoveryOrchestrator([provider], prospect_service, rr_repo, campaign_repo)

        search_service = SearchService(parser, planner, orchestrator, campaign_repo)

        plan_draft = planner.plan(parser.parse(org.id, camp_draft.id, "dentistas en Miami"))
        plan_active = planner.plan(parser.parse(org.id, camp_active.id, "dentistas en Miami"))

        # Draft execution rejected
        with pytest.raises(TenantAccessError, match="status is 'draft'"):
            search_service.execute_search(org.id, camp_draft.id, plan_draft)

        # Active execution allowed
        res = search_service.execute_search(org.id, camp_active.id, plan_active)
        assert res.total_imported_prospects == 1

    def test_max_results_global_enforcement(self, memory_db):
        org_repo = OrganizationRepository(memory_db)
        campaign_repo = CampaignRepository(memory_db)
        prospect_repo = ProspectRepository(memory_db)
        rr_repo = ResearchRunRepository(memory_db)

        org = org_repo.save(Organization(name="Org Max", slug="org-max"))
        camp = campaign_repo.save(org.id, Campaign(name="Max Camp", status=CampaignStatus.ACTIVE))

        # 20 items returned by mock
        items = [
            DiscoveredBusiness(overture_id=f"ov-{i}", name=f"Clinic {i}", website_url=f"https://clinic{i}.com")
            for i in range(20)
        ]
        gateway = MockDiscoveryGateway(items)
        provider = OvertureDiscoveryProvider(gateway)
        prospect_service = ProspectService(prospect_repo)
        orchestrator = DiscoveryOrchestrator([provider], prospect_service, rr_repo, campaign_repo)

        plan = SearchPlan(
            organization_id=org.id,
            campaign_id=camp.id,
            tasks=[DiscoveryTask(provider="overture", category="dentist", city="Miami", limit=100)],
        )

        res = orchestrator.execute_plan(plan, max_results_override=5)
        assert res.total_imported_prospects == 5
        assert len(res.imported_prospects) == 5
