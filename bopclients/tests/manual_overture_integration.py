"""Manual live integration test for BopClients P2 against real FORGE Overture Parquet engine."""

import time
from bopclients.domain.organization import Organization
from bopclients.domain.campaign import Campaign
from bopclients.domain.enums import CampaignStatus
from bopclients.application.search_intent_parser import RuleBasedSearchIntentParser
from bopclients.application.search_planner import DefaultSearchPlanner
from bopclients.application.search_service import SearchService
from bopclients.application.discovery_orchestrator import DiscoveryOrchestrator
from bopclients.infrastructure.location.static_location_resolver import StaticLocationResolver
from bopclients.infrastructure.providers.overture_provider import OvertureDiscoveryProvider
from bopclients.infrastructure.gateways.forge_gateway import ForgeDiscoveryGatewayAdapter
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.application.prospect_service import ProspectService
from bopclients.infrastructure.db.migrations import run_p1_migrations
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend


def run_manual_overture_discovery():
    """Manual integration test searching real Overture dataset for dentists in Miami."""
    start_time = time.time()
    db = ForgeDB(_SQLiteBackend(db_path=":memory:"))
    run_p1_migrations(db)

    org_repo = OrganizationRepository(db)
    campaign_repo = CampaignRepository(db)
    prospect_repo = ProspectRepository(db)
    rr_repo = ResearchRunRepository(db)

    org = org_repo.save(Organization(name="Bop Real Agency", slug="bop-real"))
    camp = campaign_repo.save(org.id, Campaign(name="Miami Dentists Real", status=CampaignStatus.ACTIVE))

    parser = RuleBasedSearchIntentParser()
    planner = DefaultSearchPlanner(StaticLocationResolver())

    # Real FORGE Overture Gateway
    real_gateway = ForgeDiscoveryGatewayAdapter()
    provider = OvertureDiscoveryProvider(real_gateway)
    prospect_service = ProspectService(prospect_repo)
    orchestrator = DiscoveryOrchestrator([provider], prospect_service, rr_repo, campaign_repo)

    search_service = SearchService(parser, planner, orchestrator, campaign_repo)

    raw_prompt = "Busca dentistas en Miami"
    print(f"\n[MANUAL INTEGRATION TEST]")
    print(f"1. Prompt: '{raw_prompt}'")
    intent = search_service.parse_search_intent(org.id, camp.id, raw_prompt)
    print(f"2. SearchIntent Result: target={intent.target_entity_type}, industries={intent.industries}, cities={intent.cities}, countries={intent.countries}")

    plan = search_service.plan_search(intent)
    print(f"3. SearchPlan Generated: tasks_count={len(plan.tasks)}, warnings_count={len(plan.warnings)}")
    if plan.tasks:
        t = plan.tasks[0]
        print(f"   Task 1: provider={t.provider}, category={t.category}, city={t.city}, postal_code={t.postal_code}, lat/lon=({t.latitude}, {t.longitude}), limit={t.limit}")

    print(f"4. Executing discovery against real Overture Parquet dataset on S3...")
    result = search_service.execute_search(org.id, camp.id, plan)

    duration = time.time() - start_time
    print(f"\n[EXECUTION SUMMARY]")
    print(f"  - Command: python -m bopclients.tests.manual_overture_integration")
    print(f"  - Duration: {duration:.2f}s")
    print(f"  - ResearchRun ID: {result.research_run_id}")
    print(f"  - Tasks Succeeded: {result.tasks_succeeded} / {result.tasks_total}")
    print(f"  - Total Discovered Raw: {result.total_discovered_raw}")
    print(f"  - Total Prospects Created: {result.prospects_created}")
    print(f"  - Total Prospects Reused: {result.prospects_reused}")
    print(f"  - Total Imported Prospects: {result.total_imported_prospects}")

    # Verify CampaignProspect memberships & ProspectSource records in DB
    cp_list = prospect_repo.list_prospect_campaigns(org.id, result.imported_prospects[0].id)
    print(f"  - CampaignProspect Memberships for 1st Prospect: {len(cp_list)}")

    sources = db.fetch_dicts("SELECT * FROM prospect_sources WHERE prospect_id = ?", (result.imported_prospects[0].id,))
    print(f"  - ProspectSource Records for 1st Prospect: {len(sources)} (type={sources[0]['source_type']}, external_id={sources[0]['external_id']})")

    run_check = rr_repo.get_by_id(org.id, result.research_run_id)
    print(f"  - Final ResearchRun Status: {run_check.status}")

    return result


if __name__ == "__main__":
    run_manual_overture_discovery()
