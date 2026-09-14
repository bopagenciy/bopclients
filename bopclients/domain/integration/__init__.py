"""Bop Platform Integration foundation package."""

from bopclients.domain.integration.app_id import BopAppId, LOCAL_APPLICATION_ID, validate_application_id
from bopclients.domain.integration.entity_ref import BopEntityRef
from bopclients.domain.integration.events import BopIntegrationEvent
from bopclients.domain.integration.exceptions import (
    IntegrationError,
    InvalidEntityRef,
    InvalidIntegrationEvent,
    CrossTenantIntegrationEvent,
    UnsupportedEventVersion,
    DuplicateIntegrationEvent,
)
from bopclients.domain.integration.registry import BopEventRegistry, EventPayloadValidator
from bopclients.domain.integration.outbox import OutboxStatus, OutboxRecord
from bopclients.domain.integration.inbox import InboxStatus, InboxRecord

__all__ = [
    "BopAppId",
    "LOCAL_APPLICATION_ID",
    "validate_application_id",
    "BopEntityRef",
    "BopIntegrationEvent",
    "IntegrationError",
    "InvalidEntityRef",
    "InvalidIntegrationEvent",
    "CrossTenantIntegrationEvent",
    "UnsupportedEventVersion",
    "DuplicateIntegrationEvent",
    "BopEventRegistry",
    "EventPayloadValidator",
    "OutboxStatus",
    "OutboxRecord",
    "InboxStatus",
    "InboxRecord",
]
