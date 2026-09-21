"""Application service for triggering and querying Bop CRM handoffs via integration outbox."""

from datetime import datetime, timezone
import logging
from typing import Dict, Any, Optional, List
import uuid
from urllib.parse import urlparse

from bopclients.domain.integration.app_id import LOCAL_APPLICATION_ID
from bopclients.domain.integration.delivery import DeliveryStatus, DeliveryRecord
from bopclients.domain.integration.entity_ref import BopEntityRef
from bopclients.domain.integration.outbox import OutboxStatus, OutboxRecord
from bopclients.domain.integration.registry import BopEventRegistry
from bopclients.domain.exceptions import (
    EntityNotFoundError,
    CrmDestinationNotConfiguredError,
)
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.prospect_priority_repository import ProspectPriorityRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.signal_observation_repository import SignalObservationRepository
from bopclients.infrastructure.repositories.integration_outbox_repository import IntegrationOutboxRepository
from bopclients.infrastructure.repositories.integration_destination_repository import IntegrationDestinationRepository
from bopclients.infrastructure.repositories.integration_delivery_repository import IntegrationDeliveryRepository
from bopclients.application.integration_dispatcher import IntegrationOutboxDispatcher

logger = logging.getLogger("bopclients.application.crm_handoff_service")

DISALLOWED_INTERNAL_HOSTS = {
    "backend",
    "web",
    "api",
    "django-crm-backend",
    "django-crm-frontend",
    "db",
    "redis",
    "bophub-frontend",
    "bophub-backend",
    "integration-dispatcher",
}


def validate_web_public_url(url: str, is_production: bool = False) -> str:
    """Validate public web URL ensuring valid HTTP/HTTPS scheme and preventing internal host/API leaks."""
    if not url or not str(url).strip():
        raise ValueError("Public web URL cannot be empty.")

    cleaned = str(url).strip()
    parsed = urlparse(cleaned)

    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Invalid web public URL '{url}': must be an absolute URL with http or https scheme.")

    hostname = (parsed.hostname or "").lower()
    port = parsed.port

    # Disallow API port 8100 explicitly
    if port == 8100 or ":8100" in cleaned:
        raise ValueError("Web public URL must not point to API host or port (8100).")

    # Disallow Docker-internal hostnames
    if hostname in DISALLOWED_INTERNAL_HOSTS or hostname.endswith((".internal", ".local")):
        raise ValueError(f"Web public URL must not use internal host '{hostname}'.")

    if is_production:
        if parsed.scheme != "https":
            raise ValueError("Web public URL must use HTTPS in production.")
        if hostname in ("localhost", "127.0.0.1"):
            raise ValueError("Web public URL cannot be localhost or loopback in production.")

    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def build_canonical_prospect_url(
    web_public_url: str,
    prospect_id: str,
    locale: str = "en",
    is_production: bool = False,
) -> str:
    """Build canonical browser-facing prospect detail URL matching Next.js routing:
    {web_public_url}/{locale}/prospects/{prospect_id}
    """
    if not web_public_url or not str(web_public_url).strip():
        if is_production:
            raise ValueError("BOPCLIENTS_WEB_PUBLIC_URL is required in production.")
        web_public_url = "http://localhost:3011"

    base = validate_web_public_url(web_public_url, is_production=is_production)

    # Normalize locale (supported: en, es; default: en)
    norm_locale = (locale or "en").strip().lower()
    if norm_locale.startswith("es"):
        resolved_locale = "es"
    elif norm_locale.startswith("en"):
        resolved_locale = "en"
    elif norm_locale in ("en", "es"):
        resolved_locale = norm_locale
    else:
        resolved_locale = "en"

    clean_prospect_id = str(prospect_id).strip()
    if not clean_prospect_id:
        raise ValueError("prospect_id cannot be empty.")

    return f"{base}/{resolved_locale}/prospects/{clean_prospect_id}"


class CrmHandoffService:
    """Service orchestrating prospect handoff into the platform transactional outbox for CRM delivery."""

    def __init__(
        self,
        prospect_repo: ProspectRepository,
        outbox_repo: IntegrationOutboxRepository,
        destination_repo: IntegrationDestinationRepository,
        delivery_repo: IntegrationDeliveryRepository,
        priority_repo: Optional[ProspectPriorityRepository] = None,
        campaign_repo: Optional[CampaignRepository] = None,
        signal_repo: Optional[SignalObservationRepository] = None,
        dispatcher: Optional[IntegrationOutboxDispatcher] = None,
        web_public_url: str = "http://localhost:3011",
        is_production: bool = False,
    ):
        self.prospect_repo = prospect_repo
        self.outbox_repo = outbox_repo
        self.destination_repo = destination_repo
        self.delivery_repo = delivery_repo
        self.priority_repo = priority_repo
        self.campaign_repo = campaign_repo
        self.signal_repo = signal_repo
        self.dispatcher = dispatcher
        self.web_public_url = web_public_url or "http://localhost:3011"
        self.is_production = is_production

    @staticmethod
    def derive_event_id(bop_organization_id: str, prospect_id: str) -> str:
        """Compute deterministic RFC 4122 UUID v4 ensuring idempotency across repeated handoffs."""
        import hashlib

        seed = f"{bop_organization_id}:{prospect_id}:bopcrm_handoff"
        h = hashlib.sha256(seed.encode("utf-8")).digest()
        b = bytearray(h[:16])
        b[6] = (b[6] & 0x0F) | 0x40  # version 4
        b[8] = (b[8] & 0x3F) | 0x80  # variant RFC 4122
        return str(uuid.UUID(bytes=bytes(b)))

    @staticmethod
    def _derive_status(outbox: Optional[OutboxRecord], deliveries: List[DeliveryRecord]) -> str:
        """Map underlying outbox and delivery states to truthful business handoff status:

        - NOT_SENT: no outbox record exists
        - QUEUED: outbox pending or delivery pending
        - DELIVERING: delivery claimed or retry scheduled
        - DELIVERED: outbox published or all deliveries completed
        - FAILED: terminal failure in outbox or all deliveries
        """
        if not outbox:
            return "NOT_SENT"

        if deliveries:
            if all(d.status == DeliveryStatus.DELIVERED.value for d in deliveries):
                return "DELIVERED"
            if any(d.status in (DeliveryStatus.CLAIMED.value, DeliveryStatus.RETRY_PENDING.value) for d in deliveries):
                return "DELIVERING"
            if all(d.status in (DeliveryStatus.DEAD_LETTER.value, "FAILED") for d in deliveries):
                return "FAILED"
            if any(d.status == DeliveryStatus.DELIVERED.value for d in deliveries):
                return "DELIVERED"
            if any(d.status == DeliveryStatus.PENDING.value for d in deliveries):
                return "QUEUED"
            return "QUEUED"

        if outbox.status == OutboxStatus.PUBLISHED.value:
            return "DELIVERED"
        if outbox.status == OutboxStatus.FAILED.value:
            return "FAILED"
        return "QUEUED"

    def trigger_handoff(
        self,
        bop_organization_id: str,
        organization_id: str,
        prospect_id: str,
        requested_by_user_id: str,
        base_url: str = "",
        web_public_url: Optional[str] = None,
        locale: str = "en",
    ) -> Dict[str, Any]:
        """Trigger handoff of a prospect to Bop CRM via canonical integration outbox."""
        # 1. Tenant boundary: verify prospect exists and belongs to tenant
        prospect = self.prospect_repo.get_prospect_by_id(organization_id, prospect_id)
        if not prospect:
            raise EntityNotFoundError(f"Prospect '{prospect_id}' not found.")

        # 2. Check for configured destinations for prospect.ready_for_crm
        destinations = self.destination_repo.get_destinations_for_event(
            bop_organization_id=bop_organization_id,
            event_type=BopEventRegistry.EVENT_PROSPECT_READY_FOR_CRM,
        )
        if not destinations:
            raise CrmDestinationNotConfiguredError(
                "No active integration destination configured for Bop CRM handoff."
            )

        # 3. Deterministic idempotency check
        event_id = self.derive_event_id(bop_organization_id, prospect_id)
        existing_outbox = self.outbox_repo.get_by_event_id(event_id, bop_organization_id=bop_organization_id)
        if existing_outbox:
            deliveries = self.delivery_repo.list_by_event(event_id)
            current_status = self._derive_status(existing_outbox, deliveries)
            corr_id = existing_outbox.to_event().correlation_id if existing_outbox.envelope_json else ""
            return {
                "prospect_id": prospect_id,
                "status": current_status,
                "event_id": event_id,
                "correlation_id": corr_id,
                "requested_at": existing_outbox.created_at,
                "destination_count": len(deliveries) if deliveries else len(destinations),
                "is_idempotent_replay": True,
                "message": "Prospect handoff already processed or queued.",
            }

        # 4. Assemble payload
        lead_score: Optional[int] = None
        priority_tier: Optional[str] = None
        if self.priority_repo:
            priorities = self.priority_repo.get_by_prospect(organization_id, prospect_id)
            if priorities:
                lead_score = int(priorities[0].priority_score)
                priority_tier = priorities[0].priority_label.upper()

        if lead_score is None:
            lead_score = 50
        if not priority_tier:
            priority_tier = "MEDIUM"

        loc_parts = [p for p in [prospect.city, prospect.state, prospect.country] if p]
        location_str = ", ".join(loc_parts) if loc_parts else None

        now_iso = datetime.now(timezone.utc).isoformat()

        # Build canonical public web prospect URL (P28.5)
        target_web_url = web_public_url or self.web_public_url
        if base_url and not web_public_url:
            if not (":8100" in base_url or "backend" in base_url):
                try:
                    validate_web_public_url(base_url, is_production=self.is_production)
                    target_web_url = base_url
                except ValueError:
                    pass

        prospect_url = build_canonical_prospect_url(
            web_public_url=target_web_url,
            prospect_id=prospect.id,
            locale=locale,
            is_production=self.is_production,
        )

        payload: Dict[str, Any] = {
            "prospect_id": prospect.id,
            "company_name": prospect.name,
            "website": prospect.website_url or None,
            "industry": prospect.industry or None,
            "location": location_str,
            "lead_score": lead_score,
            "priority": priority_tier,
            "campaign_id": None,
            "signal_summary": None,
            "source": prospect.source or "manual",
            "prospect_url": prospect_url,
            "handoff_requested_by": requested_by_user_id,
            "handoff_requested_at": now_iso,
            "recommended_action": "handoff_to_crm",
            "human_review_required": False,
        }

        # 5. Build canonical event envelope
        subject = BopEntityRef(
            bop_organization_id=bop_organization_id,
            application_id=LOCAL_APPLICATION_ID,
            entity_type="prospect",
            entity_id=prospect.id,
        )

        event = BopEventRegistry.build_event(
            event_type=BopEventRegistry.EVENT_PROSPECT_READY_FOR_CRM,
            bop_organization_id=bop_organization_id,
            subject=subject,
            payload=payload,
            event_version=2,
            event_id=event_id,
        )

        # 6. Append to outbox
        outbox_rec = self.outbox_repo.append(event, allow_existing=True)

        # 7. Create delivery rows for each subscribed destination
        for dest in destinations:
            self.delivery_repo.create_delivery(
                event_id=event_id,
                destination_id=dest.id,
                bop_organization_id=bop_organization_id,
            )

        return {
            "prospect_id": prospect_id,
            "status": "QUEUED",
            "event_id": event_id,
            "correlation_id": event.correlation_id,
            "requested_at": outbox_rec.created_at,
            "destination_count": len(destinations),
            "is_idempotent_replay": False,
            "message": "Prospect handoff successfully queued for CRM delivery.",
        }

    def get_handoff_status(
        self,
        bop_organization_id: str,
        organization_id: str,
        prospect_id: str,
    ) -> Dict[str, Any]:
        """Query current handoff status for a prospect."""
        prospect = self.prospect_repo.get_prospect_by_id(organization_id, prospect_id)
        if not prospect:
            raise EntityNotFoundError(f"Prospect '{prospect_id}' not found.")

        event_id = self.derive_event_id(bop_organization_id, prospect_id)
        outbox = self.outbox_repo.get_by_event_id(event_id, bop_organization_id=bop_organization_id)

        if not outbox:
            return {
                "prospect_id": prospect_id,
                "status": "NOT_SENT",
                "event_id": None,
                "correlation_id": None,
                "requested_at": None,
                "delivered_at": None,
                "attempt_count": 0,
                "last_error_message": None,
                "destination_count": 0,
                "destinations": [],
            }

        deliveries = self.delivery_repo.list_by_event(event_id)
        derived_status = self._derive_status(outbox, deliveries)
        delivered_at = next((d.delivered_at for d in deliveries if d.delivered_at), outbox.published_at)
        attempts = sum(d.attempt_count for d in deliveries) if deliveries else outbox.attempt_count
        err_msg = next((d.last_error_message for d in deliveries if d.last_error_message), outbox.last_error_message)
        corr_id = outbox.to_event().correlation_id if outbox.envelope_json else ""

        return {
            "prospect_id": prospect_id,
            "status": derived_status,
            "event_id": event_id,
            "correlation_id": corr_id,
            "requested_at": outbox.created_at,
            "delivered_at": delivered_at,
            "attempt_count": attempts,
            "last_error_message": err_msg,
            "destination_count": len(deliveries),
            "destinations": [d.destination_id for d in deliveries],
        }

    def bulk_handoff(
        self,
        bop_organization_id: str,
        organization_id: str,
        prospect_ids: List[str],
        requested_by_user_id: str,
        base_url: str = "",
        web_public_url: Optional[str] = None,
        locale: str = "en",
    ) -> Dict[str, Any]:
        """Trigger handoff for multiple prospects in bulk."""
        destinations = self.destination_repo.get_destinations_for_event(
            bop_organization_id=bop_organization_id,
            event_type=BopEventRegistry.EVENT_PROSPECT_READY_FOR_CRM,
        )
        if not destinations:
            raise CrmDestinationNotConfiguredError(
                "No active integration destination configured for Bop CRM handoff."
            )

        queued = 0
        already_processed = 0
        failed = 0
        errors: Dict[str, str] = {}

        for pid in prospect_ids:
            try:
                res = self.trigger_handoff(
                    bop_organization_id=bop_organization_id,
                    organization_id=organization_id,
                    prospect_id=pid,
                    requested_by_user_id=requested_by_user_id,
                    base_url=base_url,
                    web_public_url=web_public_url,
                    locale=locale,
                )
                if res.get("is_idempotent_replay"):
                    already_processed += 1
                else:
                    queued += 1
            except Exception as e:
                failed += 1
                errors[pid] = str(e)

        return {
            "requested": len(prospect_ids),
            "queued": queued,
            "already_queued_or_delivered": already_processed,
            "failed": failed,
            "errors": errors,
        }
