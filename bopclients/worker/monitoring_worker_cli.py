"""CLI runner for BopClients P10 Continuous Monitoring Worker."""

import sys
import argparse
import logging
from bopclients.worker.monitoring_worker import (
    MonitoringWorker,
    MonitoringWorkerConfig,
)
from bopclients.infrastructure.repositories.monitoring_schedule_repository import MonitoringScheduleRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_priority_repository import ProspectPriorityRepository
from bopclients.infrastructure.repositories.signal_observation_repository import SignalObservationRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.application.public_signal_monitor_service import PublicSignalMonitorService
from bopclients.application.prospect_priority_service import ProspectPriorityService
from bopclients.application.continuous_monitoring_service import ContinuousMonitoringService
from bopclients.application.provider_registry import PublicSignalProviderRegistry
from bopclients.application.signal_provider import OfficialWebsiteSignalProvider
from bopclients.application.providers.procurement_provider import GovernmentProcurementProvider
from bopclients.application.providers.news_provider import PublicNewsSignalProvider
from bopclients.infrastructure.db.migrations import run_p1_migrations
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("bopclients.worker.cli")


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for monitoring worker."""
    parser = argparse.ArgumentParser(
        description="BopClients Continuous Monitoring Worker Runner (Run-Once)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--once",
        action="store_true",
        default=True,
        help="Process due monitoring backlog once within run budget and exit.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Number of due schedule items to fetch per query batch.",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=100,
        help="Maximum total due schedule items to process in this run.",
    )
    parser.add_argument(
        "--max-seconds",
        type=int,
        default=600,
        help="Maximum total execution duration in seconds for this run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List due schedules without executing claims or provider scans.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Health check database connection and monitoring_schedules table existence.",
    )
    return parser


def health_check(db) -> bool:
    """Validate database connection and monitoring_schedules table presence."""
    try:
        rows = db.fetch_dicts("SELECT COUNT(*) as count FROM monitoring_schedules")
        count = rows[0]["count"] if rows else 0
        logger.info(f"Health Check PASSED: DB connected. Total monitoring schedules in system: {count}")
        return True
    except Exception as ex:
        logger.error(f"Health Check FAILED: {ex}")
        return False


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Validate inputs
    if args.batch_size <= 0 or args.max_items <= 0 or args.max_seconds <= 0:
        logger.error("Error: --batch-size, --max-items, and --max-seconds must be positive integers.")
        sys.exit(1)

    # Initialize DB backend
    try:
        db = ForgeDB(_SQLiteBackend())
        run_p1_migrations(db)
    except Exception as ex:
        logger.critical(f"Failed to connect to database: {ex}")
        sys.exit(1)

    if args.check:
        ok = health_check(db)
        sys.exit(0 if ok else 1)

    # Initialize Repositories and Services
    sched_repo = MonitoringScheduleRepository(db)
    prospect_repo = ProspectRepository(db)
    camp_repo = CampaignRepository(db)
    prio_repo = ProspectPriorityRepository(db)
    obs_repo = SignalObservationRepository(db)
    intel_repo = ProspectIntelligenceRepository(db)
    enrich_repo = EnrichmentResultRepository(db)
    rr_repo = ResearchRunRepository(db)

    registry = PublicSignalProviderRegistry()
    registry.register(OfficialWebsiteSignalProvider())
    registry.register(GovernmentProcurementProvider())
    registry.register(PublicNewsSignalProvider())

    sig_service = PublicSignalMonitorService(
        observation_repo=obs_repo,
        prospect_repo=prospect_repo,
        campaign_repo=camp_repo,
        research_run_repo=rr_repo,
        registry=registry,
    )

    prio_service = ProspectPriorityService(
        priority_repo=prio_repo,
        prospect_repo=prospect_repo,
        campaign_repo=camp_repo,
        intel_repo=intel_repo,
        enrichment_repo=enrich_repo,
        research_run_repo=rr_repo,
    )

    monitoring_service = ContinuousMonitoringService(
        schedule_repo=sched_repo,
        prospect_repo=prospect_repo,
        campaign_repo=camp_repo,
        priority_repo=prio_repo,
        observation_repo=obs_repo,
        research_run_repo=rr_repo,
        signal_monitor_service=sig_service,
        priority_service=prio_service,
    )

    config = MonitoringWorkerConfig(
        batch_size=args.batch_size,
        max_items=args.max_items,
        max_run_seconds=args.max_seconds,
        dry_run=args.dry_run,
    )

    worker = MonitoringWorker(
        schedule_repo=sched_repo,
        monitoring_service=monitoring_service,
        config=config,
    )

    try:
        result = worker.run()
        print("\n" + "=" * 50)
        print(f"WORKER RUN COMPLETE (ID: {result.worker_run_id[:8]})")
        print(f"Stopped Reason:   {result.stopped_reason}")
        print(f"Items Discovered: {result.items_discovered}")
        print(f"Items Attempted:  {result.items_attempted}")
        print(f"Items Claimed:    {result.items_claimed}")
        print(f"Items Completed:  {result.items_completed}")
        print(f"Success Count:    {result.success_count}")
        print(f"Partial Success:  {result.partial_success_count}")
        print(f"Failed Count:     {result.failed_count}")
        print(f"Skipped Count:    {result.skipped_count}")
        print(f"Lease Busy Count: {result.lease_busy_count}")
        print(f"Duration:         {result.duration_ms:.2f} ms")
        print("=" * 50 + "\n")
        sys.exit(0)
    except KeyboardInterrupt:
        logger.warning("Worker interrupted by user (KeyboardInterrupt). Stopping safely.")
        sys.exit(130)
    except Exception as fatal_ex:
        logger.critical(f"Fatal worker infrastructure failure: {fatal_ex}")
        sys.exit(1)


if __name__ == "__main__":
    main()
