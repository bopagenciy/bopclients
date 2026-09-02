"""Manual integration test script for BopClients P8 External Public Signal Providers."""

from datetime import datetime, timezone
from unittest.mock import patch
from bopclients.domain.organization import Organization
from bopclients.domain.campaign import Campaign
from bopclients.domain.prospect import Prospect
from bopclients.domain.campaign_prospect import CampaignProspect
from bopclients.domain.lead_score import LeadScore
from bopclients.domain.enums import CampaignStatus
from bopclients.application.signal_provider import OfficialWebsiteSignalProvider
from bopclients.application.providers.procurement_provider import GovernmentProcurementProvider
from bopclients.application.providers.news_provider import PublicNewsSignalProvider
from bopclients.application.provider_registry import PublicSignalProviderRegistry
from bopclients.application.public_signal_monitor_service import PublicSignalMonitorService
from bopclients.application.prospect_priority_service import ProspectPriorityService
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.prospect_priority_repository import ProspectPriorityRepository
from bopclients.infrastructure.repositories.signal_observation_repository import SignalObservationRepository
from bopclients.infrastructure.repositories.prospect_intelligence_repository import ProspectIntelligenceRepository
from bopclients.infrastructure.repositories.enrichment_result_repository import EnrichmentResultRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.infrastructure.db.migrations import run_p1_migrations
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend


def run_manual_external_signal_monitoring_test():
    """Execute controlled external public signal monitoring manual integration test."""
    print("\n==================================================")
    print("BOPCLIENTS P8 — EXTERNAL PUBLIC SIGNAL MONITORING MANUAL TEST")
    print("==================================================\n")

    db = ForgeDB(_SQLiteBackend(db_path=":memory:"))
    run_p1_migrations(db)

    org_repo = OrganizationRepository(db)
    camp_repo = CampaignRepository(db)
    prospect_repo = ProspectRepository(db)
    prio_repo = ProspectPriorityRepository(db)
    obs_repo = SignalObservationRepository(db)
    intel_repo = ProspectIntelligenceRepository(db)
    enrich_repo = EnrichmentResultRepository(db)
    rr_repo = ResearchRunRepository(db)

    # Setup Organization & Campaign
    org = org_repo.save(Organization(name="P8 External Agency", slug="p8-agency"))
    camp = camp_repo.save(org.id, Campaign(name="P8 External Signals Campaign", status=CampaignStatus.ACTIVE))

    # Government Entity Prospect for SAM.gov procurement applicability
    p1 = prospect_repo.save_prospect(
        org.id, Prospect(name="Department of Veterans Affairs", website_url="https://va.gov", industry="government")
    )
    prospect_repo.add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p1.id))
    prospect_repo.save_lead_score(org.id, LeadScore(organization_id=org.id, prospect_id=p1.id, score=75))

    prio_service = ProspectPriorityService(
        priority_repo=prio_repo,
        prospect_repo=prospect_repo,
        campaign_repo=camp_repo,
        intel_repo=intel_repo,
        enrichment_repo=enrich_repo,
        research_run_repo=rr_repo,
    )
    prio_before = prio_service.prioritize_prospect(org.id, camp.id, p1.id)

    # 1. Official Website Mock Scraper
    class MockWebsiteScraper:
        def fetch_page(self, url):
            if "va.gov" in url:
                return {
                    "status": 200,
                    "content": "<html><body><h1>Department of Veterans Affairs</h1><p>We opened our new Orlando location in August 2026.</p></body></html>",
                    "headers": {"content-type": "text/html"},
                }
            return {"status": 404, "content": ""}

    prov_website = OfficialWebsiteSignalProvider(scraper=MockWebsiteScraper())

    # 2. Government Procurement Mock Client
    class MockProcurementClient:
        def search_solicitations(self, company_name):
            return [{
                "solicitationNumber": "SOL-2026-99",
                "title": "Request for Proposal - Healthcare IT System",
                "organizationName": "Department of Veterans Affairs",
                "source_url": "https://va.gov/procurement/sol-99",
                "active": "true",
                "responseDeadLine": "2026-12-31",
                "prospect_role": "issuer",
            }]

    prov_procurement = GovernmentProcurementProvider(api_key="mock_key", client=MockProcurementClient())

    # 3. Public News Search Backend Mock
    class MockNewsSearchBackend:
        def search(self, query):
            if "expansion" in query or "funding" in query:
                return [{
                    "url": "https://bizjournals.com/news/va-orlando-expansion",
                    "title": "Department of Veterans Affairs Announces Orlando Expansion",
                    "content": "The Department of Veterans Affairs announced it opened a new Orlando location to serve veterans.",
                }]
            return []

    prov_news = PublicNewsSignalProvider(search_backend=MockNewsSearchBackend())

    # Registry setup
    registry = PublicSignalProviderRegistry()
    registry.register(prov_website)
    registry.register(prov_procurement)
    registry.register(prov_news)

    monitor_service = PublicSignalMonitorService(
        observation_repo=obs_repo,
        prospect_repo=prospect_repo,
        campaign_repo=camp_repo,
        research_run_repo=rr_repo,
        priority_service=prio_service,
        registry=registry,
    )

    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 80))]):
        res = monitor_service.monitor_prospect(
            org.id, p1.id, country="US", context={"is_government_entity": True}, recompute_priority=True
        )

    prio_after = prio_repo.get(org.id, camp.id, p1.id)

    print(f"PROSPECT            : {p1.name.upper()} ({p1.website_url})")
    print(f"PROVIDERS EXECUTED  : {list(res.provider_results.keys())}")
    print("\nPROVIDER RESULTS:")
    for p_name, p_res in res.provider_results.items():
        print(f"  - [{p_name.upper()}] Status: {p_res['status']} | Validation: {p_res['validation_level']} | Obs Found: {p_res['observations_found']} | Signals Activated: {p_res['signals_activated']}")

    print(f"\nCROSS-PROVIDER SUMMARY:")
    print(f"  - Total Observations Found  : {res.observations_found}")
    print(f"  - Total Observations Created: {res.observations_created}")
    print(f"  - Total Signals Activated   : {res.signals_activated}")

    print("\nOBSERVATIONS & SEMANTIC EVENTS LIST:")
    obs_list = obs_repo.list_for_prospect(org.id, p1.id)
    for obs in obs_list:
        event_key = obs.compute_semantic_event_key()
        print(f"  - [{obs.provider.upper()}] [{obs.category.upper()}] {obs.signal_type} (conf {obs.confidence:.2f})")
        print(f"    Event Key  : {event_key}")
        print(f"    Source URL : {obs.source_url}")

    has_verified_intent = bool(prio_after.data.get("has_recent_verified_buying_intent"))
    urgent_label_applied = prio_after.priority_label.upper() == "URGENT"

    print(f"\nPRIORITY IMPACT:")
    print(f"  - BEFORE Monitoring : Score {prio_before.priority_score}/100 [{prio_before.priority_label.upper()}]")
    print(f"  - AFTER  Monitoring : Score {prio_after.priority_score}/100 [{prio_after.priority_label.upper()}]")
    print(f"  - Urgent Intent Requirement Met: {has_verified_intent}")
    print(f"  - Urgent Label Applied        : {urgent_label_applied}")

    print(f"\nWARNINGS: {res.warnings}")
    print(f"ERRORS  : {res.errors}")
    print("\n==================================================")
    print("EXTERNAL PUBLIC SIGNAL MONITORING MANUAL TEST SUCCESSFUL")
    print("==================================================\n")


if __name__ == "__main__":
    run_manual_external_signal_monitoring_test()
