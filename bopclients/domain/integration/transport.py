"""Transport abstraction for external integration event delivery."""

from abc import ABC, abstractmethod

from bopclients.domain.integration.destination import IntegrationDestination
from bopclients.domain.integration.delivery import TransportPublishResult


class IntegrationTransport(ABC):
    """Abstract interface representing a transport delivery mechanism."""

    @property
    @abstractmethod
    def transport_type(self) -> str:
        """Transport protocol identifier (e.g. HTTP)."""
        pass

    @abstractmethod
    def publish(
        self,
        envelope_json: str,
        destination: IntegrationDestination,
        timeout_seconds: float = 10.0,
    ) -> TransportPublishResult:
        """Deliver immutable envelope_json to the given destination.

        Must NOT throw unhandled network exceptions; must return a structured TransportPublishResult.
        Must NOT modify envelope_json.
        """
        pass
