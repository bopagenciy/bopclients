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


def sanitize_error_message(err: Any, max_length: int = 500) -> Optional[str]:
    """Sanitize error messages ensuring passwords, DSNs, auth headers, API keys, and tokens are masked."""
    if err is None:
        return None
    text = str(err)
    # Mask passwords in connection URIs (e.g. postgresql://user:password@host/db)
    text = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", text)
    # Mask authorization headers / bearer tokens
    text = re.sub(r"(?i)(bearer\s+)[a-zA-Z0-9_\-\.]+", r"\1***", text)
    # Mask explicit api keys, secrets, tokens, and passwords
    text = re.sub(r"(?i)(api[_-]?key|token|secret|password|passwd|pwd)\s*([:=])\s*['\"]?[^\s,'\"]+['\"]?", r"\1\2***", text)
    # Strip traceback preamble if present
    if "Traceback (most recent call last)" in text:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = lines[-1] if lines else "Unhandled Exception"
    if len(text) > max_length:
        text = text[: max_length - 3] + "..."
    return text


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

    # Operational Recovery configuration
    research_run_recovery_enabled: bool = True
    research_run_stale_after_seconds: int = 900
    research_run_recovery_limit: int = 100

    # Production Scheduler configuration
    production_scheduler_enabled: bool = False
    scheduler_key: str = "monitoring_worker"
    scheduler_lease_seconds: int = 300
    scheduler_renew_before_seconds: int = 90
    scheduler_recovery_stale_after_seconds: int = 900
    scheduler_recovery_limit: int = 100

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

        rec_enabled = os.environ.get("RESEARCH_RUN_RECOVERY_ENABLED", "true").strip().lower() in ("true", "1", "yes")
        stale_sec = int(os.environ.get("RESEARCH_RUN_STALE_AFTER_SECONDS", "900"))
        rec_lim = int(os.environ.get("RESEARCH_RUN_RECOVERY_LIMIT", "100"))

        sched_enabled = os.environ.get("PRODUCTION_SCHEDULER_ENABLED", "false").strip().lower() in ("true", "1", "yes")
        sched_key = os.environ.get("PRODUCTION_SCHEDULER_KEY", "monitoring_worker").strip() or "monitoring_worker"
        sched_lease = int(os.environ.get("SCHEDULER_LEASE_SECONDS", "300"))
        sched_renew = int(os.environ.get("SCHEDULER_RENEW_BEFORE_SECONDS", "90"))
        sched_stale = int(os.environ.get("SCHEDULER_RECOVERY_STALE_AFTER_SECONDS", "900"))
        sched_rec_lim = int(os.environ.get("SCHEDULER_RECOVERY_LIMIT", "100"))

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
            research_run_recovery_enabled=rec_enabled,
            research_run_stale_after_seconds=stale_sec,
            research_run_recovery_limit=rec_lim,
            production_scheduler_enabled=sched_enabled,
            scheduler_key=sched_key,
            scheduler_lease_seconds=sched_lease,
            scheduler_renew_before_seconds=sched_renew,
            scheduler_recovery_stale_after_seconds=sched_stale,
            scheduler_recovery_limit=sched_rec_lim,
        )

    def validate(self):
        """Validate runtime settings bounds, database URI support, and provider requirements."""
        if self.worker_batch_size <= 0 or self.worker_max_items <= 0 or self.worker_max_seconds <= 0:
            raise ValueError("Worker batch size, max items, and max seconds must be > 0.")
        if self.lease_duration_seconds <= 0 or self.lease_renew_before_seconds <= 0:
            raise ValueError("Lease duration and renew before seconds must be > 0.")
        if self.lease_renew_before_seconds >= self.lease_duration_seconds:
            raise ValueError("lease_renew_before_seconds must be strictly less than lease_duration_seconds.")
        if self.research_run_stale_after_seconds <= self.lease_duration_seconds:
            raise ValueError("research_run_stale_after_seconds must be strictly greater than lease_duration_seconds.")
        if self.scheduler_lease_seconds <= 0 or self.scheduler_renew_before_seconds <= 0:
            raise ValueError("Scheduler lease seconds and renew before seconds must be > 0.")
        if self.scheduler_renew_before_seconds >= self.scheduler_lease_seconds:
            raise ValueError("scheduler_renew_before_seconds must be strictly less than scheduler_lease_seconds.")
        if self.scheduler_recovery_stale_after_seconds <= self.scheduler_lease_seconds:
            raise ValueError("scheduler_recovery_stale_after_seconds must be strictly greater than scheduler_lease_seconds.")
        if self.scheduler_recovery_limit <= 0:
            raise ValueError("scheduler_recovery_limit must be > 0.")

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
            "production_scheduler_enabled": self.production_scheduler_enabled,
            "scheduler_key": self.scheduler_key,
            "scheduler_lease_seconds": self.scheduler_lease_seconds,
            "scheduler_renew_before_seconds": self.scheduler_renew_before_seconds,
            "scheduler_recovery_stale_after_seconds": self.scheduler_recovery_stale_after_seconds,
            "scheduler_recovery_limit": self.scheduler_recovery_limit,
        }
