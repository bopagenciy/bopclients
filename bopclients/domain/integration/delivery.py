"""Delivery lifecycle and attempt domain models."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class DeliveryStatus(str, Enum):
    """Lifecycle status of a destination-specific delivery record."""

    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    DELIVERED = "DELIVERED"
    RETRY_PENDING = "RETRY_PENDING"
    DEAD_LETTER = "DEAD_LETTER"


class TransportResultStatus(str, Enum):
    """Status outcome of a transport delivery attempt."""

    SUCCESS = "SUCCESS"
    TRANSIENT_FAILURE = "TRANSIENT_FAILURE"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"


@dataclass
class TransportPublishResult:
    """Outcome returned by an IntegrationTransport execution."""

    status: TransportResultStatus
    status_code: Optional[int] = None
    response_body_sample: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retry_after_seconds: Optional[int] = None


@dataclass
class DeliveryRecord:
    """Outbound delivery tracking row for a specific event and destination."""

    id: str
    event_id: str
    destination_id: str
    bop_organization_id: str
    status: str
    attempt_count: int
    max_attempts: int
    next_attempt_at: str
    claim_token: Optional[str] = None
    claim_expires_at: Optional[str] = None
    delivered_at: Optional[str] = None
    last_error_code: Optional[str] = None
    last_error_message: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class DeliveryAttemptRecord:
    """Historical record of an individual outbound transport delivery attempt."""

    id: str
    delivery_id: str
    attempt_number: int
    started_at: str
    finished_at: str
    status: str  # SUCCESS, TRANSIENT_FAILURE, PERMANENT_FAILURE
    status_code: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    response_body_sample: Optional[str] = None


class IntegrationSecretResolver:
    """Abstract interface for resolving credential references to raw secrets at runtime."""

    def resolve(self, reference: str) -> str:
        """Resolve credential reference to secret string.

        Raises ValueError if reference is unknown, empty, or cannot be resolved.
        Must NEVER log secret values.
        """
        raise NotImplementedError

    def get_secret(self, reference: Optional[str]) -> Optional[str]:
        """Convenience method returning resolved secret or None if reference is empty."""
        if not reference or not reference.strip():
            return None
        return self.resolve(reference.strip())


class EnvIntegrationSecretResolver(IntegrationSecretResolver):
    """Resolves secret references directly from environment variables.

    Guarantees:
    - Defense-in-depth: independently validates reference against strict '^BOP_INTEGRATION_SECRET_[A-Z0-9_]{1,80}$'.
    - Arbitrary environment variables (e.g. DATABASE_URL, OPENAI_API_KEY) are strictly rejected.
    - Missing or empty environment values raise structured ValueError.
    - Never logs or exposes raw secrets.
    """

    def __init__(self, prefix: str = ""):
        self.prefix = prefix

    def resolve(self, reference: str) -> str:
        import os
        from bopclients.domain.integration.destination import validate_secret_reference

        # Validate reference namespace syntax independently
        clean_ref = validate_secret_reference(reference)
        key = self.prefix + clean_ref

        # Check environment variable
        if key not in os.environ:
            raise ValueError(f"Integration credential reference '{clean_ref}' not configured in environment")

        val = os.environ[key]
        if not val or not val.strip():
            raise ValueError(f"Integration credential reference '{clean_ref}' is empty in environment")
        return val.strip()

    def __repr__(self) -> str:
        return f"<EnvIntegrationSecretResolver(prefix='{self.prefix}')>"


class FakeIntegrationSecretResolver(IntegrationSecretResolver):
    """In-memory secret resolver for testing and local fixture support."""

    def __init__(self, secrets: Optional[dict] = None):
        self._secrets: dict = dict(secrets or {})

    def set_secret(self, reference: str, value: str) -> None:
        self._secrets[reference.strip()] = value

    def resolve(self, reference: str) -> str:
        from bopclients.domain.integration.destination import validate_secret_reference

        clean_ref = validate_secret_reference(reference)
        if clean_ref not in self._secrets:
            raise ValueError(f"Integration credential reference '{clean_ref}' not found in secret store")
        val = self._secrets[clean_ref]
        if not val or not val.strip():
            raise ValueError(f"Integration credential reference '{clean_ref}' is empty in secret store")
        return val.strip()

    def __repr__(self) -> str:
        return f"<FakeIntegrationSecretResolver(keys={list(self._secrets.keys())})>"
