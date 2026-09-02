"""Single Composition Root (RuntimeContainer) wiring dependencies for BopClients production execution."""

import logging
from dataclasses import dataclass
from typing import Optional

from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus

from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.prospect_priority_repository import ProspectPriorityRepository
from bopclients.infrastructure.repositories.signal_observation_repository import SignalObservationRepository
from bopclients.infrastructure.repositories.prospect_intelligence_repository import ProspectIntelligenceRepository
from bopclients.infrastructure.repositories.enrichment_result_repository import EnrichmentResultRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.infrastructure.repositories.monitoring_schedule_repository import MonitoringScheduleRepository

from bopclients.application.provider_registry import PublicSignalProviderRegistry
from bopclients.application.signal_provider import OfficialWebsiteSignalProvider
from bopclients.application.providers.procurement_provider import GovernmentProcurementProvider
from bopclients.application.providers.news_provider import PublicNewsSignalProvider
from bopclients.application.providers.gemini_research_provider import GeminiProspectResearchProvider

from bopclients.application.public_signal_monitor_service import PublicSignalMonitorService
from bopclients.application.continuous_monitoring_service import ContinuousMonitoringService

from bopclients.worker.monitoring_worker import MonitoringWorker, MonitoringWorkerConfig

from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend

logger = logging.getLogger("bopclients.runtime.container")


@dataclass
class RuntimeContainer:
    """Dependency container encapsulating configured services and repositories."""

    settings: RuntimeSettings
    db: ForgeDB
    org_repo: OrganizationRepository
    campaign_repo: CampaignRepository
    prospect_repo: ProspectRepository
    priority_repo: ProspectPriorityRepository
    observation_repo: SignalObservationRepository
    intel_repo: ProspectIntelligenceRepository
    enrich_repo: EnrichmentResultRepository
    research_run_repo: ResearchRunRepository
    schedule_repo: MonitoringScheduleRepository
    provider_registry: PublicSignalProviderRegistry
    signal_monitor_service: PublicSignalMonitorService
    continuous_monitoring_service: ContinuousMonitoringService
    worker: MonitoringWorker


def build_runtime_container(settings: Optional[RuntimeSettings] = None, db: Optional[ForgeDB] = None) -> RuntimeContainer:
    """Build and wire application container for production execution.
    
    Args:
        settings: Optional RuntimeSettings instance (defaults to RuntimeSettings.from_env()).
        db: Optional pre-configured ForgeDB connection.
    
    Returns:
        Fully wired RuntimeContainer instance.
    """
    if not settings:
        settings = RuntimeSettings.from_env()

    if not db:
        db = ForgeDB(_SQLiteBackend(db_path=settings.database_url))

    # Repositories
    org_repo = OrganizationRepository(db)
    campaign_repo = CampaignRepository(db)
    prospect_repo = ProspectRepository(db)
    priority_repo = ProspectPriorityRepository(db)
    observation_repo = SignalObservationRepository(db)
    intel_repo = ProspectIntelligenceRepository(db)
    enrich_repo = EnrichmentResultRepository(db)
    research_run_repo = ResearchRunRepository(db)
    schedule_repo = MonitoringScheduleRepository(db)

    # Provider Registry Wiring (Filtered by settings.enabled_providers)
    registry = PublicSignalProviderRegistry()
    enabled_lower = [p.lower() for p in settings.enabled_providers]

    if "official_website" in enabled_lower:
        registry.register(OfficialWebsiteSignalProvider())

    if "government_procurement" in enabled_lower:
        registry.register(GovernmentProcurementProvider(api_key=settings.sam_gov_api_key))

    if "public_news" in enabled_lower:
        registry.register(PublicNewsSignalProvider())

    if "gemini" in enabled_lower or "gemini_research" in enabled_lower:
        registry.register(GeminiProspectResearchProvider(api_key=settings.gemini_api_key))

    # Application Services
    signal_monitor_service = PublicSignalMonitorService(
        observation_repo=observation_repo,
        prospect_repo=prospect_repo,
        campaign_repo=campaign_repo,
        research_run_repo=research_run_repo,
        registry=registry,
    )

    continuous_monitoring_service = ContinuousMonitoringService(
        schedule_repo=schedule_repo,
        prospect_repo=prospect_repo,
        priority_repo=priority_repo,
        observation_repo=observation_repo,
        research_run_repo=research_run_repo,
        signal_monitor_service=signal_monitor_service,
    )

    # Worker Config & Instance
    worker_config = MonitoringWorkerConfig(
        batch_size=settings.worker_batch_size,
        max_items=settings.worker_max_items,
        max_run_seconds=settings.worker_max_seconds,
        lease_duration_seconds=settings.lease_duration_seconds,
        lease_renew_before_seconds=settings.lease_renew_before_seconds,
    )

    worker = MonitoringWorker(
        schedule_repo=schedule_repo,
        monitoring_service=continuous_monitoring_service,
        config=worker_config,
    )

    return RuntimeContainer(
        settings=settings,
        db=db,
        org_repo=org_repo,
        campaign_repo=campaign_repo,
        prospect_repo=prospect_repo,
        priority_repo=priority_repo,
        observation_repo=observation_repo,
        intel_repo=intel_repo,
        enrich_repo=enrich_repo,
        research_run_repo=research_run_repo,
        schedule_repo=schedule_repo,
        provider_registry=registry,
        signal_monitor_service=signal_monitor_service,
        continuous_monitoring_service=continuous_monitoring_service,
        worker=worker,
    )


def build_monitoring_worker(settings: Optional[RuntimeSettings] = None, db: Optional[ForgeDB] = None) -> MonitoringWorker:
    """Convenience helper building MonitoringWorker from RuntimeContainer."""
    container = build_runtime_container(settings=settings, db=db)
    return container.worker
