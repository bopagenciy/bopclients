"""Null email sender representing an unconfigured or disabled mail environment."""

from bopclients.application.interfaces.email_sender import ITransactionalEmailSender
from bopclients.domain.email import (
    TransactionalEmailMessage,
    EmailDeliveryResult,
    EmailDeliveryStatus,
)


class NullEmailSender(ITransactionalEmailSender):
    """Fallback sender when no email provider is configured. Truthfully reports not_configured."""

    def send(self, message: TransactionalEmailMessage) -> EmailDeliveryResult:
        return EmailDeliveryResult(
            status=EmailDeliveryStatus.NOT_CONFIGURED,
            error="Transactional email provider is not configured",
        )
