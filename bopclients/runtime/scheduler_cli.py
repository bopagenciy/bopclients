"""CLI runner for BopClients P16 Production Scheduler."""

import sys
import json
import signal
import argparse
import logging
from typing import Optional

from bopclients.runtime.settings import RuntimeSettings, sanitize_error_message
from bopclients.runtime.container import build_runtime_container
from bopclients.application.production_scheduler import ProductionScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("bopclients.scheduler.cli")


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser for production scheduler CLI."""
    parser = argparse.ArgumentParser(
        description="BopClients Production Scheduler Runner (Run-Once)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Perform non-destructive environment, schema, and scheduler readiness validation.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect scheduling policy and due backlog without acquiring leases or mutating database.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Execute scheduler tick even if PRODUCTION_SCHEDULER_ENABLED is false (lease locks remain strictly enforced).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured result in JSON format.",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    settings = RuntimeSettings.from_env()

    # Build runtime container
    try:
        container = build_runtime_container(settings)
        scheduler = container.scheduler
    except Exception as init_ex:
        logger.critical(f"Failed to initialize runtime container for scheduler: {init_ex}")
        sys.exit(1)

    # 1. Check Mode
    if args.check:
        info = scheduler.check()
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            print("==================================================")
            print("BOPCLIENTS PRODUCTION SCHEDULER CHECK")
            print("==================================================")
            print(f"Environment:          {info['environment']}")
            print(f"Database URL:         {info['database_url']}")
            print(f"Schema Version:       {info['schema_version']} (Expected: {info['expected_schema_version']})")
            print(f"Scheduler Enabled:    {info['scheduler_enabled']}")
            print(f"Scheduler Key:        {info['scheduler_key']}")
            print(f"Lease Seconds:        {info['scheduler_lease_seconds']}")
            print(f"Renew Before Seconds: {info['scheduler_renew_before_seconds']}")
            print(f"Readiness Status:     {info['readiness_status']}")
            print(f"Database Connected:   {info['database_connected']}")
            print(f"Tables Present:       {info['tables_present']}")
            if info["current_lease_state"]:
                print(f"Lease Currently Held: {info['current_lease_state']['lease_held']}")
                print(f"Last Status:          {info['current_lease_state']['last_status']}")
            if info["warnings"]:
                print("\nWarnings:")
                for w in info["warnings"]:
                    print(f"  - WARNING: {w}")
            if info["errors"]:
                print("\nErrors:")
                for e in info["errors"]:
                    print(f"  - ERROR: {e}")
            print("==================================================")

        ready = info["readiness_status"] in ("READY", "DEGRADED") and not info["errors"]
        sys.exit(0 if ready else 1)

    # 2. Dry Run Mode
    if args.dry_run:
        dry_info = scheduler.dry_run()
        if args.json:
            print(json.dumps(dry_info, indent=2))
        else:
            print("==================================================")
            print("BOPCLIENTS PRODUCTION SCHEDULER DRY RUN")
            print("==================================================")
            print(f"Mode:                 {dry_info['mode']}")
            print(f"Scheduler Key:        {dry_info['scheduler_key']}")
            print(f"Scheduler Enabled:    {dry_info['production_scheduler_enabled']}")
            print(f"Readiness Status:     {dry_info['readiness_status']}")
            print(f"Lease Active:         {dry_info['lease_currently_active']}")
            print(f"Due Items Backlog:    {dry_info['due_items_count']}")
            print(f"Would Dispatch:       {dry_info['would_dispatch']}")
            print(f"Mutations Count:      {dry_info['mutations_count']}")
            print("==================================================")
        sys.exit(0)

    # 3. Default Mode: Execute One Scheduler Tick with Signal Handling
    def handle_signal(signum, frame):
        logger.warning(f"Process received termination signal ({signum}). Requesting worker cooperative stop...")
        container.worker.request_stop()

    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_signal)

    try:
        result = scheduler.tick(force=args.force)

        if args.json:
            print(json.dumps(result.safe_summary(), indent=2))
        else:
            print("\n" + "=" * 50)
            print(f"SCHEDULER TICK COMPLETE: {result.status}")
            print("=" * 50)
            print(f"Scheduler Run ID:     {result.scheduler_run_id}")
            print(f"Scheduler Key:        {result.scheduler_key}")
            print(f"Duration:             {result.duration_ms:.2f} ms")
            if result.worker_run_id:
                print(f"Worker Run ID:        {result.worker_run_id}")
                print(f"Worker Stopped:       {result.worker_stopped_reason}")
                print(f"Items Attempted:      {result.items_attempted}")
                print(f"Items Claimed:        {result.items_claimed}")
                print(f"Success Count:        {result.success_count}")
                print(f"Failure Count:        {result.failure_count}")
                print(f"Backpressure Count:   {result.backpressure_count}")
            if result.recovered_runs_count > 0:
                print(f"Orphan Runs Recovered: {result.recovered_runs_count}")
            if result.error_code:
                print(f"Error Code:           {result.error_code}")
                print(f"Error Message:        {sanitize_error_message(result.error_message)}")
            print("=" * 50 + "\n")

        # Exit code mapping: COMPLETED, SKIPPED_LEASE_HELD, SKIPPED_DISABLED -> 0
        if result.status in ("COMPLETED", "SKIPPED_LEASE_HELD", "SKIPPED_DISABLED"):
            sys.exit(0)
        else:
            sys.exit(1)

    except KeyboardInterrupt:
        logger.warning("Scheduler process interrupted by user (KeyboardInterrupt). Exiting cleanly.")
        sys.exit(130)
    except Exception as fatal_ex:
        logger.critical(f"Fatal error during scheduler execution: {sanitize_error_message(fatal_ex)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
