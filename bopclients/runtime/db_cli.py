"""CLI entry point for database schema migration status inspection and migration execution."""

import sys
import json
import argparse
import logging
from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.db_migrator import DatabaseMigrator
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("bopclients.runtime.db_cli")


def main():
    parser = argparse.ArgumentParser(description="BopClients Production Database Migration CLI")
    parser.add_argument("action", choices=["status", "migrate"], help="Action to execute: 'status' to inspect schema version, 'migrate' to apply schema updates.")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format.")
    args = parser.parse_args()

    settings = RuntimeSettings.from_env()
    db = ForgeDB(_SQLiteBackend(db_path=settings.database_url))

    if args.action == "status":
        info = DatabaseMigrator.status(db)
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            print("==================================================")
            print("BOPCLIENTS DATABASE MIGRATION STATUS")
            print("==================================================")
            print(f"Database Target:  {settings.mask_database_url()}")
            print(f"Current Version:  {info['current_version']}")
            print(f"Expected Version: {info['expected_version']}")
            print(f"Is Up To Date:    {info['is_up_to_date']}")
            print("==================================================")
        sys.exit(0 if info["is_up_to_date"] else 1)

    elif args.action == "migrate":
        logger.info(f"Starting database migration on {settings.mask_database_url()}...")
        applied_ver = DatabaseMigrator.migrate(db)
        if args.json:
            print(json.dumps({"status": "SUCCESS", "applied_version": applied_ver}, indent=2))
        else:
            print("==================================================")
            print("BOPCLIENTS DATABASE MIGRATION COMPLETED")
            print("==================================================")
            print(f"Database Target: {settings.mask_database_url()}")
            print(f"Schema Version:  {applied_ver}")
            print("==================================================")
        sys.exit(0)


if __name__ == "__main__":
    main()
