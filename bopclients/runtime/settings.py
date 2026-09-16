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
    # Mask passwords in connection URIs (e.g. postgresql://user:password@host/db or http://user:pass@host)
    text = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", text)
    # Mask authorization headers / bearer tokens
    text = re.sub(r"(?i)(authorization|proxy-authorization)\s*[:=]\s*['\"]?[^\s,'\"]+['\"]?", r"\1: ***", text)
    text = re.sub(r"(?i)(bearer\s+)[a-zA-Z0-9_\-\.]+", r"\1***", text)
    # Mask cookies / session tokens
    text = re.sub(r"(?i)(cookie|set-cookie)\s*[:=]\s*['\"]?[^\r\n]+['\"]?", r"\1: ***", text)
    # Mask query parameters in URLs (e.g. ?api_key=secret, &token=secret, ?password=secret)
    text = re.sub(r"([?&](?:api[_-]?key|token|access_token|refresh_token|secret|password|passwd|pwd|auth|key)=)([^&#\s]+)", r"\1***", text, flags=re.IGNORECASE)
    # Mask explicit api keys, secrets, tokens, and passwords
    text = re.sub(r"(?i)(api[_-]?key|token|secret|password|passwd|pwd)\s*([:=])\s*['\"]?[^\s,'\"&#]+['\"]?", r"\1\2***", text)
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

    # Integration Outbox Publisher configuration (P18)
    integration_publisher_enabled: bool = False
    integration_batch_size: int = 25
    integration_claim_lease_seconds: int = 60
    integration_max_runtime_seconds: int = 300
    integration_http_connect_timeout: float = 5.0
    integration_http_read_timeout: float = 10.0
    integration_max_attempts: int = 5
    integration_allow_insecure_http: bool = False

    # Product API & Auth configuration (P19)
    auth_signing_key: str = "bop_default_dev_secret_key_change_in_production_32bytes"
    auth_token_expire_seconds: int = 3600
    auth_session_expire_days: int = 30
    cors_allowed_origins: List[str] = field(default_factory=lambda: ["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000"])
    api_port: int = 8100
    api_host: str = "127.0.0.1"

    # Team Invitations configuration (P24.1)
    invitation_dev_token_exposure: bool = False

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

        pub_enabled = os.environ.get("INTEGRATION_PUBLISHER_ENABLED", "false").strip().lower() in ("true", "1", "yes")
        pub_batch = int(os.environ.get("INTEGRATION_BATCH_SIZE", "25"))
        pub_claim_lease = int(os.environ.get("INTEGRATION_CLAIM_LEASE_SECONDS", "60"))
        pub_max_runtime = int(os.environ.get("INTEGRATION_MAX_RUNTIME_SECONDS", "300"))
        pub_conn_timeout = float(os.environ.get("INTEGRATION_HTTP_CONNECT_TIMEOUT", "5.0"))
        pub_read_timeout = float(os.environ.get("INTEGRATION_HTTP_READ_TIMEOUT", "10.0"))
        pub_max_attempts = int(os.environ.get("INTEGRATION_MAX_ATTEMPTS", "5"))
        pub_allow_insecure = os.environ.get("INTEGRATION_ALLOW_INSECURE_HTTP", "false").strip().lower() in ("true", "1", "yes")

        # In production, insecure http is strictly disallowed
        if env == AppEnvironment.PRODUCTION:
            pub_allow_insecure = False

        auth_key = os.environ.get("BOP_AUTH_SIGNING_KEY", "bop_default_dev_secret_key_change_in_production_32bytes").strip()
        auth_expire_sec = int(os.environ.get("BOP_AUTH_TOKEN_EXPIRE_SECONDS", "3600"))
        session_expire_days = int(os.environ.get("BOP_AUTH_SESSION_EXPIRE_DAYS", "30"))
        cors_raw = os.environ.get("BOP_CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000")
        cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()]
        api_p = int(os.environ.get("BOP_API_PORT", "8100"))
        api_h = os.environ.get("BOP_API_HOST", "127.0.0.1").strip()

        inv_dev_exposure = os.environ.get("BOP_INVITATION_DEV_TOKEN_EXPOSURE", "false").strip().lower() in ("true", "1", "yes")
        if env == AppEnvironment.PRODUCTION:
            inv_dev_exposure = False

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
            integration_publisher_enabled=pub_enabled,
            integration_batch_size=pub_batch,
            integration_claim_lease_seconds=pub_claim_lease,
            integration_max_runtime_seconds=pub_max_runtime,
            integration_http_connect_timeout=pub_conn_timeout,
            integration_http_read_timeout=pub_read_timeout,
            integration_max_attempts=pub_max_attempts,
            integration_allow_insecure_http=pub_allow_insecure,
            auth_signing_key=auth_key,
            auth_token_expire_seconds=auth_expire_sec,
            auth_session_expire_days=session_expire_days,
            cors_allowed_origins=cors_origins,
            api_port=api_p,
            api_host=api_h,
            invitation_dev_token_exposure=inv_dev_exposure,
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

        # Integration Publisher bounds (P18)
        if self.integration_batch_size <= 0:
            raise ValueError("integration_batch_size must be > 0.")
        if self.integration_claim_lease_seconds <= 0:
            raise ValueError("integration_claim_lease_seconds must be > 0.")
        if self.integration_max_runtime_seconds <= 0:
            raise ValueError("integration_max_runtime_seconds must be > 0.")
        if self.integration_http_connect_timeout <= 0 or self.integration_http_read_timeout <= 0:
            raise ValueError("HTTP connect and read timeouts must be > 0.")
        if self.integration_max_attempts <= 0:
            raise ValueError("integration_max_attempts must be > 0.")

        # Auth bounds (P19)
        if self.auth_token_expire_seconds <= 0:
            raise ValueError("auth_token_expire_seconds must be > 0.")
        if self.auth_session_expire_days <= 0:
            raise ValueError("auth_session_expire_days must be > 0.")
        if not self.auth_signing_key or len(self.auth_signing_key.strip()) < 32:
            raise ValueError("auth_signing_key must be at least 32 characters for security.")

        # Database scheme validation
        db_lower = (self.database_url or "").strip().lower()
        if self.environment == AppEnvironment.PRODUCTION and db_lower == ":memory:":
            raise ValueError("In-memory SQLite database is not persistent and cannot be used in production.")

        if db_lower.startswith(("postgresql://", "postgres://")):
            pass
        elif db_lower == ":memory:" or db_lower.endswith(".db") or db_lower.startswith("sqlite:"):
            pass
        else:
            raise ValueError(f"Unsupported database scheme: '{self.database_url}'")

    def mask_database_url(self) -> str:
        """Return database URI with user credentials safely redacted."""
        if not self.database_url:
            return ""
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
            "integration_publisher_enabled": self.integration_publisher_enabled,
            "integration_batch_size": self.integration_batch_size,
            "integration_claim_lease_seconds": self.integration_claim_lease_seconds,
            "integration_max_runtime_seconds": self.integration_max_runtime_seconds,
            "integration_max_attempts": self.integration_max_attempts,
            "integration_allow_insecure_http": self.integration_allow_insecure_http,
            "auth_configured": bool(self.auth_signing_key),
            "auth_token_expire_seconds": self.auth_token_expire_seconds,
            "auth_session_expire_days": self.auth_session_expire_days,
            "cors_allowed_origins": self.cors_allowed_origins,
            "api_port": self.api_port,
            "api_host": self.api_host,
            "invitation_dev_token_exposure": self.invitation_dev_token_exposure,
        }
