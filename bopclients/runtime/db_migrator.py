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

    EXPECTED_VERSION = "20260902_004"

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
    def _apply_003_upgrades(cls, db: Union[ForgeDB, BopDBConnection], is_pg: bool):
        """Apply migration 20260902_003 column additions to existing research_runs table."""
        if is_pg:
            db.execute("ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS monitoring_schedule_id VARCHAR(36);")
            db.execute("ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS execution_attempt_id VARCHAR(36);")
        else:
            try:
                cols = db.fetch_dicts("PRAGMA table_info(research_runs)")
                col_names = [c["name"] for c in cols]
                if "monitoring_schedule_id" not in col_names:
                    db.execute("ALTER TABLE research_runs ADD COLUMN monitoring_schedule_id VARCHAR(36);")
                if "execution_attempt_id" not in col_names:
                    db.execute("ALTER TABLE research_runs ADD COLUMN execution_attempt_id VARCHAR(36);")
            except Exception as ex:
                logger.warning(f"Error applying 003 columns to SQLite research_runs: {ex}")
        db.commit()

    @classmethod
    def _apply_004_upgrades(cls, db: Union[ForgeDB, BopDBConnection], is_pg: bool):
        """Apply migration 20260902_004 column addition current_execution_attempt_id to monitoring_schedules table."""
        if is_pg:
            db.execute("ALTER TABLE monitoring_schedules ADD COLUMN IF NOT EXISTS current_execution_attempt_id VARCHAR(36);")
        else:
            try:
                cols = db.fetch_dicts("PRAGMA table_info(monitoring_schedules)")
                col_names = [c["name"] for c in cols]
                if "current_execution_attempt_id" not in col_names:
                    db.execute("ALTER TABLE monitoring_schedules ADD COLUMN current_execution_attempt_id VARCHAR(36);")
            except Exception as ex:
                logger.warning(f"Error applying 004 column to SQLite monitoring_schedules: {ex}")
        db.commit()

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

        # 2. Apply 003 upgrades (monitoring_schedule_id, execution_attempt_id)
        cls._apply_003_upgrades(db, is_pg)

        # 3. Apply 004 upgrades (current_execution_attempt_id on monitoring_schedules)
        cls._apply_004_upgrades(db, is_pg)

        # 4. Ensure version table and insert expected version idempotently
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
