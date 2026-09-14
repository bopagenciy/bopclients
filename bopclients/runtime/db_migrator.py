"""DatabaseMigrator managing schema versioning and idempotent migration execution for BopClients."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Union
from bopclients.infrastructure.db.migrations import run_p1_migrations
from bopclients.infrastructure.db.postgres_ddl import run_postgres_migrations
from bopclients.infrastructure.db.connection import BopDBConnection, SQLiteConnectionAdapter, PostgresConnectionAdapter
from forge.db import ForgeDB

logger = logging.getLogger("bopclients.runtime.migrator")


class DatabaseMigrator:
    """Manager handling database schema versioning and migration execution."""

    EXPECTED_VERSION = "20260902_009"

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
    def _apply_005_upgrades(cls, db: Union[ForgeDB, BopDBConnection], is_pg: bool):
        """Apply migration 20260902_005 creating provider_rate_limit_state and provider_rate_limit_leases."""
        # 1. provider_rate_limit_state
        state_sql = """
            CREATE TABLE IF NOT EXISTS provider_rate_limit_state (
                id VARCHAR(36) PRIMARY KEY,
                provider_key VARCHAR(50) NOT NULL,
                scope_key VARCHAR(150) NOT NULL,
                window_started_at VARCHAR(50) NOT NULL,
                execution_count INTEGER NOT NULL DEFAULT 0,
                cooldown_until VARCHAR(50),
                last_status_code INTEGER,
                last_retry_after_seconds INTEGER,
                updated_at VARCHAR(50) NOT NULL,
                UNIQUE (provider_key, scope_key)
            );
        """
        db.execute(state_sql)

        # Ensure execution_count column is present if table was pre-created with request_count
        try:
            if is_pg:
                db.execute("""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='provider_rate_limit_state' AND column_name='request_count'
                        ) THEN
                            ALTER TABLE provider_rate_limit_state RENAME COLUMN request_count TO execution_count;
                        END IF;
                    END $$;
                """)
            else:
                cols = [c["name"] for c in db.fetch_dicts("PRAGMA table_info(provider_rate_limit_state)")]
                if "request_count" in cols and "execution_count" not in cols:
                    db.execute("ALTER TABLE provider_rate_limit_state RENAME COLUMN request_count TO execution_count")
        except Exception as ex:
            logger.debug(f"Column migration compatibility notice: {ex}")

        # 2. provider_rate_limit_leases
        leases_sql = """
            CREATE TABLE IF NOT EXISTS provider_rate_limit_leases (
                id VARCHAR(36) PRIMARY KEY,
                provider_key VARCHAR(50) NOT NULL,
                scope_key VARCHAR(150) NOT NULL,
                lease_token VARCHAR(64) NOT NULL,
                permit_id VARCHAR(36) NOT NULL,
                expires_at VARCHAR(50) NOT NULL,
                created_at VARCHAR(50) NOT NULL,
                UNIQUE (lease_token)
            );
        """
        db.execute(leases_sql)

        # 3. Indexes
        idx_stmts = [
            "CREATE INDEX IF NOT EXISTS idx_rate_limit_state_lookup ON provider_rate_limit_state(provider_key, scope_key);",
            "CREATE INDEX IF NOT EXISTS idx_rate_limit_state_cooldown ON provider_rate_limit_state(cooldown_until);",
            "CREATE INDEX IF NOT EXISTS idx_rate_limit_leases_active ON provider_rate_limit_leases(provider_key, scope_key, expires_at);",
            "CREATE INDEX IF NOT EXISTS idx_rate_limit_leases_token ON provider_rate_limit_leases(lease_token);",
        ]
        for idx in idx_stmts:
            db.execute(idx)

        db.commit()

    @classmethod
    def _apply_006_upgrades(cls, db: Union[ForgeDB, BopDBConnection], is_pg: bool):
        """Apply migration 20260902_006 creating scheduler_dispatch_state and scheduler_runs."""
        # 1. scheduler_dispatch_state
        state_sql = """
            CREATE TABLE IF NOT EXISTS scheduler_dispatch_state (
                scheduler_key VARCHAR(64) PRIMARY KEY,
                lease_token VARCHAR(64),
                lease_expires_at VARCHAR(50),
                last_started_at VARCHAR(50),
                last_completed_at VARCHAR(50),
                last_status VARCHAR(50),
                last_worker_run_id VARCHAR(36),
                current_run_id VARCHAR(36),
                updated_at VARCHAR(50) NOT NULL
            );
        """
        db.execute(state_sql)

        # 2. scheduler_runs
        runs_sql = """
            CREATE TABLE IF NOT EXISTS scheduler_runs (
                id VARCHAR(36) PRIMARY KEY,
                scheduler_key VARCHAR(64) NOT NULL,
                started_at VARCHAR(50) NOT NULL,
                completed_at VARCHAR(50),
                status VARCHAR(50) NOT NULL,
                worker_run_id VARCHAR(36),
                worker_stopped_reason VARCHAR(50),
                items_attempted INTEGER NOT NULL DEFAULT 0,
                items_claimed INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                backpressure_count INTEGER NOT NULL DEFAULT 0,
                error_code VARCHAR(50),
                error_message VARCHAR(500),
                created_at VARCHAR(50) NOT NULL
            );
        """
        db.execute(runs_sql)

        # 3. Indexes
        idx_stmts = [
            "CREATE INDEX IF NOT EXISTS idx_scheduler_runs_key_started ON scheduler_runs(scheduler_key, started_at);",
            "CREATE INDEX IF NOT EXISTS idx_scheduler_runs_status ON scheduler_runs(status, started_at);",
        ]
        for idx in idx_stmts:
            db.execute(idx)

        db.commit()

    @classmethod
    def _apply_007_upgrades(cls, db: Union[ForgeDB, BopDBConnection], is_pg: bool):
        """Apply migration 20260902_007 enforcing NOT NULL bop_organization_id, outbox, and inbox."""
        if is_pg:
            chk_sql = """
                SELECT column_name, is_nullable FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'organizations' AND column_name = 'bop_organization_id'
            """
            rows = db.fetch_dicts(chk_sql)
            if not rows:
                db.execute("ALTER TABLE organizations ADD COLUMN bop_organization_id VARCHAR(36);")
                db.commit()

            # Backfill existing rows where bop_organization_id IS NULL with random UUID v4
            null_rows = db.fetch_dicts(
                "SELECT id FROM organizations WHERE bop_organization_id IS NULL OR bop_organization_id = ''"
            )
            if null_rows:
                for r in null_rows:
                    gen_uuid = str(uuid.uuid4())
                    db.execute("UPDATE organizations SET bop_organization_id = %s WHERE id = %s", (gen_uuid, r["id"]))
                db.commit()

            # Enforce NOT NULL at database level
            db.execute("ALTER TABLE organizations ALTER COLUMN bop_organization_id SET NOT NULL;")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_bop_org_id ON organizations(bop_organization_id);")
            db.commit()
        else:
            pragma_rows = db.fetch_dicts("PRAGMA table_info(organizations);")
            bop_col = next((r for r in pragma_rows if r.get("name") == "bop_organization_id"), None)
            is_not_null = bop_col and bop_col.get("notnull") == 1

            if not bop_col or not is_not_null:
                # Table rebuild to enforce NOT NULL constraint at SQLite database level
                # PRAGMA foreign_keys must be toggled outside the active transaction
                db.execute("PRAGMA foreign_keys = OFF;")
                try:
                    db.begin()
                    db.execute("""
                        CREATE TABLE IF NOT EXISTS organizations_p17 (
                            id VARCHAR(36) PRIMARY KEY,
                            bop_organization_id VARCHAR(36) NOT NULL UNIQUE,
                            name VARCHAR(255) NOT NULL,
                            slug VARCHAR(100) UNIQUE NOT NULL,
                            description TEXT,
                            website VARCHAR(255),
                            country VARCHAR(10) NOT NULL DEFAULT 'US',
                            default_language VARCHAR(10) NOT NULL DEFAULT 'en',
                            timezone VARCHAR(50) NOT NULL DEFAULT 'UTC',
                            created_at VARCHAR(50) NOT NULL,
                            updated_at VARCHAR(50) NOT NULL
                        );
                    """)
                    existing_orgs = db.fetch_dicts("SELECT * FROM organizations;")
                    for org in existing_orgs:
                        bop_id = org.get("bop_organization_id")
                        if not bop_id:
                            bop_id = str(uuid.uuid4())
                        db.execute(
                            """
                            INSERT INTO organizations_p17 (
                                id, bop_organization_id, name, slug, description, website,
                                country, default_language, timezone, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                org["id"],
                                bop_id,
                                org["name"],
                                org["slug"],
                                org.get("description"),
                                org.get("website"),
                                org.get("country", "US"),
                                org.get("default_language", "en"),
                                org.get("timezone", "UTC"),
                                org["created_at"],
                                org["updated_at"],
                            ),
                        )
                    db.execute("DROP TABLE organizations;")
                    db.execute("ALTER TABLE organizations_p17 RENAME TO organizations;")
                    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_bop_org_id ON organizations(bop_organization_id);")
                    db.commit()
                except Exception:
                    db.rollback()
                    raise
                finally:
                    db.execute("PRAGMA foreign_keys = ON;")
            else:
                null_rows = db.fetch_dicts(
                    "SELECT id FROM organizations WHERE bop_organization_id IS NULL OR bop_organization_id = ''"
                )
                for r in null_rows:
                    db.execute("UPDATE organizations SET bop_organization_id = ? WHERE id = ?", (str(uuid.uuid4()), r["id"]))
                db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_bop_org_id ON organizations(bop_organization_id);")
                db.commit()

        # 4. Create or upgrade bop_integration_outbox
        outbox_sql = """
            CREATE TABLE IF NOT EXISTS bop_integration_outbox (
                id VARCHAR(36) PRIMARY KEY,
                event_id VARCHAR(36) NOT NULL UNIQUE,
                bop_organization_id VARCHAR(36) NOT NULL,
                event_type VARCHAR(100) NOT NULL,
                event_version INTEGER NOT NULL DEFAULT 1,
                producer_app VARCHAR(50) NOT NULL,
                subject_bop_org_id VARCHAR(36) NOT NULL,
                subject_application_id VARCHAR(50) NOT NULL,
                subject_entity_type VARCHAR(50) NOT NULL,
                subject_entity_id VARCHAR(128) NOT NULL,
                correlation_id VARCHAR(36) NOT NULL,
                causation_id VARCHAR(128),
                envelope_json TEXT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                available_at VARCHAR(50) NOT NULL,
                created_at VARCHAR(50) NOT NULL,
                published_at VARCHAR(50),
                last_error_code VARCHAR(50),
                last_error_message VARCHAR(500)
            );
        """
        db.execute(outbox_sql)

        # Ensure missing columns exist if upgrading from earlier intermediate table
        if is_pg:
            chk_corr = db.fetch_dicts(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'bop_integration_outbox' AND column_name = 'correlation_id'"
            )
            if not chk_corr:
                db.execute("ALTER TABLE bop_integration_outbox ADD COLUMN IF NOT EXISTS subject_bop_org_id VARCHAR(36);")
                db.execute("ALTER TABLE bop_integration_outbox ADD COLUMN IF NOT EXISTS correlation_id VARCHAR(36);")
                db.execute("ALTER TABLE bop_integration_outbox ADD COLUMN IF NOT EXISTS causation_id VARCHAR(128);")
                db.commit()
        else:
            chk_cols = db.fetch_dicts("PRAGMA table_info(bop_integration_outbox);")
            col_names = {r.get("name") for r in chk_cols}
            if chk_cols and "correlation_id" not in col_names:
                db.execute("ALTER TABLE bop_integration_outbox ADD COLUMN subject_bop_org_id VARCHAR(36);")
                db.execute("ALTER TABLE bop_integration_outbox ADD COLUMN correlation_id VARCHAR(36);")
                db.execute("ALTER TABLE bop_integration_outbox ADD COLUMN causation_id VARCHAR(128);")
                db.commit()

        # 5. Create or upgrade bop_integration_inbox
        inbox_sql = """
            CREATE TABLE IF NOT EXISTS bop_integration_inbox (
                id VARCHAR(36) PRIMARY KEY,
                event_id VARCHAR(36) NOT NULL UNIQUE,
                producer_app VARCHAR(50) NOT NULL,
                bop_organization_id VARCHAR(36) NOT NULL,
                event_type VARCHAR(100) NOT NULL,
                event_version INTEGER NOT NULL DEFAULT 1,
                envelope_json TEXT NOT NULL DEFAULT '{}',
                received_at VARCHAR(50) NOT NULL,
                processed_at VARCHAR(50),
                status VARCHAR(20) NOT NULL DEFAULT 'RECEIVED',
                last_error_code VARCHAR(50),
                last_error_message VARCHAR(500)
            );
        """
        db.execute(inbox_sql)

        if is_pg:
            chk_inbox_env = db.fetch_dicts(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'bop_integration_inbox' AND column_name = 'envelope_json'"
            )
            if not chk_inbox_env:
                db.execute("ALTER TABLE bop_integration_inbox ADD COLUMN IF NOT EXISTS envelope_json TEXT NOT NULL DEFAULT '{}';")
                db.commit()
            chk_inbox_err = db.fetch_dicts(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'bop_integration_inbox' AND column_name = 'last_error_code'"
            )
            if not chk_inbox_err:
                db.execute("ALTER TABLE bop_integration_inbox ADD COLUMN IF NOT EXISTS last_error_code VARCHAR(50);")
                db.execute("ALTER TABLE bop_integration_inbox ADD COLUMN IF NOT EXISTS last_error_message VARCHAR(500);")
                db.commit()
        else:
            chk_inbox_cols = db.fetch_dicts("PRAGMA table_info(bop_integration_inbox);")
            col_inbox_names = {r.get("name") for r in chk_inbox_cols}
            if chk_inbox_cols and "envelope_json" not in col_inbox_names:
                db.execute("ALTER TABLE bop_integration_inbox ADD COLUMN envelope_json TEXT NOT NULL DEFAULT '{}';")
                db.commit()
            if chk_inbox_cols and "last_error_code" not in col_inbox_names:
                db.execute("ALTER TABLE bop_integration_inbox ADD COLUMN last_error_code VARCHAR(50);")
                db.execute("ALTER TABLE bop_integration_inbox ADD COLUMN last_error_message VARCHAR(500);")
                db.commit()

        # 6. Indexes for outbox and inbox
        idx_stmts = [
            "CREATE INDEX IF NOT EXISTS idx_outbox_status_available ON bop_integration_outbox(status, available_at);",
            "CREATE INDEX IF NOT EXISTS idx_outbox_tenant_created ON bop_integration_outbox(bop_organization_id, created_at);",
            "CREATE INDEX IF NOT EXISTS idx_outbox_correlation ON bop_integration_outbox(correlation_id);",
            "CREATE INDEX IF NOT EXISTS idx_inbox_tenant_received ON bop_integration_inbox(bop_organization_id, received_at);",
            "CREATE INDEX IF NOT EXISTS idx_inbox_status ON bop_integration_inbox(status, received_at);",
        ]
        for idx in idx_stmts:
            db.execute(idx)

        db.commit()

    @classmethod
    def _apply_008_upgrades(cls, db: Union[ForgeDB, BopDBConnection], is_pg: bool) -> None:
        """Apply 008 upgrades: integration destinations, subscriptions, deliveries, and delivery attempts."""
        p = "%s" if is_pg else "?"

        # 1. Create bop_integration_destinations
        dest_sql = """
            CREATE TABLE IF NOT EXISTS bop_integration_destinations (
                id VARCHAR(36) PRIMARY KEY,
                bop_organization_id VARCHAR(36) NOT NULL,
                target_app_id VARCHAR(50) NOT NULL,
                destination_name VARCHAR(100) NOT NULL,
                transport_type VARCHAR(20) NOT NULL DEFAULT 'HTTP',
                endpoint_url VARCHAR(500) NOT NULL,
                secret_key_ref VARCHAR(100),
                headers_template_json TEXT,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at VARCHAR(50) NOT NULL,
                updated_at VARCHAR(50) NOT NULL
            );
        """
        db.execute(dest_sql)

        # 2. Create bop_integration_subscriptions
        sub_sql = """
            CREATE TABLE IF NOT EXISTS bop_integration_subscriptions (
                id VARCHAR(36) PRIMARY KEY,
                bop_organization_id VARCHAR(36) NOT NULL,
                destination_id VARCHAR(36) NOT NULL,
                event_type VARCHAR(100) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at VARCHAR(50) NOT NULL,
                FOREIGN KEY (destination_id) REFERENCES bop_integration_destinations(id) ON DELETE CASCADE
            );
        """
        db.execute(sub_sql)

        # 3. Create bop_integration_deliveries
        deliv_sql = """
            CREATE TABLE IF NOT EXISTS bop_integration_deliveries (
                id VARCHAR(36) PRIMARY KEY,
                event_id VARCHAR(36) NOT NULL,
                destination_id VARCHAR(36) NOT NULL,
                bop_organization_id VARCHAR(36) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 5,
                next_attempt_at VARCHAR(50) NOT NULL,
                claim_token VARCHAR(64),
                claim_expires_at VARCHAR(50),
                delivered_at VARCHAR(50),
                last_error_code VARCHAR(50),
                last_error_message VARCHAR(500),
                created_at VARCHAR(50) NOT NULL,
                updated_at VARCHAR(50) NOT NULL,
                FOREIGN KEY (destination_id) REFERENCES bop_integration_destinations(id) ON DELETE RESTRICT,
                UNIQUE (event_id, destination_id)
            );
        """
        db.execute(deliv_sql)

        if is_pg:
            # If table existed with legacy CASCADE, upgrade constraint to RESTRICT
            chk_fk = db.fetch_dicts("""
                SELECT rc.constraint_name, rc.delete_rule
                FROM information_schema.referential_constraints rc
                JOIN information_schema.table_constraints tc ON rc.constraint_name = tc.constraint_name
                WHERE tc.table_name = 'bop_integration_deliveries' AND rc.delete_rule = 'CASCADE';
            """)
            for fk in chk_fk:
                cname = fk["constraint_name"]
                db.execute(f"ALTER TABLE bop_integration_deliveries DROP CONSTRAINT IF EXISTS {cname};")
                db.execute("ALTER TABLE bop_integration_deliveries ADD CONSTRAINT bop_integration_deliveries_destination_id_fkey FOREIGN KEY (destination_id) REFERENCES bop_integration_destinations(id) ON DELETE RESTRICT;")
                db.commit()

        # 4. Create bop_integration_delivery_attempts
        att_sql = """
            CREATE TABLE IF NOT EXISTS bop_integration_delivery_attempts (
                id VARCHAR(36) PRIMARY KEY,
                delivery_id VARCHAR(36) NOT NULL,
                attempt_number INTEGER NOT NULL,
                started_at VARCHAR(50) NOT NULL,
                finished_at VARCHAR(50) NOT NULL,
                status VARCHAR(20) NOT NULL,
                status_code INTEGER,
                error_code VARCHAR(50),
                error_message VARCHAR(500),
                response_body_sample VARCHAR(1000),
                FOREIGN KEY (delivery_id) REFERENCES bop_integration_deliveries(id) ON DELETE CASCADE
            );
        """
        db.execute(att_sql)

        # 5. Create P18 indexes
        idx_stmts = [
            "CREATE INDEX IF NOT EXISTS idx_dest_tenant ON bop_integration_destinations(bop_organization_id, is_active);",
            "CREATE INDEX IF NOT EXISTS idx_sub_event_type ON bop_integration_subscriptions(bop_organization_id, event_type, is_active);",
            "CREATE INDEX IF NOT EXISTS idx_deliv_due_claim ON bop_integration_deliveries(status, next_attempt_at);",
            "CREATE INDEX IF NOT EXISTS idx_deliv_tenant ON bop_integration_deliveries(bop_organization_id, status);",
            "CREATE INDEX IF NOT EXISTS idx_deliv_claim_lease ON bop_integration_deliveries(claim_expires_at);",
            "CREATE INDEX IF NOT EXISTS idx_deliv_att_delivery ON bop_integration_delivery_attempts(delivery_id, attempt_number);",
        ]
        for idx in idx_stmts:
            db.execute(idx)

        db.commit()

    @classmethod
    def _apply_009_upgrades(cls, db: Union[ForgeDB, BopDBConnection], is_pg: bool) -> None:
        """Apply migration 20260902_009: user auth fields, auth sessions, login attempts."""
        # 1. Check and add missing columns to users table
        if is_pg:
            chk_cols_sql = """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'users'
            """
            user_cols = {r["column_name"] for r in db.fetch_dicts(chk_cols_sql)}
            if "password_hash" not in user_cols:
                db.execute("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255);")
            if "is_active" not in user_cols:
                db.execute("ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT true;")
            if "locale" not in user_cols:
                db.execute("ALTER TABLE users ADD COLUMN locale VARCHAR(10) NOT NULL DEFAULT 'en';")
            db.commit()
        else:
            pragma_sql = "PRAGMA table_info(users)"
            user_cols = {r["name"] for r in db.fetch_dicts(pragma_sql)}
            if "password_hash" not in user_cols:
                db.execute("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255);")
            if "is_active" not in user_cols:
                db.execute("ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1;")
            if "locale" not in user_cols:
                db.execute("ALTER TABLE users ADD COLUMN locale VARCHAR(10) NOT NULL DEFAULT 'en';")
            db.commit()

        # 2. Create bop_auth_sessions
        sessions_sql = """
            CREATE TABLE IF NOT EXISTS bop_auth_sessions (
                id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                token_hash VARCHAR(64) UNIQUE NOT NULL,
                created_at VARCHAR(50) NOT NULL,
                expires_at VARCHAR(50) NOT NULL,
                revoked_at VARCHAR(50),
                last_used_at VARCHAR(50),
                user_agent_hash VARCHAR(64),
                ip_address VARCHAR(45),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """
        db.execute(sessions_sql)

        # 3. Create bop_auth_login_attempts
        attempts_sql = """
            CREATE TABLE IF NOT EXISTS bop_auth_login_attempts (
                id VARCHAR(36) PRIMARY KEY,
                identifier_hash VARCHAR(64) NOT NULL,
                attempt_time VARCHAR(50) NOT NULL,
                is_successful BOOLEAN NOT NULL
            );
        """
        db.execute(attempts_sql)

        # 4. Create P19 indexes
        idx_stmts = [
            "CREATE INDEX IF NOT EXISTS idx_auth_sessions_token_hash ON bop_auth_sessions(token_hash);",
            "CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON bop_auth_sessions(user_id, expires_at);",
            "CREATE INDEX IF NOT EXISTS idx_login_attempts_lookup ON bop_auth_login_attempts(identifier_hash, attempt_time);",
        ]
        for idx in idx_stmts:
            db.execute(idx)

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

        # 4. Apply 005 upgrades (provider_rate_limit_state, provider_rate_limit_leases)
        cls._apply_005_upgrades(db, is_pg)

        # 5. Apply 006 upgrades (scheduler_dispatch_state, scheduler_runs)
        cls._apply_006_upgrades(db, is_pg)

        # 6. Apply 007 upgrades (bop_organization_id, outbox, inbox)
        cls._apply_007_upgrades(db, is_pg)

        # 7. Apply 008 upgrades (destinations, subscriptions, deliveries, delivery attempts)
        cls._apply_008_upgrades(db, is_pg)

        # 8. Apply 009 upgrades (auth fields, auth sessions, login attempts)
        cls._apply_009_upgrades(db, is_pg)

        # 9. Ensure version table and insert expected version idempotently
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
