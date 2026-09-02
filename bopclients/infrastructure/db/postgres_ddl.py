"""PostgreSQL DDL schema execution for BopClients P12 using authoritative domain schema."""

import logging
from bopclients.infrastructure.db.schema import BOPCLIENTS_DDL_TABLES, BOPCLIENTS_DDL_INDEXES

logger = logging.getLogger("bopclients.db.postgres_ddl")


def run_postgres_migrations(conn) -> None:
    """Execute PostgreSQL DDL migrations idempotently using canonical schema definitions."""
    logger.info("Executing PostgreSQL DDL migrations for BopClients...")

    for stmt in BOPCLIENTS_DDL_TABLES:
        conn.execute(stmt)

    for stmt in BOPCLIENTS_DDL_INDEXES:
        conn.execute(stmt)

    conn.commit()
    logger.info("PostgreSQL DDL migrations completed successfully.")
