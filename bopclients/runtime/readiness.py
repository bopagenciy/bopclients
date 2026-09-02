"""RuntimeReadinessCheck evaluating database connection, schema version, table/index existence, and provider readiness."""

import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.infrastructure.db.connection import create_database_connection, BopDBConnection, PostgresConnectionAdapter
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend

logger = logging.getLogger("bopclients.runtime.readiness")


class ReadinessStatus(str, Enum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    NOT_READY = "NOT_READY"


@dataclass
class ReadinessCheckResult:
    """Consolidated result of a RuntimeReadinessCheck evaluation."""

    status: ReadinessStatus
    database_connected: bool
    schema_version: str
    expected_schema_version: str
    tables_present: bool
    provider_matrix: Dict[str, str]  # provider_name -> STATUS (READY, SKIPPED_NO_KEY, SKIPPED_NO_BACKEND, DISABLED)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def safe_summary(self) -> Dict[str, Any]:
        """Return safe dictionary summary without revealing secrets."""
        return {
            "status": self.status.value,
            "database_connected": self.database_connected,
            "schema_version": self.schema_version,
            "expected_schema_version": self.expected_schema_version,
            "tables_present": self.tables_present,
            "provider_matrix": self.provider_matrix,
            "warnings": self.warnings,
            "errors": self.errors,
        }


class RuntimeReadinessCheck:
    """Evaluator evaluating production environment readiness."""

    REQUIRED_TABLES = [
        "organizations",
        "campaigns",
        "prospects",
        "campaign_prospects",
        "monitoring_schedules",
        "signal_observations",
        "research_runs",
        "bopclients_schema_version",
    ]

    REQUIRED_INDEXES = [
        "idx_schedules_org_due",
        "idx_schedules_org_prospect",
        "idx_schedules_lease",
        "idx_research_runs_stale",
    ]

    @classmethod
    def check(cls, settings: RuntimeSettings, db: Optional[Any] = None) -> ReadinessCheckResult:
        """Perform non-destructive environment readiness check.
        
        Args:
            settings: RuntimeSettings instance.
            db: Optional existing DB connection (ForgeDB or BopDBConnection).
        """
        warnings: List[str] = []
        errors: List[str] = []
        db_connected = False
        schema_version = "unmigrated"
        tables_present = False

        # 1. Validate Environment Settings (Fail-Closed DB scheme check)
        try:
            settings.validate()
        except Exception as ex:
            errors.append(f"Invalid runtime configuration: {ex}")

        # 2. Check DB Connection & Schema
        conn_db = db
        close_needed = False
        if not conn_db and not errors:
            try:
                conn_db = create_database_connection(settings.database_url)
                close_needed = True
                db_connected = True
            except Exception as ex:
                errors.append(f"Database connection failed ({settings.mask_database_url()}): {ex}")
        elif conn_db:
            db_connected = True

        if db_connected and conn_db:
            try:
                schema_version = DatabaseMigrator.get_current_version(conn_db) or "unmigrated"
                if schema_version != DatabaseMigrator.EXPECTED_VERSION:
                    errors.append(f"Database schema version mismatch (found '{schema_version}', expected '{DatabaseMigrator.EXPECTED_VERSION}'). Migration required.")

                is_pg = getattr(conn_db, "backend_name", "") == "postgresql" or isinstance(conn_db, PostgresConnectionAdapter)

                # Verify Table Existence
                if is_pg:
                    check_tbl_sql = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name = %s"
                else:
                    p = conn_db._placeholder() if hasattr(conn_db, "_placeholder") else "?"
                    check_tbl_sql = f"SELECT name FROM sqlite_master WHERE type='table' AND name = {p}"

                found_tables = set()
                for tbl in cls.REQUIRED_TABLES:
                    rows = conn_db.fetch_dicts(check_tbl_sql, (tbl,))
                    if rows:
                        found_tables.add(tbl)

                missing_tables = set(cls.REQUIRED_TABLES) - found_tables
                if missing_tables:
                    errors.append(f"Missing required database tables: {sorted(list(missing_tables))}. Migration required.")
                else:
                    tables_present = True

                # Verify Index Existence
                if is_pg:
                    check_idx_sql = "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND indexname = %s"
                else:
                    p = conn_db._placeholder() if hasattr(conn_db, "_placeholder") else "?"
                    check_idx_sql = f"SELECT name FROM sqlite_master WHERE type='index' AND name = {p}"

                found_indexes = set()
                for idx in cls.REQUIRED_INDEXES:
                    rows = conn_db.fetch_dicts(check_idx_sql, (idx,))
                    if rows:
                        found_indexes.add(idx)

                missing_indexes = set(cls.REQUIRED_INDEXES) - found_indexes
                if missing_indexes:
                    warnings.append(f"Missing recommended database indexes: {sorted(list(missing_indexes))}.")

            except Exception as ex:
                errors.append(f"Database inspection failed: {ex}")
            finally:
                if close_needed and conn_db:
                    try:
                        conn_db.close()
                    except Exception:
                        pass

        # 3. Provider Readiness Matrix Evaluation
        provider_matrix: Dict[str, str] = {}
        enabled_lower = [p.lower() for p in settings.enabled_providers]

        # Official Website Provider
        if "official_website" in enabled_lower:
            provider_matrix["official_website"] = "READY"
        else:
            provider_matrix["official_website"] = "DISABLED"

        # Government Procurement Provider
        if "government_procurement" in enabled_lower:
            if settings.sam_gov_api_key:
                provider_matrix["government_procurement"] = "READY"
            else:
                provider_matrix["government_procurement"] = "SKIPPED_NO_KEY"
                warnings.append("Provider 'government_procurement' enabled but SAM_GOV_API_KEY is unconfigured. Execution will skip SAM scans.")
        else:
            provider_matrix["government_procurement"] = "DISABLED"

        # Public News Provider (Always SKIPPED_NO_BACKEND until live search backend is connected)
        if "public_news" in enabled_lower:
            provider_matrix["public_news"] = "SKIPPED_NO_BACKEND"
            warnings.append("Provider 'public_news' enabled but live news search backend is not connected. Execution will skip news scans.")
        else:
            provider_matrix["public_news"] = "DISABLED"

        # Gemini Provider
        if "gemini" in enabled_lower or "gemini_research" in enabled_lower:
            if settings.gemini_api_key:
                provider_matrix["gemini"] = "READY"
            else:
                provider_matrix["gemini"] = "SKIPPED_NO_KEY"
                warnings.append("Provider 'gemini' enabled but GEMINI_API_KEY is unconfigured.")
        else:
            provider_matrix["gemini"] = "DISABLED"

        # Determine Final Status
        if errors:
            final_status = ReadinessStatus.NOT_READY
        elif warnings or any(v.startswith("SKIPPED") for v in provider_matrix.values()):
            final_status = ReadinessStatus.DEGRADED
        else:
            final_status = ReadinessStatus.READY

        return ReadinessCheckResult(
            status=final_status,
            database_connected=db_connected,
            schema_version=schema_version,
            expected_schema_version=DatabaseMigrator.EXPECTED_VERSION,
            tables_present=tables_present,
            provider_matrix=provider_matrix,
            warnings=warnings,
            errors=errors,
        )
