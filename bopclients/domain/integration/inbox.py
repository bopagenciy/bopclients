"""Integration inbox domain models for idempotent event consumption."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class InboxStatus(str, Enum):
    """Lifecycle status for consumed inbox records."""

    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


@dataclass
class InboxRecord:
    """Inbox record recording received external integration events for idempotent processing."""

    id: str
    event_id: str
    producer_app: str
    bop_organization_id: str
    event_type: str
    event_version: int
    received_at: str
    envelope_json: Optional[str] = None
    processed_at: Optional[str] = None
    status: str = InboxStatus.RECEIVED.value
    last_error_code: Optional[str] = None
    last_error_message: Optional[str] = None

    @property
    def error_code(self) -> Optional[str]:
        """Compatibility alias for last_error_code."""
        return self.last_error_code

    @property
    def error_message(self) -> Optional[str]:
        """Compatibility alias for last_error_message."""
        return self.last_error_message
