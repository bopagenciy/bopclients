"""Tests for Phase P30.5B: Campaign, ICP & Target Market Context in Discovery.

Covers all 15 required verification cases:
1. Campaign resolves its ICP
2. ICP industry defaults applied when prompt has no industries
3. Explicit user industry override preserves user input
4. Negated category is NOT reintroduced from ICP
5. ICP company sizes preserved (exact buckets + continuous approximation + planner warning)
6. Single Target Market default context applied
7. Multiple Target Markets disambiguation / warning
8. Explicit market selection via target_market_id
9. Cross-tenant market ID rejected with TenantAccessError
10. Explicit location override clears conflicting region/zip/radius
11. Radius value/unit (25 miles) retained in DiscoveryTask
12. Market language default applied when omitted in prompt
13. Existing standalone Discovery works without campaign/ICP
14. Intent -> Plan context consistency
15. Zero external calls (offline unit verification)
"""

import pytest
from bopclients.domain.search_intent import SearchIntent
from bopclients.domain.organization import Organization
from bopclients.domain.campaign import Campaign
from bopclients.domain.enums import CampaignStatus
from bopclients.domain.exceptions import TenantAccessError, SearchPlanningError
from bopclients.domain.icp import IdealCustomerProfile, TargetMarket
from bopclients.application.search_dto import DiscoveryTask, SearchPlan
from bopclients.application.search_intent_parser import RuleBasedSearchIntentParser
from bopclients.application.search_planner import DefaultSearchPlanner
from bopclients.application.search_service import SearchService
from bopclients.application.discovery_orchestrator import DiscoveryOrchestrator
from bopclients.infrastructure.location.static_location_resolver import StaticLocationResolver
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.infrastructure.repositories.icp_repository import ICPRepository
from bopclients.application.prospect_service import ProspectService
from bopclients.infrastructure.db.migrations import run_p1_migrations
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend


@pytest.fixture
def memory_db():
    db = ForgeDB(_SQLiteBackend(db_path=":memory:"))
    run_p1_migrations(db)
    return db


@pytest.fixture
def service_env(memory_db):
    org_repo = OrganizationRepository(memory_db)
    campaign_repo = CampaignRepository(memory_db)
    icp_repo = ICPRepository(memory_db)
    prospect_repo = ProspectRepository(memory_db)
    rr_repo = ResearchRunRepository(memory_db)

    parser = RuleBasedSearchIntentParser()
    planner = DefaultSearchPlanner(location_resolver=StaticLocationResolver())
    prospect_service = ProspectService(prospect_repo)
    orchestrator = DiscoveryOrchestrator([], prospect_service, rr_repo, campaign_repo)

    search_service = SearchService(
        intent_parser=parser,
        search_planner=planner,
        orchestrator=orchestrator,
        campaign_repo=campaign_repo,
        icp_repo=icp_repo,
    )

    org = org_repo.save(Organization(name="Bop Agencia", slug="bop-agencia"))
    org_other = org_repo.save(Organization(name="Other Corp", slug="other-corp"))

    return {
        "org": org,
        "org_other": org_other,
        "campaign_repo": campaign_repo,
        "icp_repo": icp_repo,
        "search_service": search_service,
        "planner": planner,
    }


class TestCampaignICPContextDiscovery:
    def test_case_01_campaign_resolves_icp(self, service_env):
        """1. Campaign resolves its ICP."""
        org = service_env["org"]
        icp_repo = service_env["icp_repo"]
        campaign_repo = service_env["campaign_repo"]
        svc = service_env["search_service"]

        icp = icp_repo.save(
            org.id,
            IdealCustomerProfile(
                name="Asociaciones Medicas",
                industries=["salud", "asociaciones medicas"],
                company_sizes=["1-10", "11-50"],
            ),
        )
        camp = campaign_repo.save(
            org.id,
            Campaign(
                name="Camp Asociaciones",
                icp_id=icp.id,
                status=CampaignStatus.ACTIVE,
            ),
        )

        intent = svc.parse_search_intent(
            org_id=org.id,
            campaign_id=camp.id,
            raw_query="buscar prospectos",
        )
        assert intent.campaign_id == camp.id
        # Specific association is preserved and generic healthcare correctly superseded
        assert "medical_association" in intent.industries

    def test_case_02_icp_industry_defaults_when_omitted(self, service_env):
        """2. ICP industry defaults applied when prompt has no industries."""
        org = service_env["org"]
        icp_repo = service_env["icp_repo"]
        campaign_repo = service_env["campaign_repo"]
        svc = service_env["search_service"]

        icp = icp_repo.save(
            org.id,
            IdealCustomerProfile(
                name="Tech ICP",
                industries=["software", "fintech"],
            ),
        )
        camp = campaign_repo.save(
            org.id,
            Campaign(name="Tech Camp", icp_id=icp.id, status=CampaignStatus.ACTIVE),
        )

        intent = svc.parse_search_intent(
            org_id=org.id,
            campaign_id=camp.id,
            raw_query="empresas en Miami",
        )
        assert intent.industries == ["software", "fintech"]

    def test_case_03_explicit_user_industry_override(self, service_env):
        """3. Explicit user industry override preserves user input and does not inherit ICP industries."""
        org = service_env["org"]
        icp_repo = service_env["icp_repo"]
        campaign_repo = service_env["campaign_repo"]
        svc = service_env["search_service"]

        icp = icp_repo.save(
            org.id,
            IdealCustomerProfile(
                name="Health ICP",
                industries=["hospitales", "clinicas"],
            ),
        )
        camp = campaign_repo.save(
            org.id,
            Campaign(name="Health Camp", icp_id=icp.id, status=CampaignStatus.ACTIVE),
        )

        intent = svc.parse_search_intent(
            org_id=org.id,
            campaign_id=camp.id,
            raw_query="dentistas en Miami",
        )
        # Should contain parsed user industry/category, not the ICP defaults
        assert "dentist" in intent.business_categories or "dentist" in intent.industries
        assert "hospital" not in intent.industries
        assert "clinic" not in intent.industries

    def test_case_04_negated_category_not_reintroduced_from_icp(self, service_env):
        """4. Negated category is NOT reintroduced from ICP."""
        org = service_env["org"]
        icp_repo = service_env["icp_repo"]
        campaign_repo = service_env["campaign_repo"]
        svc = service_env["search_service"]

        icp = icp_repo.save(
            org.id,
            IdealCustomerProfile(
                name="Med ICP",
                industries=["asociaciones medicas", "clinicas"],
            ),
        )
        camp = campaign_repo.save(
            org.id,
            Campaign(name="Med Camp", icp_id=icp.id, status=CampaignStatus.ACTIVE),
        )

        # Prompt negates clinics: "sin clinicas"
        intent = svc.parse_search_intent(
            org_id=org.id,
            campaign_id=camp.id,
            raw_query="asociaciones medicas sin clinicas",
        )
        assert "clinic" in intent.negative_keywords
        # "clinic" should NOT be in positive industries or business categories
        assert "clinic" not in intent.industries
        assert "clinic" not in intent.business_categories
        assert "medical_association" in intent.industries

    def test_case_05_icp_company_sizes_preserved(self, service_env):
        """5. ICP company sizes preserved (buckets + continuous range + planner warning)."""
        org = service_env["org"]
        icp_repo = service_env["icp_repo"]
        campaign_repo = service_env["campaign_repo"]
        svc = service_env["search_service"]

        icp = icp_repo.save(
            org.id,
            IdealCustomerProfile(
                name="SME ICP",
                company_sizes=["1-10", "11-50", "51-200"],
            ),
        )
        camp = campaign_repo.save(
            org.id,
            Campaign(name="SME Camp", icp_id=icp.id, status=CampaignStatus.ACTIVE),
        )

        intent = svc.parse_search_intent(
            org_id=org.id,
            campaign_id=camp.id,
            raw_query="empresas de software",
        )
        assert intent.company_sizes == ["1-10", "11-50", "51-200"]
        assert intent.company_size_min == 1
        assert intent.company_size_max == 200

        plan = svc.plan_search(intent)
        warning_codes = [w.code for w in plan.warnings]
        assert "EXACT_SIZE_FILTER_REQUIRES_ENRICHMENT" in warning_codes

    def test_case_06_single_target_market_default(self, service_env):
        """6. Single Target Market default context applied."""
        org = service_env["org"]
        icp_repo = service_env["icp_repo"]
        campaign_repo = service_env["campaign_repo"]
        svc = service_env["search_service"]

        tm = TargetMarket(
            country="CO",
            region="Valle del Cauca",
            city="Cali",
            radius_miles=25.0,
            language="es",
        )
        icp = icp_repo.save(
            org.id,
            IdealCustomerProfile(
                name="Cali ICP",
                target_markets=[tm],
            ),
        )
        camp = campaign_repo.save(
            org.id,
            Campaign(name="Cali Camp", icp_id=icp.id, status=CampaignStatus.ACTIVE),
        )

        intent = svc.parse_search_intent(
            org_id=org.id,
            campaign_id=camp.id,
            raw_query="asociaciones medicas",
        )
        assert intent.cities == ["Cali"]
        assert intent.regions == ["Valle del Cauca"]
        assert intent.countries == ["CO"]
        assert intent.radius_miles == 25.0
        assert intent.languages == ["es"]

    def test_case_07_multiple_target_markets_disambiguation(self, service_env):
        """7. Multiple Target Markets require selection / matching (matches query or warns)."""
        org = service_env["org"]
        icp_repo = service_env["icp_repo"]
        campaign_repo = service_env["campaign_repo"]
        svc = service_env["search_service"]

        tm_cali = TargetMarket(country="CO", city="Cali", radius_miles=25.0, language="es")
        tm_bogota = TargetMarket(country="CO", city="Bogota", radius_miles=15.0, language="es")

        icp = icp_repo.save(
            org.id,
            IdealCustomerProfile(
                name="Multi Market ICP",
                target_markets=[tm_cali, tm_bogota],
            ),
        )
        camp = campaign_repo.save(
            org.id,
            Campaign(name="Multi Camp", icp_id=icp.id, status=CampaignStatus.ACTIVE),
        )

        # 7a. Prompt matches Bogota deterministically
        intent_bogota = svc.parse_search_intent(
            org_id=org.id,
            campaign_id=camp.id,
            raw_query="asociaciones en Bogota",
        )
        assert intent_bogota.cities == ["Bogota"]
        assert intent_bogota.radius_miles == 15.0

        # 7b. Prompt without location does NOT arbitrarily default to first market; requires selection
        intent_no_loc = svc.parse_search_intent(
            org_id=org.id,
            campaign_id=camp.id,
            raw_query="asociaciones medicas",
        )
        assert intent_no_loc.target_market_id is None
        assert intent_no_loc.cities == []
        assert "MULTIPLE_TARGET_MARKETS_REQUIRE_SELECTION" in intent_no_loc.warnings

        plan = svc.plan_search(intent_no_loc)
        warning_codes = [w.code for w in plan.warnings]
        assert "MULTIPLE_TARGET_MARKETS_REQUIRE_SELECTION" in warning_codes

        # Fail-closed: execution is blocked without market selection
        with pytest.raises(SearchPlanningError, match="Multiple target markets are configured"):
            svc.execute_search(org.id, camp.id, plan)

    def test_case_07c_multiple_markets_same_city_requires_selection(self, service_env):
        """7c. Multiple target markets in the same city require explicit selection."""
        org = service_env["org"]
        icp_repo = service_env["icp_repo"]
        campaign_repo = service_env["campaign_repo"]
        svc = service_env["search_service"]

        tm_bogota_north = TargetMarket(country="CO", city="Bogota", postal_code="110111", radius_miles=10.0)
        tm_bogota_south = TargetMarket(country="CO", city="Bogota", postal_code="110222", radius_miles=20.0)

        icp = icp_repo.save(
            org.id,
            IdealCustomerProfile(
                name="Bogota Dual ICP",
                target_markets=[tm_bogota_north, tm_bogota_south],
            ),
        )
        camp = campaign_repo.save(
            org.id,
            Campaign(name="Bogota Dual Camp", icp_id=icp.id, status=CampaignStatus.ACTIVE),
        )

        intent = svc.parse_search_intent(
            org_id=org.id,
            campaign_id=camp.id,
            raw_query="asociaciones en Bogota",
        )
        # Multiple markets matched "Bogota" -> cannot disambiguate -> require explicit selection
        assert intent.target_market_id is None
        assert "MULTIPLE_TARGET_MARKETS_REQUIRE_SELECTION" in intent.warnings


    def test_case_08_explicit_market_selection(self, service_env):
        """8. Explicit market selection via target_market_id."""
        org = service_env["org"]
        icp_repo = service_env["icp_repo"]
        campaign_repo = service_env["campaign_repo"]
        svc = service_env["search_service"]

        tm1 = TargetMarket(country="CO", city="Cali", radius_miles=25.0, language="es")
        tm2 = TargetMarket(country="CO", city="Medellin", radius_miles=30.0, language="es")

        icp = icp_repo.save(
            org.id,
            IdealCustomerProfile(name="Markets ICP", target_markets=[tm1, tm2]),
        )
        camp = campaign_repo.save(
            org.id,
            Campaign(name="Markets Camp", icp_id=icp.id, status=CampaignStatus.ACTIVE),
        )

        intent = svc.parse_search_intent(
            org_id=org.id,
            campaign_id=camp.id,
            raw_query="asociaciones medicas",
            target_market_id=tm2.id,
        )
        assert intent.target_market_id == tm2.id
        assert intent.cities == ["Medellin"]
        assert intent.radius_miles == 30.0

    def test_case_09_cross_tenant_market_id_rejected(self, service_env):
        """9. Cross-tenant market ID rejected with TenantAccessError."""
        org = service_env["org"]
        org_other = service_env["org_other"]
        icp_repo = service_env["icp_repo"]
        campaign_repo = service_env["campaign_repo"]
        svc = service_env["search_service"]

        tm_other = TargetMarket(country="US", city="New York")
        icp_other = icp_repo.save(
            org_other.id,
            IdealCustomerProfile(name="Other ICP", target_markets=[tm_other]),
        )

        icp_org = icp_repo.save(
            org.id,
            IdealCustomerProfile(name="Org ICP"),
        )
        camp = campaign_repo.save(
            org.id,
            Campaign(name="Camp Org", icp_id=icp_org.id, status=CampaignStatus.ACTIVE),
        )

        with pytest.raises(TenantAccessError):
            svc.parse_search_intent(
                org_id=org.id,
                campaign_id=camp.id,
                raw_query="dentistas",
                target_market_id=tm_other.id,
            )

    def test_case_10_explicit_location_override_clears_conflicting_fields(self, service_env):
        """10. Explicit location override clears conflicting region/zip/radius."""
        org = service_env["org"]
        icp_repo = service_env["icp_repo"]
        campaign_repo = service_env["campaign_repo"]
        svc = service_env["search_service"]

        tm = TargetMarket(
            country="CO",
            region="Valle del Cauca",
            city="Cali",
            postal_code="760001",
            radius_miles=25.0,
            language="es",
        )
        icp = icp_repo.save(
            org.id,
            IdealCustomerProfile(name="Cali ICP", target_markets=[tm]),
        )
        camp = campaign_repo.save(
            org.id,
            Campaign(name="Cali Camp", icp_id=icp.id, status=CampaignStatus.ACTIVE),
        )

        # User explicitly queries for Bogota
        intent = svc.parse_search_intent(
            org_id=org.id,
            campaign_id=camp.id,
            raw_query="asociaciones medicas en Bogota",
        )
        assert intent.cities == ["Bogota"]
        # Conflicting Cali region, zip, and radius must be cleared
        assert intent.regions == []
        assert intent.radius_miles is None
        # Country remains CO
        assert intent.countries == ["CO"]

    def test_case_11_radius_miles_retained_in_discovery_task(self, service_env):
        """11. Radius value/unit (25 miles) retained in DiscoveryTask."""
        org = service_env["org"]
        icp_repo = service_env["icp_repo"]
        campaign_repo = service_env["campaign_repo"]
        svc = service_env["search_service"]

        tm = TargetMarket(
            country="CO",
            city="Cali",
            radius_miles=25.0,
            language="es",
        )
        icp = icp_repo.save(
            org.id,
            IdealCustomerProfile(name="Cali ICP", target_markets=[tm]),
        )
        camp = campaign_repo.save(
            org.id,
            Campaign(name="Cali Camp", icp_id=icp.id, status=CampaignStatus.ACTIVE),
        )

        intent = svc.parse_search_intent(
            org_id=org.id,
            campaign_id=camp.id,
            raw_query="asociaciones medicas",
        )
        assert intent.radius_miles == 25.0

        plan = svc.plan_search(intent)
        assert len(plan.tasks) > 0
        for task in plan.tasks:
            assert task.radius_miles == 25.0

    def test_case_12_market_language_default(self, service_env):
        """12. Market language default applied when omitted in prompt."""
        org = service_env["org"]
        icp_repo = service_env["icp_repo"]
        campaign_repo = service_env["campaign_repo"]
        svc = service_env["search_service"]

        tm = TargetMarket(country="CO", city="Cali", language="es")
        icp = icp_repo.save(
            org.id,
            IdealCustomerProfile(name="Spanish ICP", target_markets=[tm]),
        )
        camp = campaign_repo.save(
            org.id,
            Campaign(name="Spanish Camp", icp_id=icp.id, status=CampaignStatus.ACTIVE),
        )

        intent = svc.parse_search_intent(
            org_id=org.id,
            campaign_id=camp.id,
            raw_query="prospectos",
        )
        assert intent.languages == ["es"]

    def test_case_13_existing_standalone_discovery_works(self, service_env):
        """13. Existing standalone Discovery works without campaign/ICP."""
        org = service_env["org"]
        svc = service_env["search_service"]

        intent = svc.parse_search_intent(
            org_id=org.id,
            campaign_id=None,
            raw_query="dentists in Miami",
        )
        assert intent.campaign_id is None
        assert intent.target_market_id is None
        assert "dentist" in intent.business_categories
        assert "Miami" in intent.cities

        plan = svc.plan_search(intent)
        assert len(plan.tasks) > 0
        assert plan.tasks[0].city == "Miami"

    def test_case_14_intent_to_plan_context_consistency(self, service_env):
        """14. Intent -> Plan context consistency."""
        org = service_env["org"]
        svc = service_env["search_service"]

        intent = SearchIntent(
            organization_id=org.id,
            target_market_id="tm-custom-123",
            raw_query="clinics in Orlando",
            cities=["Orlando"],
            radius_miles=35.0,
            company_sizes=["10-50"],
        )
        plan = svc.plan_search(intent)
        assert plan.organization_id == org.id
        assert len(plan.tasks) > 0
        assert plan.tasks[0].city == "Orlando"
        assert plan.tasks[0].radius_miles == 35.0
        # Warning present for company size enrichment requirement
        assert any(w.code == "EXACT_SIZE_FILTER_REQUIRES_ENRICHMENT" for w in plan.warnings)

    def test_case_15_zero_external_calls(self, service_env):
        """15. Zero external calls (offline unit verification)."""
        # SearchService and DiscoveryOrchestrator were initialized with empty providers list
        # and mock StaticLocationResolver; verify no provider tasks were executed against external APIs
        svc = service_env["search_service"]
        assert len(svc.orchestrator.providers) == 0

    def test_case_16_api_intents_and_plans_endpoint_context(self, memory_db):
        """16. API integration: intents and plans endpoints handle campaign and target market context."""
        from starlette.testclient import TestClient
        from bopclients.api.app import create_bopclients_api_app
        from bopclients.runtime.settings import RuntimeSettings
        from bopclients.runtime.container import build_runtime_container
        from bopclients.domain.organization import OrganizationMember
        from bopclients.domain.enums import MemberRole

        settings = RuntimeSettings(
            database_url=":memory:",
            auth_signing_key="unit-test-signing-key-minimum-32-chars-long!",
        )
        container = build_runtime_container(settings, db=memory_db)
        app = create_bopclients_api_app(container)
        client = TestClient(app)

        # Setup user and org
        user = container.auth_service.register_user(
            email="test_user@bopagencia.local",
            name="Test User",
            password="Password123!",
        )
        import uuid
        org = Organization(
            id=str(uuid.uuid4()),
            bop_organization_id=str(uuid.uuid4()),
            name="Bop Agencia",
            slug="bop-agencia-api",
        )
        container.org_repo.save(org)
        container.org_repo.add_member(
            OrganizationMember(
                organization_id=org.id,
                user_id=user.id,
                role="OWNER",
            )
        )
        login_res = container.auth_service.authenticate(email="test_user@bopagencia.local", password="Password123!")
        token = login_res.access_token
        headers = {"Authorization": f"Bearer {token}", "X-Bop-Organization-Id": org.bop_organization_id}

        # Create ICP with Target Market
        tm = TargetMarket(country="CO", city="Cali", radius_miles=25.0, language="es")
        icp = container.icp_repo.save(
            org.id,
            IdealCustomerProfile(
                name="Asociaciones ICP",
                industries=["asociaciones medicas"],
                company_sizes=["1-10", "11-50"],
                target_markets=[tm],
            ),
        )
        camp = container.campaign_repo.save(
            org.id,
            Campaign(name="Asociaciones Camp", icp_id=icp.id, status=CampaignStatus.ACTIVE),
        )

        # Test POST /api/v1/discovery/intents
        res = client.post(
            "/api/v1/discovery/intents",
            headers=headers,
            json={
                "campaign_id": camp.id,
                "raw_query": "asociaciones medicas",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["campaign_id"] == camp.id
        assert data["target_market_id"] == tm.id
        assert data["radius_miles"] == 25.0
        assert data["company_sizes"] == ["1-10", "11-50"]
        assert data["cities"] == ["Cali"]

        # Test POST /api/v1/discovery/plans
        plan_res = client.post(
            "/api/v1/discovery/plans",
            headers=headers,
            json=data,
        )
        assert plan_res.status_code == 200
        plan_data = plan_res.json()
        assert len(plan_data["tasks"]) > 0
        assert plan_data["tasks"][0]["query_params"]["city"] == "Cali"
        assert plan_data["tasks"][0]["query_params"]["radius_miles"] == 25.0

    def test_case_17_openapi_schema_properties(self):
        """17. OpenAPI schema properties synchronization check."""
        import json
        with open("apps/web/openapi_p19.json", encoding="utf-8") as f:
            snap = json.load(f)

        schemas = snap.get("components", {}).get("schemas", {})

        # SearchIntentRequest
        req_props = schemas.get("SearchIntentRequest", {}).get("properties", {})
        assert "target_market_id" in req_props
        assert "campaign_id" in req_props
        assert "raw_query" in req_props

        # SearchIntentResponse
        resp_props = schemas.get("SearchIntentResponse", {}).get("properties", {})
        assert "target_market_id" in resp_props
        assert "radius_miles" in resp_props
        assert "company_sizes" in resp_props
        assert "negative_keywords" in resp_props

        # SearchPlanRequest
        plan_req_props = schemas.get("SearchPlanRequest", {}).get("properties", {})
        assert "target_market_id" in plan_req_props
        assert "radius_miles" in plan_req_props
        assert "company_sizes" in plan_req_props
        assert "negative_keywords" in plan_req_props

    def test_case_18_company_size_warning_truthful(self, service_env):
        """18. Truthful company size warning and non-contiguous bucket preservation."""
        org = service_env["org"]
        icp_repo = service_env["icp_repo"]
        campaign_repo = service_env["campaign_repo"]
        svc = service_env["search_service"]

        # Non-contiguous bucket set
        icp = icp_repo.save(
            org.id,
            IdealCustomerProfile(
                name="Disjoint ICP",
                company_sizes=["1-10", "500-1000"],
            ),
        )
        camp = campaign_repo.save(
            org.id,
            Campaign(name="Disjoint Camp", icp_id=icp.id, status=CampaignStatus.ACTIVE),
        )

        intent = svc.parse_search_intent(
            org_id=org.id,
            campaign_id=camp.id,
            raw_query="empresas de software",
        )
        # Exact buckets preserved
        assert intent.company_sizes == ["1-10", "500-1000"]
        # Min/max outer approximation
        assert intent.company_size_min == 1
        assert intent.company_size_max == 1000

        plan = svc.plan_search(intent)
        warnings = [w for w in plan.warnings if "size" in w.message.lower() or w.code == "EXACT_SIZE_FILTER_REQUIRES_ENRICHMENT"]
        assert len(warnings) > 0
        w = warnings[0]
        # Truthful warning: does NOT claim live Overture supports employee filtering
        assert "not support employee-size filtering" in w.message
        assert w.details.get("provider_filtering_supported") is False
