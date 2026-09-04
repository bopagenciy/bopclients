"""Domain models and policies for distributed provider rate limiting and concurrency management."""

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class ProviderAcquireStatus(str, Enum):
    """Structured result status for provider slot acquisition attempts."""

    ACQUIRED = "ACQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    TENANT_CAPACITY_LIMITED = "TENANT_CAPACITY_LIMITED"
    CONCURRENCY_LIMITED = "CONCURRENCY_LIMITED"
    COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"
    PROVIDER_DISABLED = "PROVIDER_DISABLED"
    PROVIDER_BUDGET_EXHAUSTED = "PROVIDER_BUDGET_EXHAUSTED"


# Canonical provider keys across BopClients runtime
CANONICAL_OFFICIAL_WEBSITE = "official_website"
CANONICAL_GOVERNMENT_PROCUREMENT = "government_procurement"
CANONICAL_PUBLIC_NEWS = "public_news"
CANONICAL_GEMINI = "gemini"


class ProviderCallBudget:
    """Run-level provider call budget tracked across items within a single worker run."""

    def __init__(self, max_calls: Optional[int] = None):
        self.max_calls = max_calls
        self.calls_executed = 0

    @property
    def is_exhausted(self) -> bool:
        if self.max_calls is None:
            return False
        return self.calls_executed >= self.max_calls

    def can_execute(self) -> bool:
        return not self.is_exhausted

    def record_call(self) -> None:
        self.calls_executed += 1


@dataclass
class ProviderRateLimitPolicy:
    """Rate limiting and concurrency guard policy for a specific provider key.
    
    Attributes:
        max_executions: Maximum provider executions per fixed window and scope.
        per_organization_max_executions: Optional max executions allocated per organization within window.
    """

    provider_key: str
    max_executions: int = 60
    window_seconds: int = 60
    max_concurrent: int = 2
    per_organization_max_executions: Optional[int] = None
    cooldown_on_429_seconds: int = 60
    cooldown_on_503_seconds: int = 30
    honor_retry_after: bool = True
    max_retry_after_seconds: int = 3600
    request_lease_duration_seconds: int = 30
    enabled: bool = True

    def validate(self) -> None:
        """Validate policy bounds fail-closed."""
        if not self.provider_key or not self.provider_key.strip():
            raise ValueError("provider_key cannot be empty.")
        if self.enabled:
            if self.max_executions <= 0:
                raise ValueError(f"max_executions must be > 0 (got {self.max_executions}).")
            if self.window_seconds <= 0:
                raise ValueError(f"window_seconds must be > 0 (got {self.window_seconds}).")
            if self.max_concurrent <= 0:
                raise ValueError(f"max_concurrent must be > 0 (got {self.max_concurrent}).")
            if self.per_organization_max_executions is not None:
                if self.per_organization_max_executions <= 0:
                    raise ValueError(f"per_organization_max_executions must be > 0 (got {self.per_organization_max_executions}).")
                if self.per_organization_max_executions > self.max_executions:
                    raise ValueError(
                        f"per_organization_max_executions ({self.per_organization_max_executions}) cannot exceed max_executions ({self.max_executions})."
                    )
            if self.cooldown_on_429_seconds < 0:
                raise ValueError("cooldown_on_429_seconds cannot be negative.")
            if self.cooldown_on_503_seconds < 0:
                raise ValueError("cooldown_on_503_seconds cannot be negative.")
            if self.max_retry_after_seconds <= 0:
                raise ValueError("max_retry_after_seconds must be > 0.")
            if self.request_lease_duration_seconds <= 0:
                raise ValueError("request_lease_duration_seconds must be > 0.")


@dataclass
class ProviderAcquireResult:
    """Structured outcome of trying to acquire a provider rate limit & concurrency slot."""

    status: ProviderAcquireStatus
    acquired: bool
    provider_key: str
    scope_key: str
    permit_id: str
    lease_token: Optional[str] = None
    retry_not_before: Optional[str] = None
    retry_after_seconds: Optional[int] = None
    reason: Optional[str] = None


@dataclass
class ProviderExecutionPermit:
    """Execution permit held while invoking an external provider call."""

    permit_id: str
    provider_key: str
    scope_key: str
    acquired: bool
    status: ProviderAcquireStatus
    lease_token: Optional[str] = None
    retry_not_before: Optional[str] = None
    retry_after_seconds: Optional[int] = None
    reason: Optional[str] = None
