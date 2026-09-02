"""CLI entry point for runtime environment readiness check inspection."""

import sys
import json
import argparse
import logging
from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def main():
    parser = argparse.ArgumentParser(description="BopClients Production Runtime Readiness Check CLI")
    parser.add_argument("--json", action="store_true", help="Output readiness check result in JSON format.")
    args = parser.parse_args()

    settings = RuntimeSettings.from_env()
    result = RuntimeReadinessCheck.check(settings)

    if args.json:
        print(json.dumps(result.safe_summary(), indent=2))
    else:
        print("==================================================")
        print("BOPCLIENTS RUNTIME READINESS CHECK REPORT")
        print("==================================================")
        print(f"STATUS:               {result.status.value}")
        print(f"Environment:          {settings.environment.value}")
        print(f"Database URL:         {settings.mask_database_url()}")
        print(f"Database Connected:   {result.database_connected}")
        print(f"Schema Version:       {result.schema_version} (Expected: {result.expected_schema_version})")
        print(f"Tables Present:       {result.tables_present}")
        print("Provider Matrix:")
        for name, status_str in result.provider_matrix.items():
            print(f"  - {name:<24}: {status_str}")

        if result.warnings:
            print("\nWarnings:")
            for w in result.warnings:
                print(f"  - WARNING: {w}")

        if result.errors:
            print("\nErrors:")
            for err in result.errors:
                print(f"  - ERROR: {err}")
        print("==================================================")

    # Exit code: 0 if READY or DEGRADED, 1 if NOT_READY
    exit_code = 0 if result.status in (ReadinessStatus.READY, ReadinessStatus.DEGRADED) else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
