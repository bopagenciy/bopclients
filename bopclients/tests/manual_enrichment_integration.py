"""Manual live integration test for BopClients P3.1: Live Validation Closure."""

import time
from bopclients.domain.organization import Organization
from bopclients.domain.campaign import Campaign
from bopclients.domain.service import Service
from bopclients.domain.icp import IdealCustomerProfile
from bopclients.domain.prospect import Prospect
from bopclients.domain.campaign_prospect import CampaignProspect
from bopclients.domain.enums import CampaignStatus
from bopclients.application.enrichment_dto import EnrichmentSnapshot
from bopclients.application.search_intent_parser import RuleBasedSearchIntentParser
from bopclients.application.search_planner import DefaultSearchPlanner
from bopclients.application.search_service import SearchService
from bopclients.application.discovery_orchestrator import DiscoveryOrchestrator
from bopclients.infrastructure.location.static_location_resolver import StaticLocationResolver
from bopclients.infrastructure.providers.overture_provider import OvertureDiscoveryProvider
from bopclients.infrastructure.providers.forge_enrichment_provider import ForgeEnrichmentProvider
from bopclients.infrastructure.gateways.forge_gateway import (
    ForgeDiscoveryGatewayAdapter,
    ForgeEnrichmentGatewayAdapter,
)
from bopclients.application.signal_detectors.detectors import (
    NoWebsiteDetector,
    WebsiteUnreachableDetector,
    WebsiteSlowDetector,
    NoSSLDetector,
    NoChatbotDetector,
    NoBookingDetector,
    NoAnalyticsDetector,
)
from bopclients.application.opportunity_scorer import RuleBasedOpportunityScorer
from bopclients.application.enrichment_orchestrator import EnrichmentOrchestrator
from bopclients.application.enrichment_service import EnrichmentService
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.infrastructure.repositories.enrichment_result_repository import EnrichmentResultRepository
from bopclients.infrastructure.repositories.service_repository import ServiceRepository
from bopclients.infrastructure.repositories.icp_repository import ICPRepository
from bopclients.application.prospect_service import ProspectService
from bopclients.infrastructure.db.migrations import run_p1_migrations
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend


def run_manual_enrichment_integration():
    """Manual integration test: 2 Discovered Miami Dentists + 1 Controlled Technical Validation Prospect."""
    start_time = time.time()
    # Always create fresh isolated in-memory DB
    db = ForgeDB(_SQLiteBackend(db_path=":memory:"))
    run_p1_migrations(db)

    org_repo = OrganizationRepository(db)
    campaign_repo = CampaignRepository(db)
    prospect_repo = ProspectRepository(db)
    rr_repo = ResearchRunRepository(db)
    res_repo = EnrichmentResultRepository(db)
    service_repo = ServiceRepository(db)
    icp_repo = ICPRepository(db)

    org = org_repo.save(Organization(name="Growth AI Agency", slug="growth-ai"))
    camp = campaign_repo.save(org.id, Campaign(name="Miami Dentists Outreach P3", status=CampaignStatus.ACTIVE))

    # Configure Organization Services (WHAT WE SELL)
    s1 = service_repo.save(org.id, Service(name="Web Development", category="web_development", description="Modern website & redesign"))
    s2 = service_repo.save(org.id, Service(name="Automation & AI Chatbot", category="automation", description="Automated booking & live AI assistant"))
    s3 = service_repo.save(org.id, Service(name="Digital Marketing", category="marketing", description="SEO & Analytics tracking"))

    # Configure Organization ICP
    icp = icp_repo.save(org.id, IdealCustomerProfile(name="Dental Clinics", industries=["dentist"], countries=["US"]))

    # Step 1: DISCOVERED PROSPECTS (Max 2 real Miami Dentists from Overture)
    parser = RuleBasedSearchIntentParser()
    planner = DefaultSearchPlanner(StaticLocationResolver())
    disc_gateway = ForgeDiscoveryGatewayAdapter()
    disc_provider = OvertureDiscoveryProvider(disc_gateway)
    prospect_service = ProspectService(prospect_repo)
    disc_orchestrator = DiscoveryOrchestrator([disc_provider], prospect_service, rr_repo, campaign_repo)

    search_service = SearchService(parser, planner, disc_orchestrator, campaign_repo)
    intent = search_service.parse_search_intent(org.id, camp.id, "Busca dentistas en Miami")
    plan = search_service.plan_search(intent)
    
    print("\n[MANUAL INTEGRATION TEST P3.1 - LIVE VALIDATION]")
    print(f"1. Discovery Phase: Executing Overture search for max 2 prospects...")
    disc_result = disc_orchestrator.execute_plan(plan, max_results_override=2)
    discovered_prospects = prospect_repo.list_prospects_by_campaign(org.id, camp.id)
    print(f"   DISCOVERED PROSPECTS IMPORTED: {len(discovered_prospects)}")

    # Step 2: CONTROLLED VALIDATION PROSPECT (1 site with SUCCESS status to verify positive signal detectors)
    controlled_p = prospect_repo.save_prospect(
        org.id,
        Prospect(
            name="Miami Smile Center (Technical Validation)",
            website_url="https://miamismilevalidationtest.com",
            phone="305-555-9999",
            industry="dentist",
            country="US",
        )
    )
    prospect_repo.add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=controlled_p.id))

    # Pre-populate successful enrichment snapshot in DB to simulate HTTP 200 homepage inspection
    from bopclients.domain.enrichment_result import EnrichmentResult
    res_repo.save(
        org.id,
        EnrichmentResult(
            organization_id=org.id,
            prospect_id=controlled_p.id,
            provider="forge",
            status="success",
            website_url="https://miamismilevalidationtest.com",
            data={
                "emails": ["contact@miamismilevalidationtest.com"],
                "technologies": ["PHP"],
                "cms": None,
                "ssl_valid": True,
                "response_time_ms": 2200.0,
                "http_status": 200,
                "raw_html": "<html><body><h1>Miami Smile Center</h1><p>Call us for appointments</p></body></html>"
            }
        )
    )
    print(f"   CONTROLLED VALIDATION PROSPECTS ADDED: 1")

    # Step 3: Configure Hybrid Enrichment Pipeline for Live + Controlled Validation
    forge_enrich_provider = ForgeEnrichmentProvider(ForgeEnrichmentGatewayAdapter(db_pool=db))

    class HybridEnrichmentProvider:
        @property
        def name(self) -> str:
            return "forge"

        def enrich(self, org_id: str, prospect: Prospect) -> EnrichmentSnapshot:
            if prospect.id == controlled_p.id:
                return EnrichmentSnapshot(
                    prospect_id=prospect.id,
                    website_url=prospect.website_url,
                    website_reachable=True,
                    scrape_status="success",
                    http_status=200,
                    response_time_ms=2200.0,
                    ssl_valid=True,
                    emails=["contact@miamismilevalidationtest.com"],
                    technologies=["PHP"],
                    cms=None,
                    has_chatbot=False,
                    has_booking=False,
                    has_analytics=False,
                )
            return forge_enrich_provider.enrich(org_id, prospect)

    enrich_provider = HybridEnrichmentProvider()
    detectors = [
        NoWebsiteDetector(),
        WebsiteUnreachableDetector(),
        WebsiteSlowDetector(),
        NoSSLDetector(),
        NoChatbotDetector(),
        NoBookingDetector(),
        NoAnalyticsDetector(),
    ]
    scorer = RuleBasedOpportunityScorer()

    enrich_orchestrator = EnrichmentOrchestrator(
        enrich_provider, detectors, scorer, prospect_repo, rr_repo, res_repo, service_repo, icp_repo
    )
    enrich_service = EnrichmentService(enrich_orchestrator, campaign_repo, prospect_repo)

    print(f"2. Enrichment & Opportunity Scoring Phase for Campaign '{camp.name}'...")
    analysis_results = enrich_service.analyze_campaign(org.id, camp.id, limit=10)

    duration = time.time() - start_time
    print(f"\n[ENRICHMENT SUMMARY]")
    print(f"  - Command: python -m bopclients.tests.manual_enrichment_integration")
    print(f"  - Duration: {duration:.2f}s")
    print(f"  - DISCOVERED PROSPECTS: {len(discovered_prospects)}")
    print(f"  - CONTROLLED VALIDATION PROSPECTS: 1")
    print(f"  - TOTAL ANALYZED: {len(analysis_results)}")

    for idx, res in enumerate(analysis_results, 1):
        p = prospect_repo.get_prospect_by_id(org.id, res.prospect_id)
        latest_res = res_repo.get_latest(org.id, res.prospect_id)
        raw_data = latest_res.data if latest_res else {}

        p_name = p.name if p else "Unknown"
        p_url = p.website_url if p else "None"
        is_controlled = (p.id == controlled_p.id)
        tag = " [CONTROLLED VALIDATION]" if is_controlled else " [DISCOVERED]"

        print(f"\n--- PROSPECT {idx}{tag} ---")
        print(f"  Name: {p_name}")
        print(f"  Website: {p_url}")
        print(f"  Enrichment Status: {res.enrichment_status}")
        print(f"  HTTP Status: {raw_data.get('http_status')}")
        print(f"  Website Reachable: {raw_data.get('http_status') == 200 or res.enrichment_status == 'success'}")
        print(f"  Response Time: {raw_data.get('response_time_ms')} ms")
        print(f"  SSL Valid: {raw_data.get('ssl_valid')}")
        print(f"  Technologies: {raw_data.get('technologies')}")
        print(f"  CMS: {raw_data.get('cms')}")
        print(f"  Has Chatbot: {False if is_controlled else None}")
        print(f"  Has Booking: {False if is_controlled else None}")
        print(f"  Has Analytics: {False if is_controlled else None}")
        print(f"  Signals Detected ({len(res.signals_detected)}): {[s.type for s in res.signals_detected]}")
        for s in res.signals_detected:
            print(f"    * Signal '{s.type}' (Conf: {s.confidence}) -> Evidence: {s.evidence}")
        if res.lead_score:
            print(f"  Opportunity Score (v1.1): {res.lead_score.score}/100")
            print(f"  Score Explanation: {res.lead_score.explanation}")
        print(f"  Recommended Services ({len(res.service_recommendations)}):")
        for rec in res.service_recommendations:
            print(f"    - {rec.service_name} (Relevance: {rec.relevance_score}/100) -> {rec.reasoning}")


if __name__ == "__main__":
    run_manual_enrichment_integration()
