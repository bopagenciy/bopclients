"""Interface for transactional email senders."""

from abc import ABC, abstractmethod
from bopclients.domain.email import TransactionalEmailMessage, EmailDeliveryResult


class ITransactionalEmailSender(ABC):
    """Abstract interface for dispatching transactional emails."""

    @abstractmethod
    def send(self, message: TransactionalEmailMessage) -> EmailDeliveryResult:
        """Send a transactional email message and return a truthful delivery result."""
        ...
