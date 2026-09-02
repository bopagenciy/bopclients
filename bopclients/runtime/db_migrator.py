"""DatabaseMigrator managing schema versioning and idempotent migration execution for BopClients."""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Union
from bopclients.infrastructure.db.migrations import run_p1_migrations
from bopclients.infrastructure.db.postgres_ddl import run_postgres_migrations
from bopclients.infrastructure.db.connection import BopDBConnection, SQLiteConnectionAdapter, PostgresConnectionAdapter
from forge.db import ForgeDB

logger = logging.getLogger("bopclients.runtime.migrator")


class DatabaseMigrator:
    """Manager handling database schema versioning and migration execution."""

    EXPECTED_VERSION = "20260902_002"

    @classmethod
    def ensure_version_table(cls, db: Union[ForgeDB, BopDBConnection]):
        """Create version tracking table if not present."""
        if isinstance(db, PostgresConnectionAdapter) or getattr(db, "backend_name", "") == "postgresql":
            p = "%s"
            sql = """
                CREATE TABLE IF NOT EXISTS bopclients_schema_version (
                    version VARCHAR(64) PRIMARY KEY,
                    applied_at VARCHAR(64) NOT NULL
                );
            """
        else:
            p = "?"
            sql = """
                CREATE TABLE IF NOT EXISTS bopclients_schema_version (
                    version TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
            """
        db.execute(sql)
        db.commit()

    @classmethod
    def get_current_version(cls, db: Union[ForgeDB, BopDBConnection]) -> Optional[str]:
        """Fetch current applied schema version or None if unmigrated."""
        try:
            is_pg = isinstance(db, PostgresConnectionAdapter) or getattr(db, "backend_name", "") == "postgresql"
            p = "%s" if is_pg else "?"

            if is_pg:
                check_sql = f"SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name = {p}"
            else:
                check_sql = f"SELECT name FROM sqlite_master WHERE type='table' AND name = {p}"

            rows = db.fetch_dicts(check_sql, ("bopclients_schema_version",))
            if not rows:
                return None

            ver_rows = db.fetch_dicts("SELECT version FROM bopclients_schema_version ORDER BY applied_at DESC LIMIT 1")
            if ver_rows:
                return ver_rows[0]["version"]
            return None
        except Exception:
            return None

    @classmethod
    def status(cls, db: Union[ForgeDB, BopDBConnection]) -> Dict[str, Any]:
        """Return migration status dictionary."""
        current = cls.get_current_version(db)
        is_up_to_date = (current == cls.EXPECTED_VERSION)
        return {
            "current_version": current or "unmigrated",
            "expected_version": cls.EXPECTED_VERSION,
            "is_up_to_date": is_up_to_date,
        }

    @classmethod
    def migrate(cls, db: Union[ForgeDB, BopDBConnection]) -> str:
        """Run idempotent schema migration and record schema version.
        
        Returns:
            Applied schema version string.
        """
        current_version = cls.get_current_version(db)
        if current_version and current_version > cls.EXPECTED_VERSION:
            raise ValueError(f"Database schema version '{current_version}' is newer than expected version '{cls.EXPECTED_VERSION}'. Automatic downgrade is prohibited.")

        logger.info(f"Executing database schema migration to target version {cls.EXPECTED_VERSION}")
        is_pg = isinstance(db, PostgresConnectionAdapter) or getattr(db, "backend_name", "") == "postgresql"

        # 1. Run DDL schema creation & indexes idempotently
        if is_pg:
            run_postgres_migrations(db)
        else:
            if isinstance(db, ForgeDB):
                run_p1_migrations(db)
            else:
                run_p1_migrations(db.forge_db)

        # 2. Ensure version table and insert expected version idempotently
        cls.ensure_version_table(db)
        now_iso = datetime.now(timezone.utc).isoformat()
        p = "%s" if is_pg else "?"

        check_sql = f"SELECT version FROM bopclients_schema_version WHERE version = {p}"
        rows = db.fetch_dicts(check_sql, (cls.EXPECTED_VERSION,))

        if not rows:
            insert_sql = f"INSERT INTO bopclients_schema_version (version, applied_at) VALUES ({p}, {p})"
            db.execute(insert_sql, (cls.EXPECTED_VERSION, now_iso))
            db.commit()

        logger.info(f"Schema migration completed successfully at version {cls.EXPECTED_VERSION}")
        return cls.EXPECTED_VERSION
