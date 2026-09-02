"""BopClients ResearchRun Recovery CLI for operational reconciliation of orphan running ResearchRuns."""

import sys
import logging
import argparse
from datetime import datetime, timezone
from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.container import build_runtime_container
from bopclients.application.research_run_recovery_service import ResearchRunRecoveryService

logger = logging.getLogger("bopclients.recovery_cli")


def main():
    parser = argparse.ArgumentParser(description="BopClients Operational ResearchRun Recovery Runner")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Inspect stale candidate ResearchRuns without performing status mutations.",
    )
    parser.add_argument(
        "--stale-after-seconds",
        type=int,
        default=None,
        help="Stale threshold in seconds (defaults to settings.research_run_stale_after_seconds / 900s).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum candidate runs to evaluate (defaults to settings.research_run_recovery_limit / 100).",
    )

    args = parser.parse_args()

    try:
        settings = RuntimeSettings.from_env()
        settings.validate()
        container = build_runtime_container(settings)
        DatabaseMigrator.migrate(container.db)

        stale_sec = args.stale_after_seconds or settings.research_run_stale_after_seconds
        lim = args.limit or settings.research_run_recovery_limit

        print("=================================================================")
        print("BOPCLIENTS RESEARCHRUN RECOVERY OPERATIONAL RUNNER")
        print("=================================================================")
        print(f"Target DB URL:       {settings.mask_database_url()}")
        print(f"Environment:         {settings.environment.value}")
        print(f"Mode:                {'DRY_RUN (No Mutations)' if args.dry_run else 'REAL_RECOVERY'}")
        print(f"Stale Threshold:     {stale_sec} seconds")
        print(f"Candidate Limit:     {lim}")

        if args.dry_run:
            # Perform read-only candidate inspection
            now_dt = datetime.now(timezone.utc)
            from datetime import timedelta
            stale_before_iso = (now_dt - timedelta(seconds=stale_sec)).isoformat()
            candidates = container.research_run_repo.list_stale_running_runs(stale_before_iso, limit=lim)

            print(f"\n[DRY RUN SUMMARY]")
            print(f"Stale Candidates Discovered: {len(candidates)}")
            for c in candidates:
                print(f"  - Run ID: {c.id[:8]}... | Tenant: {c.organization_id} | Schedule ID: {c.monitoring_schedule_id} | Started: {c.started_at}")
            print("\nDRY RUN COMPLETED SUCCESSFULLY (No DB mutations performed).")
            sys.exit(0)

        # Real Recovery Pass
        result = container.recovery_service.reconcile_stale_runs(
            stale_after_seconds=stale_sec,
            limit=lim,
        )

        print(f"\n[RECOVERY PASS COMPLETED]")
        print(f"  - Duration:                 {result.duration_ms} ms")
        print(f"  - Candidates Found:         {result.candidates_found}")
        print(f"  - Runs Recovered (failed):  {result.recovered_count}")
        print(f"  - Active Leases Skipped:   {result.skipped_active_lease}")
        print(f"  - Errors Encounted:        {result.error_count}")

        if result.recovered_run_ids:
            print(f"  - Recovered Run IDs:       {result.recovered_run_ids}")

        sys.exit(0)

    except Exception as ex:
        print(f"\nFATAL ERROR during recovery execution: {ex}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
