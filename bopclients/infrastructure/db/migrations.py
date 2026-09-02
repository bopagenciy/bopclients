"""Database migration runner for BopClients P1 foundation."""

import logging
from typing import Any
from bopclients.infrastructure.db.schema import BOPCLIENTS_DDL_TABLES, BOPCLIENTS_DDL_INDEXES

logger = logging.getLogger("bopclients.db.migrations")


def run_p1_migrations(db: Any) -> None:
    """Execute P1 schema migration DDL statements.

    Works with both ForgeDB / SQLite connections and PostgreSQL pools.
    """
    logger.info("Executing BopClients P1 Foundation DB migrations...")
    # 1. Create tables
    for ddl in BOPCLIENTS_DDL_TABLES:
        db.execute(ddl)

    # 2. Create indexes
    for ddl in BOPCLIENTS_DDL_INDEXES:
        db.execute(ddl)

    db.commit()
    logger.info("BopClients P1 Foundation DB migrations completed successfully.")
