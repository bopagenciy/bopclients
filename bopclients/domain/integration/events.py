"""Canonical versioned integration event envelope for the Bop Platform."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import re
import uuid
from typing import Dict, Any, Optional

from bopclients.domain.integration.app_id import validate_application_id
from bopclients.domain.integration.entity_ref import BopEntityRef
from bopclients.domain.integration.exceptions import (
    InvalidIntegrationEvent,
    CrossTenantIntegrationEvent,
)

# Dotted event_type pattern (e.g. prospect.discovered, buying_intent.detected)
_EVENT_TYPE_PATTERN = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")

# Prohibited sensitive keys in integration envelopes:
# Targets exact credential and secret names while allowing non-secret metadata
# such as token_count, secretary_name, authentication_method, author_name.
_PROHIBITED_SECRET_PATTERNS = re.compile(
    r"(^|_)api_?key($|_)|(^|_)password($|_)|(^|_)secret($|_)|(^|_)private_?key($|_)|"
    r"(^|_)credentials?($|_)|(^|_)(access|refresh|auth|bearer|session|oauth|jwt|api)_token($|_)|"
    r"^token$|^secret$|^password$|^bearer$|^auth_header$",
    re.IGNORECASE,
)


def validate_strict_uuid_v4(value: Any, field_name: str, allow_none: bool = False) -> Optional[str]:
    """Validate that value is a strict, valid UUID v4 without rewriting version or input bits."""
    if value is None:
        if allow_none:
            return None
        raise InvalidIntegrationEvent(f"{field_name} cannot be None")
    if not isinstance(value, str) or not value.strip():
        raise InvalidIntegrationEvent(f"{field_name} must be a non-empty string UUID")
    raw = value.strip()
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError):
        raise InvalidIntegrationEvent(f"{field_name} '{value}' is not a valid UUID")
    if parsed.version != 4:
        raise InvalidIntegrationEvent(f"{field_name} '{value}' must be UUID version 4 (got version {parsed.version})")
    return str(parsed)


def _scan_for_secrets(obj: Any, path: str = "") -> None:
    """Recursively inspect dictionaries/lists to reject prohibited sensitive security fields.

    Security note: Does not log or reveal secret values upon rejection.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                continue
            field_path = f"{path}.{k}" if path else k
            if _PROHIBITED_SECRET_PATTERNS.search(k):
                raise InvalidIntegrationEvent(
                    f"Integration event contains forbidden security sensitive key '{field_path}'"
                )
            _scan_for_secrets(v, field_path)
    elif isinstance(obj, (list, tuple)):
        for i, item in enumerate(obj):
            _scan_for_secrets(item, f"{path}[{i}]")


@dataclass(frozen=True)
class BopIntegrationEvent:
    """Versioned canonical integration event envelope shared across Bop applications."""

    event_id: str
    event_type: str
    event_version: int
    occurred_at: str
    producer_app: str
    bop_organization_id: str
    subject: BopEntityRef
    correlation_id: str
    causation_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.validate()

    @property
    def source_app(self) -> str:
        """Compatibility alias for producer_app."""
        return self.producer_app

    @property
    def entity_ref(self) -> BopEntityRef:
        """Compatibility alias for subject."""
        return self.subject

    def validate(self) -> None:
        """Enforce strict envelope invariants, tenant integrity, and serialization safety."""
        # 1. Validate event_id (canonical strict UUID v4)
        norm_event_id = validate_strict_uuid_v4(self.event_id, "event_id")
        object.__setattr__(self, "event_id", norm_event_id)

        # 2. Validate event_type (dotted lowercase string)
        if not isinstance(self.event_type, str) or not self.event_type.strip():
            raise InvalidIntegrationEvent("event_type must be a non-empty string")
        norm_type = self.event_type.strip().lower()
        if not _EVENT_TYPE_PATTERN.match(norm_type):
            raise InvalidIntegrationEvent(
                f"Invalid event_type '{self.event_type}'. Must be dotted lowercase string (e.g. 'prospect.discovered')"
            )
        object.__setattr__(self, "event_type", norm_type)

        # 3. Validate event_version (strictly positive integer)
        if not isinstance(self.event_version, int) or self.event_version <= 0:
            raise InvalidIntegrationEvent(f"event_version must be a positive integer, got {self.event_version}")

        # 4. Validate occurred_at ISO-8601 with explicit timezone (reject naive)
        if not isinstance(self.occurred_at, str) or not self.occurred_at.strip():
            raise InvalidIntegrationEvent("occurred_at must be an ISO-8601 timestamp string")
        try:
            dt = datetime.fromisoformat(self.occurred_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                raise InvalidIntegrationEvent(f"occurred_at '{self.occurred_at}' must contain explicit timezone offset")
        except ValueError as ex:
            raise InvalidIntegrationEvent(f"occurred_at '{self.occurred_at}' is not valid ISO-8601: {ex}")

        # 5. Validate producer_app (wire-compatible application ID)
        try:
            norm_app = validate_application_id(self.producer_app)
            object.__setattr__(self, "producer_app", norm_app)
        except ValueError as e:
            raise InvalidIntegrationEvent(f"Invalid producer_app: {e}")

        # 6. Validate bop_organization_id (canonical strict UUID v4)
        norm_org_id = validate_strict_uuid_v4(self.bop_organization_id, "bop_organization_id")
        object.__setattr__(self, "bop_organization_id", norm_org_id)

        # 7. Validate subject
        if not isinstance(self.subject, BopEntityRef):
            raise InvalidIntegrationEvent(f"subject must be a BopEntityRef, got {type(self.subject).__name__}")

        # 8. Cross-Tenant Integrity Enforcement
        if norm_org_id != self.subject.bop_organization_id:
            raise CrossTenantIntegrationEvent(
                f"Tenant mismatch: envelope bop_organization_id '{norm_org_id}' does not match "
                f"subject bop_organization_id '{self.subject.bop_organization_id}'"
            )

        # 9. Validate correlation_id (canonical strict UUID v4)
        norm_corr = validate_strict_uuid_v4(self.correlation_id, "correlation_id")
        object.__setattr__(self, "correlation_id", norm_corr)

        # 10. Validate causation_id (optional, nullable strict UUID v4)
        if self.causation_id is not None:
            norm_causation = validate_strict_uuid_v4(self.causation_id, "causation_id", allow_none=True)
            object.__setattr__(self, "causation_id", norm_causation)

        # 11. Validate subject vs payload prospect_id equality for initial prospect events
        if self.event_type in (
            "prospect.discovered",
            "prospect.qualified",
            "buying_intent.detected",
            "prospect.ready_for_crm",
        ):
            if "prospect_id" in self.payload:
                if str(self.payload["prospect_id"]) != str(self.subject.entity_id):
                    raise InvalidIntegrationEvent(
                        f"Payload prospect_id '{self.payload['prospect_id']}' must equal "
                        f"subject.entity_id '{self.subject.entity_id}'"
                    )

        # 12. Validate payload and metadata serializability
        if not isinstance(self.payload, dict):
            raise InvalidIntegrationEvent(f"payload must be a dictionary, got {type(self.payload).__name__}")

        try:
            json.dumps(self.payload)
        except (TypeError, OverflowError) as e:
            raise InvalidIntegrationEvent(f"payload is not JSON serializable: {e}")

        if not isinstance(self.metadata, dict):
            raise InvalidIntegrationEvent(f"metadata must be a dictionary, got {type(self.metadata).__name__}")

        try:
            json.dumps(self.metadata)
        except (TypeError, OverflowError) as e:
            raise InvalidIntegrationEvent(f"metadata is not JSON serializable: {e}")

        # 13. Security scan: reject secret tokens and passwords
        _scan_for_secrets(self.payload, "payload")
        _scan_for_secrets(self.metadata, "metadata")

    def to_dict(self) -> Dict[str, Any]:
        """Convert event envelope to dictionary with deterministic nested representation."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "event_version": self.event_version,
            "occurred_at": self.occurred_at,
            "producer_app": self.producer_app,
            "bop_organization_id": self.bop_organization_id,
            "subject": self.subject.to_dict(),
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "payload": self.payload,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Produce deterministic canonical JSON string."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BopIntegrationEvent":
        """Construct BopIntegrationEvent from dictionary representation."""
        if not isinstance(data, dict):
            raise InvalidIntegrationEvent(f"Expected dictionary for event envelope, got {type(data).__name__}")

        required = [
            "event_id",
            "event_type",
            "event_version",
            "occurred_at",
            "bop_organization_id",
            "correlation_id",
            "payload",
        ]
        for fld in required:
            if fld not in data:
                raise InvalidIntegrationEvent(f"Missing required envelope field '{fld}'")

        # Resolve producer_app or source_app
        prod_app = data.get("producer_app") or data.get("source_app")
        if not prod_app:
            raise InvalidIntegrationEvent("Missing required envelope field 'producer_app'")

        # Resolve subject or entity_ref
        raw_subject = data.get("subject") or data.get("entity_ref")
        if raw_subject is None:
            raise InvalidIntegrationEvent("Missing required envelope field 'subject'")

        if isinstance(raw_subject, dict):
            subject = BopEntityRef.from_dict(raw_subject)
        elif isinstance(raw_subject, BopEntityRef):
            subject = raw_subject
        else:
            raise InvalidIntegrationEvent(f"Invalid subject format: {type(raw_subject).__name__}")

        return cls(
            event_id=str(data["event_id"]),
            event_type=str(data["event_type"]),
            event_version=int(data["event_version"]),
            occurred_at=str(data["occurred_at"]),
            producer_app=str(prod_app),
            bop_organization_id=str(data["bop_organization_id"]),
            subject=subject,
            correlation_id=str(data["correlation_id"]),
            causation_id=str(data["causation_id"]) if data.get("causation_id") is not None else None,
            payload=data.get("payload", {}),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_json(cls, raw: str) -> "BopIntegrationEvent":
        """Parse deterministic canonical JSON string into BopIntegrationEvent."""
        try:
            data = json.loads(raw)
        except Exception as e:
            raise InvalidIntegrationEvent(f"Failed to parse event JSON: {e}")
        return cls.from_dict(data)
