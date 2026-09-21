"""Operator CLI for BopClients Durable Research Worker."""

import argparse
import json
import logging
import sys
from typing import Optional

from bopclients.runtime.container import RuntimeContainer
from bopclients.runtime.settings import RuntimeSettings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("bopclients.cli.research_worker")


def parse_args(args=None):
    parser = argparse.ArgumentParser(
        description="BopClients Durable Research Worker CLI (Run-once batch execution)",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        default=False,
        help="Execute a single batch sweep of pending ResearchRuns and exit",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        default=False,
        help="Run continuously as a persistent background service (polling loop)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Polling interval in seconds when idle in continuous mode (default: 2.0s)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Maximum pending research runs to claim in this sweep (default: 10)",
    )
    parser.add_argument(
        "--tenant",
        type=str,
        default=None,
        help="Optional organization_id to restrict research execution to a specific tenant",
    )
    parser.add_argument(
        "--worker-id",
        type=str,
        default=None,
        help="Optional worker instance diagnostic identifier",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="deterministic",
        help="Research provider to use (default: deterministic)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output structured JSON summary to stdout",
    )
    return parser.parse_args(args)


def main(args=None, container: Optional[RuntimeContainer] = None) -> int:
    opts = parse_args(args)
    settings = RuntimeSettings.from_env()

    try:
        if container is None:
            container = RuntimeContainer.initialize(settings=settings)
        worker = container.research_worker
        if not worker:
            logger.error("ResearchWorker is not wired into container.")
            return 1

        if opts.continuous:
            stop_requested = False

            def handle_signal(sig, frame):
                nonlocal stop_requested
                logger.info(f"Signal {sig} received, requesting graceful shutdown...")
                stop_requested = True

            import signal
            try:
                signal.signal(signal.SIGINT, handle_signal)
                signal.signal(signal.SIGTERM, handle_signal)
            except Exception:
                pass

            logger.info("Starting ResearchWorker persistent continuous service...")
            total = worker.run_continuous(
                batch_size=opts.batch_size,
                poll_interval=opts.poll_interval,
                org_id=opts.tenant,
                worker_id=opts.worker_id,
                provider=opts.provider,
                should_stop=lambda: stop_requested,
            )
            logger.info(f"ResearchWorker service exited cleanly. Total completed runs: {total}")
            return 0

        # Default or --run-once: single batch sweep
        result = worker.run_once(
            batch_size=opts.batch_size,
            org_id=opts.tenant,
            worker_id=opts.worker_id,
            provider=opts.provider,
        )

        if opts.json:
            print(json.dumps(result.safe_summary(), indent=2))
        else:
            print("Research Worker Execution Result:")
            print(f"  Worker ID:  {result.worker_id}")
            print(f"  Scanned:    {result.scanned}")
            print(f"  Claimed:    {result.claimed}")
            print(f"  Completed:  {result.completed}")
            print(f"  Failed:     {result.failed}")
            print(f"  Skipped:    {result.skipped}")
            print(f"  Duration:   {result.duration_seconds:.2f}s")

        return 0 if result.failed == 0 else 2
    except Exception as exc:
        logger.error(f"Fatal research worker error: {exc}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
