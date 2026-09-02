"""DatabaseMigrator managing schema versioning and idempotent migration execution for BopClients."""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from bopclients.infrastructure.db.migrations import run_p1_migrations
from forge.db import ForgeDB

logger = logging.getLogger("bopclients.runtime.migrator")


class DatabaseMigrator:
    """Manager handling database schema versioning and migration execution."""

    EXPECTED_VERSION = "20260902_001"

    @classmethod
    def ensure_version_table(cls, db: ForgeDB):
        """Create version tracking table if not present."""
        create_sql = """
            CREATE TABLE IF NOT EXISTS bopclients_schema_version (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
        """
        db.execute(create_sql)
        db.commit()

    @classmethod
    def get_current_version(cls, db: ForgeDB) -> Optional[str]:
        """Fetch current applied schema version or None if unmigrated."""
        try:
            p = db._placeholder() if hasattr(db, "_placeholder") else "?"
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
    def status(cls, db: ForgeDB) -> Dict[str, Any]:
        """Return migration status dictionary."""
        current = cls.get_current_version(db)
        is_up_to_date = (current == cls.EXPECTED_VERSION)
        return {
            "current_version": current or "unmigrated",
            "expected_version": cls.EXPECTED_VERSION,
            "is_up_to_date": is_up_to_date,
        }

    @classmethod
    def migrate(cls, db: ForgeDB) -> str:
        """Run idempotent schema migration and record schema version.
        
        Returns:
            Applied schema version string.
        """
        current_version = cls.get_current_version(db)
        if current_version and current_version > cls.EXPECTED_VERSION:
            raise ValueError(f"Database schema version '{current_version}' is newer than expected version '{cls.EXPECTED_VERSION}'. Automatic downgrade is prohibited.")

        logger.info(f"Executing database schema migration to target version {cls.EXPECTED_VERSION}")

        # 1. Run DDL schema creation & indexes idempotently
        run_p1_migrations(db)

        # 2. Ensure version table and insert expected version idempotently
        cls.ensure_version_table(db)
        now_iso = datetime.now(timezone.utc).isoformat()

        p = db._placeholder() if hasattr(db, "_placeholder") else "?"
        check_sql = f"SELECT version FROM bopclients_schema_version WHERE version = {p}"
        rows = db.fetch_dicts(check_sql, (cls.EXPECTED_VERSION,))

        if not rows:
            insert_sql = f"INSERT INTO bopclients_schema_version (version, applied_at) VALUES ({p}, {p})"
            db.execute(insert_sql, (cls.EXPECTED_VERSION, now_iso))
            db.commit()

        logger.info(f"Schema migration completed successfully at version {cls.EXPECTED_VERSION}")
        return cls.EXPECTED_VERSION
