"""Integration outbox domain models for reliable event publication."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from bopclients.domain.integration.events import BopIntegrationEvent


class OutboxStatus(str, Enum):
    """Publication lifecycle status for outbox records."""

    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


@dataclass
class OutboxRecord:
    """Outbox record representing an immutable integration event awaiting delivery."""

    id: str
    event_id: str
    bop_organization_id: str
    event_type: str
    event_version: int
    producer_app: str
    subject_application_id: str
    subject_entity_type: str
    subject_entity_id: str
    envelope_json: str
    status: str
    attempt_count: int
    available_at: str
    created_at: str
    published_at: Optional[str] = None
    last_error_code: Optional[str] = None
    last_error_message: Optional[str] = None

    def to_event(self) -> BopIntegrationEvent:
        """Deserialize envelope_json into a BopIntegrationEvent instance."""
        return BopIntegrationEvent.from_json(self.envelope_json)
