"""Operator CLI for BopClients Integration Outbox Publisher."""

import argparse
import json
import logging
import sys
from typing import Optional

from bopclients.runtime.container import RuntimeContainer
from bopclients.runtime.settings import RuntimeSettings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("bopclients.cli.integration_publisher")


def parse_args(args=None):
    parser = argparse.ArgumentParser(
        description="BopClients Integration Outbox Publisher Worker CLI (Run-once batch delivery)",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        default=True,
        help="Execute a single batch sweep and exit (default: True)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Override batch size of outbox events and deliveries to process",
    )
    parser.add_argument(
        "--tenant",
        type=str,
        default=None,
        help="Optional bop_organization_id to restrict dispatching to a specific tenant",
    )
    parser.add_argument(
        "--worker-id",
        type=str,
        default=None,
        help="Optional worker instance diagnostic identifier",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="Check schema and readiness without running publisher",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview pending outbox events and due deliveries without mutating DB or making network calls",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output structured JSON summary to stdout",
    )
    return parser.parse_args(args)


def main(args=None) -> int:
    opts = parse_args(args)
    settings = RuntimeSettings.from_env()

    try:
        container = RuntimeContainer.initialize(settings=settings)
        worker = container.integration_publisher_worker

        if opts.check:
            summary = worker.check()
            if opts.json:
                print(json.dumps(summary, indent=2))
            else:
                print("Integration Publisher Check:")
                for k, v in summary.items():
                    print(f"  {k}: {v}")
            return 0

        if opts.dry_run:
            summary = worker.dry_run(
                batch_size=opts.batch_size,
                bop_organization_id=opts.tenant,
            )
            if opts.json:
                print(json.dumps(summary, indent=2))
            else:
                print("Integration Publisher Dry Run:")
                for k, v in summary.items():
                    print(f"  {k}: {v}")
            return 0

        result = worker.run_once(
            worker_id=opts.worker_id,
            batch_size=opts.batch_size,
            bop_organization_id=opts.tenant,
        )

        summary = result.safe_summary()

        if opts.json:
            print(json.dumps(summary, indent=2))
        else:
            print(f"Integration Publisher Run Completed:")
            print(f"  Worker ID:           {summary.get('worker_id')}")
            print(f"  Duration:            {summary['duration_seconds']}s")
            print(f"  Routing Scanned:     {summary['routing_scanned']}")
            print(f"  Deliveries Created:  {summary['deliveries_created']}")
            print(f"  Unrouted Events:     {summary['unrouted_events']}")
            print(f"  Deliveries Claimed:  {summary['deliveries_claimed']}")
            print(f"  Delivered:           {summary['delivered']}")
            print(f"  Retried:             {summary['retried']}")
            print(f"  Dead Letter:         {summary['dead_letter']}")
            print(f"  Events Completed:    {summary['events_completed']}")

        return 0

    except Exception as ex:
        logger.error(f"Fatal error running integration publisher CLI: {ex}", exc_info=True)
        if opts.json:
            print(json.dumps({"status": "ERROR", "error": str(ex)}, indent=2))
        else:
            print(f"ERROR: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
