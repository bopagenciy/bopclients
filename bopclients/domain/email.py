"""Domain models and value objects for transactional email delivery."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class EmailCategory(str, Enum):
    """Canonical transactional email categories."""

    TEAM_INVITATION = "team_invitation"
    PASSWORD_RESET = "password_reset"
    EMAIL_VERIFICATION = "email_verification"


class EmailDeliveryStatus(str, Enum):
    """Truthful delivery status outcomes."""

    SENT = "sent"
    FAILED = "failed"
    NOT_CONFIGURED = "not_configured"


@dataclass(frozen=True)
class TransactionalEmailMessage:
    """Provider-neutral transactional email payload."""

    to: str
    subject: str
    html_body: str
    text_body: str
    category: EmailCategory
    from_email: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.to or "@" not in self.to:
            raise ValueError(f"Invalid recipient email address: {self.to}")
        if not self.subject or not self.subject.strip():
            raise ValueError("Email subject cannot be empty")
        if not self.html_body and not self.text_body:
            raise ValueError("Email must provide either html_body or text_body")


@dataclass(frozen=True)
class EmailDeliveryResult:
    """Truthful outcome of an email transmission attempt."""

    status: EmailDeliveryStatus
    message_id: Optional[str] = None
    error: Optional[str] = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def is_success(self) -> bool:
        return self.status == EmailDeliveryStatus.SENT
