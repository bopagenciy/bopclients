"""Database Abstraction Layer providing unified SQLite and PostgreSQL connection adapters."""

import re
import os
import logging
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import List, Dict, Any, Optional, Tuple
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend

logger = logging.getLogger("bopclients.db.connection")

try:
    import psycopg
    from psycopg.rows import dict_row
    HAS_PSYCOPG = True
except ImportError:
    psycopg = None
    dict_row = None
    HAS_PSYCOPG = False


class BopDBConnection(ABC):
    """Abstract interface defining database execution and transaction contract."""

    @property
    @abstractmethod
    def in_transaction(self) -> bool:
        """Whether a caller-managed transaction block is currently active."""
        pass

    @abstractmethod
    def begin(self) -> None:
        """Begin an explicit database transaction."""
        pass

    @abstractmethod
    def execute(self, sql: str, params: Optional[Tuple[Any, ...]] = None) -> Any:
        pass

    @abstractmethod
    def execute_rowcount(self, sql: str, params: Optional[Tuple[Any, ...]] = None) -> int:
        pass

    @abstractmethod
    def executemany(self, sql: str, params_list: List[Tuple[Any, ...]]) -> Any:
        pass

    @abstractmethod
    def fetch_dicts(self, sql: str, params: Optional[Tuple[Any, ...]] = None) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def commit(self) -> None:
        pass

    @abstractmethod
    def rollback(self) -> None:
        pass

    @abstractmethod
    def close(self) -> None:
        pass

    @property
    @abstractmethod
    def placeholder(self) -> str:
        pass

    @property
    @abstractmethod
    def backend_name(self) -> str:
        pass

    _tx_depth: int = 0

    @contextmanager
    def transaction(self):
        """Context manager providing an atomic database transaction boundary with depth tracking.

        Reuses outer transaction on nested invocations to prevent premature commits.
        """
        is_outermost = (getattr(self, "_tx_depth", 0) == 0)
        self._tx_depth = getattr(self, "_tx_depth", 0) + 1
        if is_outermost:
            self.begin()
        try:
            yield self
            if is_outermost:
                self.commit()
        except Exception:
            if is_outermost:
                self.rollback()
            raise
        finally:
            self._tx_depth = getattr(self, "_tx_depth", 1) - 1
            if self._tx_depth < 0:
                self._tx_depth = 0


class SQLiteConnectionAdapter(BopDBConnection):
    """Adapter wrapping ForgeDB for SQLite database backend."""

    def __init__(self, db_path: str = ":memory:"):
        # Strip scheme if present
        path = db_path
        if path.startswith("sqlite:///"):
            path = path[10:]
        elif path.startswith("sqlite://"):
            path = path[9:]
        self._db_path = path
        self._db = ForgeDB(_SQLiteBackend(db_path=path))
        self._manual_in_tx = False

    @property
    def forge_db(self) -> ForgeDB:
        return self._db

    @property
    def placeholder(self) -> str:
        return "?"

    @property
    def backend_name(self) -> str:
        return "sqlite"

    @property
    def in_transaction(self) -> bool:
        return self._manual_in_tx or getattr(self._db._in_transaction, "active", False)

    def begin(self) -> None:
        self._manual_in_tx = True
        self._db._in_transaction.active = True

    def execute(self, sql: str, params: Optional[Tuple[Any, ...]] = None) -> Any:
        p = params or ()
        return self._db.execute(sql, p)

    def execute_rowcount(self, sql: str, params: Optional[Tuple[Any, ...]] = None) -> int:
        p = params or ()
        if hasattr(self._db, "_backend") and hasattr(self._db._backend, "_conn"):
            conn = self._db._backend._conn
            cur = conn.cursor()
            cur.execute(sql, p)
            rc = cur.rowcount
            cur.close()
            if not self.in_transaction:
                conn.commit()
            return rc
        res = self._db.execute(sql, p)
        if hasattr(res, "rowcount"):
            return res.rowcount
        return 1

    def executemany(self, sql: str, params_list: List[Tuple[Any, ...]]) -> Any:
        for p in params_list:
            self._db.execute(sql, p)

    def fetch_dicts(self, sql: str, params: Optional[Tuple[Any, ...]] = None) -> List[Dict[str, Any]]:
        p = params or ()
        return self._db.fetch_dicts(sql, p)

    def commit(self) -> None:
        try:
            if hasattr(self._db, "_backend") and hasattr(self._db._backend, "_conn"):
                self._db._backend._conn.commit()
            else:
                self._db.commit()
        finally:
            self._manual_in_tx = False
            self._db._in_transaction.active = False

    def rollback(self) -> None:
        try:
            if hasattr(self._db, "_backend") and hasattr(self._db._backend, "_conn"):
                self._db._backend._conn.rollback()
        finally:
            self._manual_in_tx = False
            self._db._in_transaction.active = False

    def close(self) -> None:
        if hasattr(self._db, "_backend") and hasattr(self._db._backend, "close"):
            self._db._backend.close()


class PostgresConnectionAdapter(BopDBConnection):
    """Adapter wrapping psycopg v3 for PostgreSQL database backend."""

    def __init__(self, connection_url: str):
        if not HAS_PSYCOPG:
            raise ImportError("psycopg library is required for PostgreSQL support. Install 'psycopg[binary]'.")

        # Convert postgres:// to postgresql:// if needed
        url = connection_url
        if url.startswith("postgres://"):
            url = "postgresql://" + url[11:]

        logger.info("Opening PostgreSQL database connection via psycopg...")
        self._conn = psycopg.connect(url, row_factory=dict_row, autocommit=False)
        self._manual_in_tx = False

    @property
    def raw_connection(self):
        return self._conn

    @property
    def placeholder(self) -> str:
        return "%s"

    @property
    def backend_name(self) -> str:
        return "postgresql"

    @property
    def in_transaction(self) -> bool:
        return self._manual_in_tx

    def begin(self) -> None:
        self._manual_in_tx = True

    def _convert_sql(self, sql: str) -> str:
        """Convert SQLite parameter placeholders (?) to PostgreSQL placeholders (%s)."""
        return sql.replace("?", "%s")

    def execute(self, sql: str, params: Optional[Tuple[Any, ...]] = None) -> Any:
        pg_sql = self._convert_sql(sql)
        p = params or ()
        with self._conn.cursor() as cur:
            cur.execute(pg_sql, p)
            return cur

    def execute_rowcount(self, sql: str, params: Optional[Tuple[Any, ...]] = None) -> int:
        pg_sql = self._convert_sql(sql)
        p = params or ()
        with self._conn.cursor() as cur:
            cur.execute(pg_sql, p)
            return cur.rowcount

    def executemany(self, sql: str, params_list: List[Tuple[Any, ...]]) -> Any:
        pg_sql = self._convert_sql(sql)
        with self._conn.cursor() as cur:
            cur.executemany(pg_sql, params_list)
            return cur

    def fetch_dicts(self, sql: str, params: Optional[Tuple[Any, ...]] = None) -> List[Dict[str, Any]]:
        pg_sql = self._convert_sql(sql)
        p = params or ()
        with self._conn.cursor() as cur:
            cur.execute(pg_sql, p)
            if cur.description is not None:
                rows = cur.fetchall()
                return [dict(r) for r in rows]
            return []

    def commit(self) -> None:
        try:
            self._conn.commit()
        finally:
            self._manual_in_tx = False

    def rollback(self) -> None:
        try:
            self._conn.rollback()
        finally:
            self._manual_in_tx = False

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


def create_database_connection(database_url: str) -> BopDBConnection:
    """Factory creating appropriate database adapter from database_url string."""
    url = (database_url or "").strip()
    url_lower = url.lower()

    if url_lower.startswith(("postgresql://", "postgres://")):
        return PostgresConnectionAdapter(url)
    elif url_lower.startswith("sqlite://") or url_lower == ":memory:" or not url or url.endswith((".db", ".sqlite")):
        return SQLiteConnectionAdapter(url)
    else:
        raise ValueError(f"Unsupported database URL scheme: '{database_url}'")
