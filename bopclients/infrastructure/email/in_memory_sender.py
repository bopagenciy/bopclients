"""In-memory transactional email sender for local development and deterministic testing."""

import uuid
from typing import List, Optional
from bopclients.application.interfaces.email_sender import ITransactionalEmailSender
from bopclients.domain.email import (
    TransactionalEmailMessage,
    EmailDeliveryResult,
    EmailDeliveryStatus,
)


class InMemoryEmailSender(ITransactionalEmailSender):
    """In-memory sender capturing sent emails for assertions without remote calls."""

    def __init__(
        self,
        simulate_failure: bool = False,
        simulate_error: Optional[str] = None,
        default_from: Optional[str] = None,
    ):
        self.sent_messages: List[TransactionalEmailMessage] = []
        self.simulate_failure = simulate_failure
        self.simulate_error = simulate_error
        self.default_from = default_from

    def get_sent_messages(self) -> List[TransactionalEmailMessage]:
        """Return all recorded messages."""
        return list(self.sent_messages)

    def send(self, message: TransactionalEmailMessage) -> EmailDeliveryResult:
        """Capture message in memory or return simulated failure."""
        if self.simulate_failure:
            return EmailDeliveryResult(
                status=EmailDeliveryStatus.FAILED,
                error=self.simulate_error or "Simulated transmission failure",
            )

        self.sent_messages.append(message)
        message_id = f"msg_inmem_{uuid.uuid4().hex[:12]}"
        return EmailDeliveryResult(
            status=EmailDeliveryStatus.SENT,
            message_id=message_id,
        )

    def clear(self) -> None:
        """Clear recorded messages."""
        self.sent_messages.clear()

    def get_last_message(self) -> Optional[TransactionalEmailMessage]:
        """Retrieve most recently dispatched message."""
        return self.sent_messages[-1] if self.sent_messages else None
