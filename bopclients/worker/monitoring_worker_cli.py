"""CLI runner for BopClients P10 Continuous Monitoring Worker."""

import sys
import argparse
import logging
from bopclients.worker.monitoring_worker import (
    MonitoringWorker,
    MonitoringWorkerConfig,
)
from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus
from bopclients.runtime.container import build_runtime_container
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

    # Build container from settings
    settings = RuntimeSettings.from_env()
    settings.worker_batch_size = args.batch_size
    settings.worker_max_items = args.max_items
    settings.worker_max_seconds = args.max_seconds

    # Production Startup Guard: Perform Readiness Check
    readiness = RuntimeReadinessCheck.check(settings)
    if readiness.status == ReadinessStatus.NOT_READY:
        logger.critical(f"Worker startup aborted: Runtime readiness is NOT_READY. Errors: {readiness.errors}")
        sys.exit(1)
    elif readiness.status == ReadinessStatus.DEGRADED:
        logger.warning(f"Worker starting in DEGRADED mode. Warnings: {readiness.warnings}")

    try:
        container = build_runtime_container(settings)
        db = container.db
    except Exception as ex:
        logger.critical(f"Failed to initialize runtime container: {ex}")
        sys.exit(1)

    if args.check:
        ok = health_check(db)
        sys.exit(0 if ok else 1)

    worker = container.worker
    worker.config.dry_run = args.dry_run

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
