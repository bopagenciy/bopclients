"""Centralized RuntimeSettings for BopClients production environment configuration and secret masking."""

import os
import re
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


class AppEnvironment(str, Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"

    @classmethod
    def parse(cls, val: str) -> "AppEnvironment":
        val_lower = (val or "").strip().lower()
        for env in cls:
            if env.value == val_lower:
                return env
        return cls.DEVELOPMENT


@dataclass
class RuntimeSettings:
    """Centralized runtime settings parsed from environment variables."""

    environment: AppEnvironment = AppEnvironment.DEVELOPMENT
    database_url: str = ":memory:"
    log_level: str = "INFO"

    # Provider feature flags & secrets
    enabled_providers: List[str] = field(default_factory=lambda: ["official_website"])
    sam_gov_api_key: str = ""
    gemini_api_key: str = ""

    # Worker configuration
    worker_batch_size: int = 25
    worker_max_items: int = 100
    worker_max_seconds: int = 600
    lease_duration_seconds: int = 300
    lease_renew_before_seconds: int = 90

    @classmethod
    def from_env(cls) -> "RuntimeSettings":
        """Factory instantiating RuntimeSettings from environment variables."""
        env = AppEnvironment.parse(os.environ.get("BOPCLIENTS_ENV", os.environ.get("APP_ENV", "development")))
        db_url = os.environ.get("DATABASE_URL", ":memory:").strip()
        log_lvl = os.environ.get("LOG_LEVEL", "INFO").strip().upper()

        providers_raw = os.environ.get("ENABLED_PUBLIC_SIGNAL_PROVIDERS", "official_website")
        enabled = [p.strip().lower() for p in providers_raw.split(",") if p.strip()]

        sam_key = os.environ.get("SAM_GOV_API_KEY", "").strip()
        gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()

        batch_sz = int(os.environ.get("MONITORING_WORKER_BATCH_SIZE", "25"))
        max_it = int(os.environ.get("MONITORING_WORKER_MAX_ITEMS", "100"))
        max_sec = int(os.environ.get("MONITORING_WORKER_MAX_SECONDS", "600"))
        lease_dur = int(os.environ.get("MONITORING_LEASE_DURATION_SECONDS", "300"))
        renew_bef = int(os.environ.get("MONITORING_LEASE_RENEW_BEFORE_SECONDS", "90"))

        return cls(
            environment=env,
            database_url=db_url,
            log_level=log_lvl,
            enabled_providers=enabled,
            sam_gov_api_key=sam_key,
            gemini_api_key=gemini_key,
            worker_batch_size=batch_sz,
            worker_max_items=max_it,
            worker_max_seconds=max_sec,
            lease_duration_seconds=lease_dur,
            lease_renew_before_seconds=renew_bef,
        )

    def validate(self):
        """Validate runtime settings bounds, database URI support, and provider requirements."""
        if self.worker_batch_size <= 0 or self.worker_max_items <= 0 or self.worker_max_seconds <= 0:
            raise ValueError("Worker batch size, max items, and max seconds must be > 0.")
        if self.lease_duration_seconds <= 0 or self.lease_renew_before_seconds <= 0:
            raise ValueError("Lease duration and renew before seconds must be > 0.")
        if self.lease_renew_before_seconds >= self.lease_duration_seconds:
            raise ValueError("lease_renew_before_seconds must be strictly less than lease_duration_seconds.")

        # Database scheme validation
        db_lower = (self.database_url or "").strip().lower()
        if db_lower.startswith(("postgresql://", "postgres://")):
            try:
                import psycopg
            except ImportError:
                raise ValueError("PostgreSQL driver 'psycopg' is not installed.")
        if self.environment == AppEnvironment.PRODUCTION and db_lower in (":memory:", "sqlite:///:memory:"):
            raise ValueError("In-memory SQLite database is not persistent and cannot be used in production environment.")

    def mask_database_url(self) -> str:
        """Return safe database URL with credentials masked."""
        if not self.database_url or self.database_url == ":memory:":
            return ":memory:"
        # Mask password in URL pattern scheme://user:password@host/db
        masked = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", self.database_url)
        return masked

    def safe_summary(self) -> Dict[str, Any]:
        """Return safe dictionary summary without revealing secrets or raw tokens."""
        return {
            "environment": self.environment.value,
            "database_url": self.mask_database_url(),
            "log_level": self.log_level,
            "enabled_providers": self.enabled_providers,
            "sam_gov_configured": bool(self.sam_gov_api_key),
            "gemini_configured": bool(self.gemini_api_key),
            "worker_batch_size": self.worker_batch_size,
            "worker_max_items": self.worker_max_items,
            "worker_max_seconds": self.worker_max_seconds,
            "lease_duration_seconds": self.lease_duration_seconds,
            "lease_renew_before_seconds": self.lease_renew_before_seconds,
        }
