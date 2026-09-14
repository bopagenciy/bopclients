"""Canonical cross-application entity reference for the Bop Platform ecosystem."""

from dataclasses import dataclass
import uuid
from typing import Dict, Any

from bopclients.domain.integration.app_id import validate_application_id
from bopclients.domain.integration.exceptions import InvalidEntityRef


@dataclass(frozen=True)
class BopEntityRef:
    """Immutable canonical entity reference linking domain entities across Bop applications.

    Carries universal tenant identity (bop_organization_id) and an opaque entity identifier
    to avoid coupling independent application database primary keys.
    """

    bop_organization_id: str
    application_id: str
    entity_type: str
    entity_id: str

    def __post_init__(self):
        # 1. Validate bop_organization_id (canonical strict UUID v4)
        if not isinstance(self.bop_organization_id, str) or not self.bop_organization_id.strip():
            raise InvalidEntityRef("bop_organization_id must be a non-empty string UUID")
        raw_uuid = self.bop_organization_id.strip()
        try:
            parsed_uuid = uuid.UUID(raw_uuid)
        except (ValueError, AttributeError):
            raise InvalidEntityRef(f"bop_organization_id '{self.bop_organization_id}' is not a valid UUID")
        if parsed_uuid.version != 4:
            raise InvalidEntityRef(f"bop_organization_id '{self.bop_organization_id}' must be a UUID version 4 (got version {parsed_uuid.version})")
        object.__setattr__(self, "bop_organization_id", str(parsed_uuid))

        # 2. Validate application_id (wire-compatible Bop application syntax)
        try:
            norm_app = validate_application_id(self.application_id)
            object.__setattr__(self, "application_id", norm_app)
        except ValueError as e:
            raise InvalidEntityRef(str(e))

        # 3. Validate entity_type
        if not isinstance(self.entity_type, str) or not self.entity_type.strip():
            raise InvalidEntityRef("entity_type must be a non-empty string")
        norm_type = self.entity_type.strip().lower()
        if not norm_type.replace("_", "").isalnum():
            raise InvalidEntityRef(f"entity_type '{self.entity_type}' contains invalid characters")
        object.__setattr__(self, "entity_type", norm_type)

        # 4. Validate entity_id (opaque string, bounded length, not assumed UUID, not stripped/altered)
        if not isinstance(self.entity_id, str) or len(self.entity_id) == 0:
            raise InvalidEntityRef("entity_id must be a non-empty string")
        if not self.entity_id.strip():
            raise InvalidEntityRef("entity_id cannot be whitespace-only")
        if len(self.entity_id) > 128:
            raise InvalidEntityRef(f"entity_id exceeds maximum length of 128 characters ({len(self.entity_id)})")
        object.__setattr__(self, "entity_id", self.entity_id)

    @property
    def app_id(self) -> str:
        """Compatibility alias for application_id."""
        return self.application_id

    def to_dict(self) -> Dict[str, str]:
        """Return deterministic dictionary representation."""
        return {
            "bop_organization_id": self.bop_organization_id,
            "application_id": self.application_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BopEntityRef":
        """Reconstruct BopEntityRef from dictionary representation."""
        if not isinstance(data, dict):
            raise InvalidEntityRef(f"Expected dictionary for BopEntityRef, got {type(data).__name__}")

        if "bop_organization_id" not in data:
            raise InvalidEntityRef("Missing required field 'bop_organization_id' in BopEntityRef data")

        app_id = data.get("application_id") or data.get("app_id")
        if not app_id:
            raise InvalidEntityRef("Missing required field 'application_id' in BopEntityRef data")

        if "entity_type" not in data:
            raise InvalidEntityRef("Missing required field 'entity_type' in BopEntityRef data")

        if "entity_id" not in data:
            raise InvalidEntityRef("Missing required field 'entity_id' in BopEntityRef data")

        return cls(
            bop_organization_id=str(data["bop_organization_id"]),
            application_id=str(app_id),
            entity_type=str(data["entity_type"]),
            entity_id=str(data["entity_id"]),
        )
