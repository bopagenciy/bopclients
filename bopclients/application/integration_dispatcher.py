"""Application service orchestrating outbound integration routing, claiming, delivery, and lifecycle."""

from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional, Any
import uuid

from bopclients.domain.integration.delivery import (
    DeliveryRecord,
    DeliveryStatus,
    TransportResultStatus,
)
from bopclients.domain.integration.outbox import OutboxStatus, OutboxRecord
from bopclients.domain.integration.transport import IntegrationTransport
from bopclients.infrastructure.repositories.integration_outbox_repository import IntegrationOutboxRepository
from bopclients.infrastructure.repositories.integration_destination_repository import IntegrationDestinationRepository
from bopclients.infrastructure.repositories.integration_delivery_repository import IntegrationDeliveryRepository

logger = logging.getLogger("bopclients.application.integration_dispatcher")


class IntegrationOutboxDispatcher:
    """Orchestrator for routing outbox events into deliveries and executing claimed deliveries via transports."""

    def __init__(
        self,
        outbox_repo: IntegrationOutboxRepository,
        destination_repo: IntegrationDestinationRepository,
        delivery_repo: IntegrationDeliveryRepository,
        transports: Optional[Dict[str, IntegrationTransport]] = None,
    ):
        self.outbox_repo = outbox_repo
        self.destination_repo = destination_repo
        self.delivery_repo = delivery_repo
        self.transports: Dict[str, IntegrationTransport] = transports or {}

    def register_transport(self, transport: IntegrationTransport) -> None:
        """Register a transport protocol handler."""
        self.transports[transport.transport_type.upper()] = transport

    # ---------------- 1. Routing Phase ----------------

    def route_pending_outbox_events(
        self,
        limit: int = 50,
        bop_organization_id: Optional[str] = None,
    ) -> Dict[str, int]:
        """Expand available PENDING outbox events into destination-specific delivery rows.

        If an event has matching subscribed destinations:
        - Creates a bop_integration_deliveries row for each destination (if not already existing).

        If an event has ZERO matching subscriptions:
        - Does NOT mark the event PUBLISHED (prevents false sense of delivery).
        - Marks outbox status FAILED with code 'NO_SUBSCRIBED_DESTINATIONS'.
        """
        pending_events = self.outbox_repo.list_pending(limit=limit, bop_organization_id=bop_organization_id)
        routed_deliveries_count = 0
        unrouted_events_count = 0

        for outbox in pending_events:
            # Check existing deliveries for this event
            existing_deliveries = self.delivery_repo.list_by_event(outbox.event_id)
            if existing_deliveries:
                # Already expanded into deliveries
                continue

            # Find matching active destinations
            destinations = self.destination_repo.get_destinations_for_event(
                bop_organization_id=outbox.bop_organization_id,
                event_type=outbox.event_type,
            )

            if not destinations:
                # Zero matching destinations: fail with explicit unrouted reason
                self.outbox_repo.mark_failed(
                    event_id=outbox.event_id,
                    error_code="NO_SUBSCRIBED_DESTINATIONS",
                    error_message=f"No active subscriptions found for tenant {outbox.bop_organization_id} and event_type {outbox.event_type}",
                    retry_delay_seconds=None,  # Terminal outbox failure until destinations are configured
                    bop_organization_id=outbox.bop_organization_id,
                )
                unrouted_events_count += 1
                continue

            # Create delivery rows for each destination
            for dest in destinations:
                self.delivery_repo.create_delivery(
                    event_id=outbox.event_id,
                    destination_id=dest.id,
                    bop_organization_id=outbox.bop_organization_id,
                )
                routed_deliveries_count += 1

        return {
            "pending_scanned": len(pending_events),
            "deliveries_created": routed_deliveries_count,
            "unrouted_events": unrouted_events_count,
        }

    # ---------------- 2. Delivery Execution Phase ----------------

    def dispatch_batch(
        self,
        worker_token: str,
        batch_size: int = 25,
        lease_seconds: int = 60,
        timeout_seconds: float = 10.0,
        bop_organization_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Claim due deliveries and execute transport delivery attempts.

        Guarantees:
        - Atomic distributed claiming prevents worker duplicate execution.
        - Immutable attempt history logged for every execution.
        - Stale owner protection on completion.
        - When all deliveries for an event succeed, updates parent outbox event to PUBLISHED.
        - Never mutates envelope_json.
        """
        claimed = self.delivery_repo.claim_due_deliveries(
            worker_token=worker_token,
            lease_seconds=lease_seconds,
            batch_size=batch_size,
            bop_organization_id=bop_organization_id,
        )

        delivered_count = 0
        retried_count = 0
        dead_letter_count = 0
        events_completed = 0

        for delivery in claimed:
            dest = self.destination_repo.get_destination(delivery.destination_id, delivery.bop_organization_id)
            if not dest or not dest.is_active:
                # Destination disabled or removed: configuration error -> dead letter with 0 network calls and attempt_count unchanged
                self.delivery_repo.mark_attempt_failed(
                    delivery_id=delivery.id,
                    claim_token=worker_token,
                    error_code="DESTINATION_INACTIVE",
                    error_message="Destination does not exist or is inactive",
                    is_permanent=True,
                    increment_attempts=False,
                )
                dead_letter_count += 1
                self._check_and_update_outbox_status(delivery.event_id, delivery.bop_organization_id)
                continue

            # Fetch outbox record to get immutable envelope_json
            outbox_rec = self.outbox_repo.get_by_event_id(delivery.event_id, delivery.bop_organization_id)
            if not outbox_rec:
                started_at = datetime.now(timezone.utc)
                finished_at = started_at
                self.delivery_repo.log_attempt(
                    delivery_id=delivery.id,
                    attempt_number=delivery.attempt_count + 1,
                    started_at=started_at,
                    finished_at=finished_at,
                    status=TransportResultStatus.PERMANENT_FAILURE.value,
                    error_code="OUTBOX_EVENT_MISSING",
                    error_message=f"Parent outbox event {delivery.event_id} not found",
                )
                self.delivery_repo.mark_attempt_failed(
                    delivery_id=delivery.id,
                    claim_token=worker_token,
                    error_code="OUTBOX_EVENT_MISSING",
                    error_message=f"Parent outbox event {delivery.event_id} not found",
                    is_permanent=True,
                )
                dead_letter_count += 1
                continue

            transport = self.transports.get(dest.transport_type.upper())
            if not transport:
                started_at = datetime.now(timezone.utc)
                finished_at = started_at
                self.delivery_repo.log_attempt(
                    delivery_id=delivery.id,
                    attempt_number=delivery.attempt_count + 1,
                    started_at=started_at,
                    finished_at=finished_at,
                    status=TransportResultStatus.PERMANENT_FAILURE.value,
                    error_code="UNSUPPORTED_TRANSPORT",
                    error_message=f"No transport registered for type {dest.transport_type}",
                )
                self.delivery_repo.mark_attempt_failed(
                    delivery_id=delivery.id,
                    claim_token=worker_token,
                    error_code="UNSUPPORTED_TRANSPORT",
                    error_message=f"No transport registered for type {dest.transport_type}",
                    is_permanent=True,
                )
                dead_letter_count += 1
                self._check_and_update_outbox_status(delivery.event_id, delivery.bop_organization_id)
                continue

            # Execute transport delivery
            started_at = datetime.now(timezone.utc)
            result = transport.publish(
                envelope_json=outbox_rec.envelope_json,
                destination=dest,
                timeout_seconds=timeout_seconds,
            )
            finished_at = datetime.now(timezone.utc)

            # Log attempt audit record
            self.delivery_repo.log_attempt(
                delivery_id=delivery.id,
                attempt_number=delivery.attempt_count + 1,
                started_at=started_at,
                finished_at=finished_at,
                status=result.status.value,
                status_code=result.status_code,
                error_code=result.error_code,
                error_message=result.error_message,
                response_body_sample=result.response_body_sample,
            )

            if result.status == TransportResultStatus.SUCCESS:
                marked = self.delivery_repo.mark_delivered(
                    delivery_id=delivery.id,
                    claim_token=worker_token,
                    delivered_at=finished_at,
                )
                if marked:
                    delivered_count += 1
                    if self._check_and_update_outbox_status(delivery.event_id, delivery.bop_organization_id):
                        events_completed += 1

            elif result.status == TransportResultStatus.TRANSIENT_FAILURE:
                marked, new_status = self.delivery_repo.mark_attempt_failed(
                    delivery_id=delivery.id,
                    claim_token=worker_token,
                    error_code=result.error_code or "TRANSIENT_FAILURE",
                    error_message=result.error_message or "Transient delivery failure",
                    is_permanent=False,
                    retry_delay_seconds=result.retry_after_seconds,
                )
                if marked:
                    if new_status == DeliveryStatus.DEAD_LETTER.value:
                        dead_letter_count += 1
                    else:
                        retried_count += 1
                self._check_and_update_outbox_status(delivery.event_id, delivery.bop_organization_id)

            else:  # PERMANENT_FAILURE
                marked, new_status = self.delivery_repo.mark_attempt_failed(
                    delivery_id=delivery.id,
                    claim_token=worker_token,
                    error_code=result.error_code or "PERMANENT_FAILURE",
                    error_message=result.error_message or "Permanent delivery failure",
                    is_permanent=True,
                )
                if marked:
                    dead_letter_count += 1
                self._check_and_update_outbox_status(delivery.event_id, delivery.bop_organization_id)

        return {
            "deliveries_claimed": len(claimed),
            "delivered": delivered_count,
            "retried": retried_count,
            "dead_letter": dead_letter_count,
            "events_completed": events_completed,
        }

    # ---------------- 3. Outbox Lifecycle Synchronization ----------------

    def _check_and_update_outbox_status(self, event_id: str, bop_organization_id: str) -> bool:
        """Check all delivery records for event_id and update parent outbox status if complete.

        - If ALL deliveries are DELIVERED -> outbox status becomes PUBLISHED.
        - If ANY delivery is DEAD_LETTER and none are PENDING/CLAIMED/RETRY_PENDING -> outbox status becomes FAILED.
        - Otherwise, outbox remains PENDING.
        """
        deliveries = self.delivery_repo.list_by_event(event_id)
        if not deliveries:
            return False

        all_delivered = all(d.status == DeliveryStatus.DELIVERED.value for d in deliveries)
        if all_delivered:
            return self.outbox_repo.mark_published(event_id=event_id, bop_organization_id=bop_organization_id)

        has_active = any(d.status in (DeliveryStatus.PENDING.value, DeliveryStatus.CLAIMED.value, DeliveryStatus.RETRY_PENDING.value) for d in deliveries)
        if not has_active:
            # All finished, but at least one DEAD_LETTER
            first_dead = next((d for d in deliveries if d.status == DeliveryStatus.DEAD_LETTER.value), None)
            err_code = first_dead.last_error_code if first_dead else "DELIVERY_DEAD_LETTER"
            err_msg = first_dead.last_error_message if first_dead else "One or more destination deliveries reached dead letter"
            self.outbox_repo.mark_failed(
                event_id=event_id,
                error_code=err_code or "DELIVERY_DEAD_LETTER",
                error_message=err_msg or "Dead letter delivery",
                retry_delay_seconds=None,
                bop_organization_id=bop_organization_id,
            )

        return False
