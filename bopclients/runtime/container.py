"""Single Composition Root (RuntimeContainer) wiring dependencies for BopClients production execution."""

import logging
from dataclasses import dataclass
from typing import Optional, Any

from bopclients.runtime.settings import RuntimeSettings, AppEnvironment
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus

from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository, UserRepository
from bopclients.infrastructure.repositories.invitation_repository import InvitationRepository
from bopclients.infrastructure.repositories.icp_repository import ICPRepository
from bopclients.infrastructure.repositories.auth_repository import AuthSessionRepository, LoginAttemptRepository
from bopclients.infrastructure.repositories.auth_token_repository import AuthTokenRepository
from bopclients.domain.auth.password import PasswordHasher
from bopclients.domain.auth.token import TokenService
from bopclients.application.auth_service import AuthService
from bopclients.application.invitation_service import InvitationService
from bopclients.application.interfaces.email_sender import ITransactionalEmailSender
from bopclients.infrastructure.email.in_memory_sender import InMemoryEmailSender
from bopclients.infrastructure.email.null_sender import NullEmailSender
from bopclients.infrastructure.email.resend_sender import ResendEmailSender
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.prospect_priority_repository import ProspectPriorityRepository
from bopclients.infrastructure.repositories.signal_observation_repository import SignalObservationRepository
from bopclients.infrastructure.repositories.prospect_intelligence_repository import ProspectIntelligenceRepository
from bopclients.infrastructure.repositories.enrichment_result_repository import EnrichmentResultRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.infrastructure.repositories.monitoring_schedule_repository import MonitoringScheduleRepository
from bopclients.infrastructure.repositories.provider_rate_limit_repository import ProviderRateLimitRepository
from bopclients.infrastructure.repositories.scheduler_repository import SchedulerRepository
from bopclients.infrastructure.repositories.integration_outbox_repository import IntegrationOutboxRepository
from bopclients.infrastructure.repositories.integration_inbox_repository import IntegrationInboxRepository
from bopclients.infrastructure.repositories.integration_destination_repository import IntegrationDestinationRepository
from bopclients.infrastructure.repositories.integration_delivery_repository import IntegrationDeliveryRepository
from bopclients.infrastructure.repositories.service_repository import ServiceRepository
from bopclients.domain.integration.delivery import EnvIntegrationSecretResolver
from bopclients.infrastructure.transports.http_transport import HttpWebhookTransport
from bopclients.application.integration_dispatcher import IntegrationOutboxDispatcher
from bopclients.runtime.integration_publisher_worker import IntegrationPublisherWorker

from bopclients.application.provider_registry import PublicSignalProviderRegistry
from bopclients.application.signal_provider import OfficialWebsiteSignalProvider
from bopclients.application.providers.procurement_provider import GovernmentProcurementProvider
from bopclients.application.providers.news_provider import PublicNewsSignalProvider
from bopclients.application.providers.gemini_research_provider import GeminiProspectResearchProvider
from bopclients.application.providers.deterministic_research_provider import DeterministicResearchProvider
from bopclients.application.research_validation_policy import ResearchValidationPolicy
from bopclients.application.prospect_research_orchestrator import ProspectResearchOrchestrator
from bopclients.application.prospect_research_service import ProspectResearchService
from bopclients.worker.research_worker import ResearchWorker

from bopclients.application.search_intent_parser import RuleBasedSearchIntentParser
from bopclients.application.search_planner import DefaultSearchPlanner
from bopclients.infrastructure.location.static_location_resolver import StaticLocationResolver
from bopclients.infrastructure.gateways.forge_gateway import ForgeDiscoveryGatewayAdapter
from bopclients.infrastructure.providers.overture_provider import OvertureDiscoveryProvider
from bopclients.application.discovery_orchestrator import DiscoveryOrchestrator
from bopclients.application.search_service import SearchService
from bopclients.application.prospect_service import ProspectService
from bopclients.application.opportunity_scorer import RuleBasedOpportunityScorer
from bopclients.application.priority_scorer import RuleBasedPriorityScorer
from bopclients.application.crm_handoff_service import CrmHandoffService

from bopclients.application.provider_rate_limit_service import ProviderRateLimitService
from bopclients.application.provider_execution_guard import ProviderExecutionGuard
from bopclients.application.public_signal_monitor_service import PublicSignalMonitorService
from bopclients.application.continuous_monitoring_service import ContinuousMonitoringService
from bopclients.application.research_run_recovery_service import ResearchRunRecoveryService
from bopclients.application.production_scheduler import ProductionScheduler

from bopclients.worker.monitoring_worker import MonitoringWorker, MonitoringWorkerConfig

from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend

from bopclients.infrastructure.db.connection import create_database_connection, BopDBConnection

logger = logging.getLogger("bopclients.runtime.container")


@dataclass
class RuntimeContainer:
    """Dependency container encapsulating configured services and repositories."""

    settings: RuntimeSettings
    db: Any
    org_repo: OrganizationRepository
    campaign_repo: CampaignRepository
    prospect_repo: ProspectRepository
    priority_repo: ProspectPriorityRepository
    observation_repo: SignalObservationRepository
    intel_repo: ProspectIntelligenceRepository
    enrich_repo: EnrichmentResultRepository
    research_run_repo: ResearchRunRepository
    schedule_repo: MonitoringScheduleRepository
    rate_limit_repo: ProviderRateLimitRepository
    rate_limit_service: ProviderRateLimitService
    execution_guard: ProviderExecutionGuard
    provider_registry: PublicSignalProviderRegistry
    signal_monitor_service: PublicSignalMonitorService
    continuous_monitoring_service: ContinuousMonitoringService
    recovery_service: ResearchRunRecoveryService
    worker: MonitoringWorker
    scheduler_repo: SchedulerRepository
    scheduler: ProductionScheduler
    outbox_repo: IntegrationOutboxRepository
    inbox_repo: IntegrationInboxRepository
    destination_repo: IntegrationDestinationRepository
    delivery_repo: IntegrationDeliveryRepository
    integration_dispatcher: IntegrationOutboxDispatcher
    integration_publisher_worker: IntegrationPublisherWorker
    user_repo: UserRepository
    icp_repo: ICPRepository
    auth_session_repo: AuthSessionRepository
    login_attempt_repo: LoginAttemptRepository
    token_service: TokenService
    password_hasher: PasswordHasher
    auth_service: AuthService
    auth_token_repo: Optional[AuthTokenRepository] = None
    invitation_repo: Optional[InvitationRepository] = None
    invitation_service: Optional[InvitationService] = None
    email_sender: Optional[ITransactionalEmailSender] = None
    search_service: Optional[SearchService] = None
    prospect_service: Optional[ProspectService] = None
    opportunity_scorer: Optional[RuleBasedOpportunityScorer] = None
    priority_scorer: Optional[RuleBasedPriorityScorer] = None
    crm_handoff_service: Optional[CrmHandoffService] = None
    service_repo: Optional[ServiceRepository] = None
    prospect_research_orchestrator: Optional[ProspectResearchOrchestrator] = None
    prospect_research_service: Optional[ProspectResearchService] = None
    research_worker: Optional[ResearchWorker] = None

    @classmethod
    def initialize(cls, settings: Optional[RuntimeSettings] = None, db: Optional[Any] = None) -> "RuntimeContainer":
        """Alternative constructor initializing RuntimeContainer."""
        return build_runtime_container(settings=settings, db=db)


def build_runtime_container(settings: Optional[RuntimeSettings] = None, db: Optional[Any] = None) -> RuntimeContainer:
    """Build and wire application container for production execution.
    
    Args:
        settings: Optional RuntimeSettings instance (defaults to RuntimeSettings.from_env()).
        db: Optional pre-configured DB connection (ForgeDB or BopDBConnection).
    
    Returns:
        Fully wired RuntimeContainer instance.
    """
    if not settings:
        settings = RuntimeSettings.from_env()

    if not db:
        db = create_database_connection(settings.database_url)

    # Repositories
    org_repo = OrganizationRepository(db)
    user_repo = UserRepository(db)
    icp_repo = ICPRepository(db)
    campaign_repo = CampaignRepository(db)
    prospect_repo = ProspectRepository(db)
    priority_repo = ProspectPriorityRepository(db)
    observation_repo = SignalObservationRepository(db)
    intel_repo = ProspectIntelligenceRepository(db)
    enrich_repo = EnrichmentResultRepository(db)
    research_run_repo = ResearchRunRepository(db)
    schedule_repo = MonitoringScheduleRepository(db)
    rate_limit_repo = ProviderRateLimitRepository(db)
    outbox_repo = IntegrationOutboxRepository(db, org_repo=org_repo)
    inbox_repo = IntegrationInboxRepository(db)
    destination_repo = IntegrationDestinationRepository(db)
    delivery_repo = IntegrationDeliveryRepository(db)
    auth_session_repo = AuthSessionRepository(db)
    login_attempt_repo = LoginAttemptRepository(db)

    # Transactional Email Delivery (P25)
    email_sender: ITransactionalEmailSender
    if settings.email_provider == "resend":
        email_sender = ResendEmailSender(
            api_key=settings.email_api_key or "",
            default_from=settings.email_from,
        )
    elif settings.email_provider == "in_memory":
        email_sender = InMemoryEmailSender(
            default_from=settings.email_from,
        )
    else:
        email_sender = NullEmailSender()

    # Auth & Security Foundation (P19 / P26)
    password_hasher = PasswordHasher()
    token_service = TokenService(
        signing_key=settings.auth_signing_key,
        access_token_expire_seconds=settings.auth_token_expire_seconds,
    )
    auth_token_repo = AuthTokenRepository(db)
    auth_service = AuthService(
        user_repo=user_repo,
        org_repo=org_repo,
        session_repo=auth_session_repo,
        attempt_repo=login_attempt_repo,
        token_service=token_service,
        password_hasher=password_hasher,
        auth_token_repo=auth_token_repo,
        email_sender=email_sender,
        app_url=settings.app_url,
        default_from=settings.email_from,
        session_expire_days=settings.auth_session_expire_days,
        password_reset_token_expire_minutes=settings.password_reset_token_expire_minutes,
        email_verification_token_expire_hours=settings.email_verification_token_expire_hours,
    )

    # Secure Team Invitations (P24 / P25)
    invitation_repo = InvitationRepository(db)
    invitation_service = InvitationService(
        inv_repo=invitation_repo,
        org_repo=org_repo,
        user_repo=user_repo,
        auth_service=auth_service,
        email_sender=email_sender,
        app_url=settings.app_url,
        default_from=settings.email_from,
    )

    # Integration Outbox Dispatcher & Publisher Worker (P18 / P18.1)
    secret_resolver = EnvIntegrationSecretResolver()
    http_transport = HttpWebhookTransport(
        connect_timeout=settings.integration_http_connect_timeout,
        read_timeout=settings.integration_http_read_timeout,
        secret_resolver=secret_resolver,
        allow_insecure_http=settings.integration_allow_insecure_http,
        allowed_local_destinations=settings.parse_allowed_local_destinations(),
    )
    integration_dispatcher = IntegrationOutboxDispatcher(
        outbox_repo=outbox_repo,
        destination_repo=destination_repo,
        delivery_repo=delivery_repo,
        transports={"HTTP": http_transport},
    )
    integration_publisher_worker = IntegrationPublisherWorker(
        dispatcher=integration_dispatcher,
        settings=settings,
    )

    # Distributed Rate Limiting & Execution Guard
    rate_limit_service = ProviderRateLimitService(rate_limit_repo)
    execution_guard = ProviderExecutionGuard(rate_limit_service)

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
        execution_guard=execution_guard,
    )

    continuous_monitoring_service = ContinuousMonitoringService(
        schedule_repo=schedule_repo,
        prospect_repo=prospect_repo,
        priority_repo=priority_repo,
        observation_repo=observation_repo,
        research_run_repo=research_run_repo,
        signal_monitor_service=signal_monitor_service,
    )

    recovery_service = ResearchRunRecoveryService(
        research_run_repo=research_run_repo,
        schedule_repo=schedule_repo,
    )

    # Worker Config & Instance
    worker_config = MonitoringWorkerConfig(
        batch_size=settings.worker_batch_size,
        max_items=settings.worker_max_items,
        max_run_seconds=settings.worker_max_seconds,
        lease_duration_seconds=settings.lease_duration_seconds,
        lease_renew_before_seconds=settings.lease_renew_before_seconds,
        research_run_recovery_enabled=settings.research_run_recovery_enabled,
        research_run_stale_after_seconds=settings.research_run_stale_after_seconds,
        research_run_recovery_limit=settings.research_run_recovery_limit,
    )

    worker = MonitoringWorker(
        schedule_repo=schedule_repo,
        monitoring_service=continuous_monitoring_service,
        recovery_service=recovery_service,
        config=worker_config,
    )

    scheduler_repo = SchedulerRepository(db)
    scheduler = ProductionScheduler(
        scheduler_repo=scheduler_repo,
        worker=worker,
        settings=settings,
        schedule_repo=schedule_repo,
    )

    # Discovery & Prospecting Application Services (P21)
    try:
        discovery_gateway = ForgeDiscoveryGatewayAdapter()
    except Exception:
        discovery_gateway = None

    discovery_provider = OvertureDiscoveryProvider(discovery_gateway)
    prospect_service = ProspectService(prospect_repo, discovery_gateway)
    discovery_orchestrator = DiscoveryOrchestrator(
        providers=[discovery_provider],
        prospect_service=prospect_service,
        research_run_repo=research_run_repo,
        campaign_repo=campaign_repo,
    )
    search_parser = RuleBasedSearchIntentParser()
    search_planner = DefaultSearchPlanner(location_resolver=StaticLocationResolver())
    search_service = SearchService(
        intent_parser=search_parser,
        search_planner=search_planner,
        orchestrator=discovery_orchestrator,
        campaign_repo=campaign_repo,
    )
    opportunity_scorer = RuleBasedOpportunityScorer()
    priority_scorer = RuleBasedPriorityScorer()
    crm_handoff_service = CrmHandoffService(
        prospect_repo=prospect_repo,
        outbox_repo=outbox_repo,
        destination_repo=destination_repo,
        delivery_repo=delivery_repo,
        priority_repo=priority_repo,
        campaign_repo=campaign_repo,
        signal_repo=observation_repo,
        dispatcher=integration_dispatcher,
        web_public_url=settings.web_public_url,
        is_production=(settings.environment == AppEnvironment.PRODUCTION),
    )

    # Prospect Research Execution Stack (P30.1)
    service_repo = ServiceRepository(db)
    research_provider = DeterministicResearchProvider()
    research_validation_policy = ResearchValidationPolicy()
    prospect_research_orchestrator = ProspectResearchOrchestrator(
        research_provider=research_provider,
        validation_policy=research_validation_policy,
        prospect_repo=prospect_repo,
        research_run_repo=research_run_repo,
        enrichment_result_repo=enrich_repo,
        prospect_intel_repo=intel_repo,
        service_repo=service_repo,
        icp_repo=icp_repo,
    )
    prospect_research_service = ProspectResearchService(
        orchestrator=prospect_research_orchestrator,
        campaign_repo=campaign_repo,
        prospect_repo=prospect_repo,
    )
    research_worker = ResearchWorker(
        research_run_repo=research_run_repo,
        research_service=prospect_research_service,
        recovery_service=recovery_service,
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
        rate_limit_repo=rate_limit_repo,
        rate_limit_service=rate_limit_service,
        execution_guard=execution_guard,
        provider_registry=registry,
        signal_monitor_service=signal_monitor_service,
        continuous_monitoring_service=continuous_monitoring_service,
        recovery_service=recovery_service,
        worker=worker,
        scheduler_repo=scheduler_repo,
        scheduler=scheduler,
        outbox_repo=outbox_repo,
        inbox_repo=inbox_repo,
        destination_repo=destination_repo,
        delivery_repo=delivery_repo,
        integration_dispatcher=integration_dispatcher,
        integration_publisher_worker=integration_publisher_worker,
        user_repo=user_repo,
        icp_repo=icp_repo,
        auth_session_repo=auth_session_repo,
        login_attempt_repo=login_attempt_repo,
        token_service=token_service,
        password_hasher=password_hasher,
        auth_service=auth_service,
        auth_token_repo=auth_token_repo,
        invitation_repo=invitation_repo,
        invitation_service=invitation_service,
        email_sender=email_sender,
        search_service=search_service,
        prospect_service=prospect_service,
        opportunity_scorer=opportunity_scorer,
        priority_scorer=priority_scorer,
        crm_handoff_service=crm_handoff_service,
        service_repo=service_repo,
        prospect_research_orchestrator=prospect_research_orchestrator,
        prospect_research_service=prospect_research_service,
        research_worker=research_worker,
    )


def build_monitoring_worker(settings: Optional[RuntimeSettings] = None, db: Optional[ForgeDB] = None) -> MonitoringWorker:
    """Convenience helper building MonitoringWorker from RuntimeContainer."""
    container = build_runtime_container(settings=settings, db=db)
    return container.worker


def build_production_scheduler(settings: Optional[RuntimeSettings] = None, db: Optional[Any] = None) -> ProductionScheduler:
    """Convenience helper building ProductionScheduler from RuntimeContainer."""
    container = build_runtime_container(settings=settings, db=db)
    return container.scheduler


def build_integration_publisher_worker(settings: Optional[RuntimeSettings] = None, db: Optional[Any] = None) -> IntegrationPublisherWorker:
    """Convenience helper building IntegrationPublisherWorker from RuntimeContainer."""
    container = build_runtime_container(settings=settings, db=db)
    return container.integration_publisher_worker


def build_research_worker(settings: Optional[RuntimeSettings] = None, db: Optional[Any] = None) -> ResearchWorker:
    """Convenience helper building ResearchWorker from RuntimeContainer."""
    container = build_runtime_container(settings=settings, db=db)
    return container.research_worker
