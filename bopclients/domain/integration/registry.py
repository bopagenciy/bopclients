"""Registry of canonical Bop Platform event types and versioned payload contracts."""

from datetime import datetime, timezone
import uuid
from typing import Dict, Any, Optional, Callable, Set

from bopclients.domain.integration.app_id import LOCAL_APPLICATION_ID
from bopclients.domain.integration.entity_ref import BopEntityRef
from bopclients.domain.integration.events import BopIntegrationEvent
from bopclients.domain.integration.exceptions import (
    InvalidIntegrationEvent,
    UnsupportedEventVersion,
)
from bopclients.domain.signal import (
    is_canonical_buying_intent_signal,
    get_canonical_signal_category,
)


class EventPayloadValidator:
    """Validator validating version-1 integration event payloads with strict field whitelisting."""

    # 1. prospect.discovered v1
    ALLOWED_KEYS_PROSPECT_DISCOVERED_V1 = {
        "prospect_id",
        "display_name",
        "source_provider",
        "campaign_id",
        "website",
        "source_external_id",
    }

    @classmethod
    def validate_prospect_discovered_v1(cls, payload: Dict[str, Any]) -> None:
        extra_keys = set(payload.keys()) - cls.ALLOWED_KEYS_PROSPECT_DISCOVERED_V1
        if extra_keys:
            raise InvalidIntegrationEvent(
                f"prospect.discovered v1 contains unauthorized field(s): {sorted(extra_keys)}"
            )

        if not isinstance(payload.get("prospect_id"), str) or not payload["prospect_id"].strip():
            raise InvalidIntegrationEvent("prospect.discovered v1 requires non-empty string 'prospect_id'")
        if not isinstance(payload.get("display_name"), str) or not payload["display_name"].strip():
            raise InvalidIntegrationEvent("prospect.discovered v1 requires non-empty string 'display_name'")
        if not isinstance(payload.get("source_provider"), str) or not payload["source_provider"].strip():
            raise InvalidIntegrationEvent("prospect.discovered v1 requires non-empty string 'source_provider'")

        if payload.get("campaign_id") is not None and not isinstance(payload["campaign_id"], str):
            raise InvalidIntegrationEvent("prospect.discovered v1 'campaign_id' must be a string if provided")
        if payload.get("website") is not None and not isinstance(payload["website"], str):
            raise InvalidIntegrationEvent("prospect.discovered v1 'website' must be a string if provided")
        if payload.get("source_external_id") is not None and not isinstance(payload["source_external_id"], str):
            raise InvalidIntegrationEvent("prospect.discovered v1 'source_external_id' must be a string if provided")

    # 2. prospect.qualified v1
    ALLOWED_KEYS_PROSPECT_QUALIFIED_V1 = {
        "prospect_id",
        "lead_score",
        "priority",
        "qualification_reason",
        "evidence_summary",
        "qualification_summary",
    }

    @classmethod
    def validate_prospect_qualified_v1(cls, payload: Dict[str, Any]) -> None:
        extra_keys = set(payload.keys()) - cls.ALLOWED_KEYS_PROSPECT_QUALIFIED_V1
        if extra_keys:
            raise InvalidIntegrationEvent(
                f"prospect.qualified v1 contains unauthorized field(s): {sorted(extra_keys)}"
            )

        if not isinstance(payload.get("prospect_id"), str) or not payload["prospect_id"].strip():
            raise InvalidIntegrationEvent("prospect.qualified v1 requires non-empty string 'prospect_id'")
        lead_score = payload.get("lead_score")
        if not isinstance(lead_score, (int, float)) or isinstance(lead_score, bool):
            raise InvalidIntegrationEvent("prospect.qualified v1 requires numeric 'lead_score'")
        if lead_score < 0 or lead_score > 100:
            raise InvalidIntegrationEvent(f"prospect.qualified v1 'lead_score' must be between 0 and 100, got {lead_score}")
        if not isinstance(payload.get("priority"), str) or not payload["priority"].strip():
            raise InvalidIntegrationEvent("prospect.qualified v1 requires non-empty string 'priority'")

        reason = payload.get("qualification_reason") or payload.get("evidence_summary") or payload.get("qualification_summary")
        if not isinstance(reason, str) or not reason.strip():
            raise InvalidIntegrationEvent(
                "prospect.qualified v1 requires non-empty string 'qualification_reason' or 'evidence_summary'"
            )

    # 3. buying_intent.detected v1
    ALLOWED_KEYS_BUYING_INTENT_DETECTED_V1 = {
        "prospect_id",
        "signal_id",
        "signal_type",
        "confidence",
        "source",
        "observed_at",
        "evidence_reference",
    }

    @classmethod
    def validate_buying_intent_detected_v1(cls, payload: Dict[str, Any]) -> None:
        extra_keys = set(payload.keys()) - cls.ALLOWED_KEYS_BUYING_INTENT_DETECTED_V1
        if extra_keys:
            raise InvalidIntegrationEvent(
                f"buying_intent.detected v1 contains unauthorized field(s): {sorted(extra_keys)}"
            )

        if not isinstance(payload.get("prospect_id"), str) or not payload["prospect_id"].strip():
            raise InvalidIntegrationEvent("buying_intent.detected v1 requires non-empty string 'prospect_id'")
        if not isinstance(payload.get("signal_id"), str) or not payload["signal_id"].strip():
            raise InvalidIntegrationEvent("buying_intent.detected v1 requires non-empty string 'signal_id'")
        sig_type = payload.get("signal_type")
        if not isinstance(sig_type, str) or not sig_type.strip():
            raise InvalidIntegrationEvent("buying_intent.detected v1 requires non-empty string 'signal_type'")
        st_clean = sig_type.strip().lower()
        if not is_canonical_buying_intent_signal(st_clean):
            cat = get_canonical_signal_category(st_clean)
            cat_name = cat.value if cat else "unknown"
            raise InvalidIntegrationEvent(
                f"signal_type '{sig_type}' is not classified as BUYING_INTENT (category: '{cat_name}'). "
                f"Generic company activities (e.g. hiring, expansion, funding) and need signals (e.g. website performance) "
                f"cannot produce buying_intent.detected events."
            )
        conf = payload.get("confidence")
        if not isinstance(conf, (int, float)) or isinstance(conf, bool) or conf < 0.0 or conf > 1.0:
            raise InvalidIntegrationEvent("buying_intent.detected v1 requires 'confidence' float between 0.0 and 1.0")
        if not isinstance(payload.get("source"), str) or not payload["source"].strip():
            raise InvalidIntegrationEvent("buying_intent.detected v1 requires non-empty string 'source'")
        obs = payload.get("observed_at")
        if not isinstance(obs, str) or not obs.strip():
            raise InvalidIntegrationEvent("buying_intent.detected v1 requires non-empty string 'observed_at'")
        try:
            dt = datetime.fromisoformat(obs.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                raise InvalidIntegrationEvent(f"buying_intent.detected v1 'observed_at' '{obs}' must contain explicit timezone offset")
        except ValueError as ex:
            raise InvalidIntegrationEvent(f"buying_intent.detected v1 'observed_at' '{obs}' is not valid ISO-8601: {ex}")
        if payload.get("evidence_reference") is not None and not isinstance(payload["evidence_reference"], str):
            raise InvalidIntegrationEvent("buying_intent.detected v1 'evidence_reference' must be a string if provided")

    # 4. prospect.ready_for_crm v1 (Zero PII, no consumer routing)
    ALLOWED_KEYS_PROSPECT_READY_FOR_CRM_V1 = {
        "prospect_id",
        "lead_score",
        "priority",
        "recommended_action",
        "human_review_required",
    }

    @classmethod
    def validate_prospect_ready_for_crm_v1(cls, payload: Dict[str, Any]) -> None:
        extra_keys = set(payload.keys()) - cls.ALLOWED_KEYS_PROSPECT_READY_FOR_CRM_V1
        if extra_keys:
            raise InvalidIntegrationEvent(
                f"prospect.ready_for_crm v1 contains unauthorized field(s): {sorted(extra_keys)}. "
                f"PII fields (e.g. 'primary_contact', 'email') and routing fields (e.g. 'target_crm') are strictly prohibited in v1."
            )

        if not isinstance(payload.get("prospect_id"), str) or not payload["prospect_id"].strip():
            raise InvalidIntegrationEvent("prospect.ready_for_crm v1 requires non-empty string 'prospect_id'")
        lead_score = payload.get("lead_score")
        if not isinstance(lead_score, (int, float)) or isinstance(lead_score, bool):
            raise InvalidIntegrationEvent("prospect.ready_for_crm v1 requires numeric 'lead_score'")
        if lead_score < 0 or lead_score > 100:
            raise InvalidIntegrationEvent(f"prospect.ready_for_crm v1 'lead_score' must be between 0 and 100, got {lead_score}")
        if not isinstance(payload.get("priority"), str) or not payload["priority"].strip():
            raise InvalidIntegrationEvent("prospect.ready_for_crm v1 requires non-empty string 'priority'")
        if not isinstance(payload.get("recommended_action"), str) or not payload["recommended_action"].strip():
            raise InvalidIntegrationEvent("prospect.ready_for_crm v1 requires non-empty string 'recommended_action'")
        if not isinstance(payload.get("human_review_required"), bool):
            raise InvalidIntegrationEvent("prospect.ready_for_crm v1 requires boolean 'human_review_required'")

    # 5. prospect.ready_for_crm v2 (Bop CRM cross-app handoff foundation)
    ALLOWED_KEYS_PROSPECT_READY_FOR_CRM_V2 = {
        "prospect_id",
        "company_name",
        "website",
        "industry",
        "location",
        "lead_score",
        "priority",
        "campaign_id",
        "signal_summary",
        "source",
        "prospect_url",
        "handoff_requested_by",
        "handoff_requested_at",
        "recommended_action",
        "human_review_required",
    }

    @classmethod
    def validate_prospect_ready_for_crm_v2(cls, payload: Dict[str, Any]) -> None:
        extra_keys = set(payload.keys()) - cls.ALLOWED_KEYS_PROSPECT_READY_FOR_CRM_V2
        if extra_keys:
            raise InvalidIntegrationEvent(
                f"prospect.ready_for_crm v2 contains unauthorized field(s): {sorted(extra_keys)}. "
                f"Sensitive credentials and direct transport routing fields are prohibited."
            )

        if not isinstance(payload.get("prospect_id"), str) or not payload["prospect_id"].strip():
            raise InvalidIntegrationEvent("prospect.ready_for_crm v2 requires non-empty string 'prospect_id'")
        if not isinstance(payload.get("company_name"), str) or not payload["company_name"].strip():
            raise InvalidIntegrationEvent("prospect.ready_for_crm v2 requires non-empty string 'company_name'")

        lead_score = payload.get("lead_score")
        if lead_score is not None:
            if not isinstance(lead_score, (int, float)) or isinstance(lead_score, bool):
                raise InvalidIntegrationEvent("prospect.ready_for_crm v2 'lead_score' must be numeric if provided")
            if lead_score < 0 or lead_score > 100:
                raise InvalidIntegrationEvent(f"prospect.ready_for_crm v2 'lead_score' must be between 0 and 100, got {lead_score}")

        priority = payload.get("priority")
        if priority is not None and (not isinstance(priority, str) or not priority.strip()):
            raise InvalidIntegrationEvent("prospect.ready_for_crm v2 'priority' must be non-empty string if provided")

        for str_field in ("website", "industry", "location", "campaign_id", "source", "prospect_url", "handoff_requested_by", "handoff_requested_at", "recommended_action"):
            val = payload.get(str_field)
            if val is not None and not isinstance(val, str):
                raise InvalidIntegrationEvent(f"prospect.ready_for_crm v2 '{str_field}' must be a string if provided")

        hr = payload.get("human_review_required")
        if hr is not None and not isinstance(hr, bool):
            raise InvalidIntegrationEvent("prospect.ready_for_crm v2 'human_review_required' must be boolean if provided")


class BopEventRegistry:
    """Registry managing supported Bop Platform event types and their versioned payload schemas.

    Notice: Does NOT couple domain events to consumer topologies or application lists.
    """

    EVENT_PROSPECT_DISCOVERED = "prospect.discovered"
    EVENT_PROSPECT_QUALIFIED = "prospect.qualified"
    EVENT_BUYING_INTENT_DETECTED = "buying_intent.detected"
    EVENT_PROSPECT_READY_FOR_CRM = "prospect.ready_for_crm"

    _REGISTRY: Dict[str, Dict[int, Callable[[Dict[str, Any]], None]]] = {
        EVENT_PROSPECT_DISCOVERED: {
            1: EventPayloadValidator.validate_prospect_discovered_v1,
        },
        EVENT_PROSPECT_QUALIFIED: {
            1: EventPayloadValidator.validate_prospect_qualified_v1,
        },
        EVENT_BUYING_INTENT_DETECTED: {
            1: EventPayloadValidator.validate_buying_intent_detected_v1,
        },
        EVENT_PROSPECT_READY_FOR_CRM: {
            1: EventPayloadValidator.validate_prospect_ready_for_crm_v1,
            2: EventPayloadValidator.validate_prospect_ready_for_crm_v2,
        },
    }

    @classmethod
    def get_supported_event_types(cls) -> Set[str]:
        """Return set of all registered event types."""
        return set(cls._REGISTRY.keys())

    @classmethod
    def is_registered(cls, event_type: str, event_version: int) -> bool:
        """Check if an event type and version pair is registered."""
        versions = cls._REGISTRY.get(event_type)
        return versions is not None and event_version in versions

    @classmethod
    def validate_event_payload(cls, event_type: str, event_version: int, payload: Dict[str, Any]) -> None:
        """Validate an event payload against its versioned contract specification.

        Raises:
            UnsupportedEventVersion: If the event_type is registered but event_version is unsupported.
            InvalidIntegrationEvent: If payload does not satisfy the registered schema.
        """
        if event_type not in cls._REGISTRY:
            if not isinstance(payload, dict):
                raise InvalidIntegrationEvent(f"Payload must be a dictionary, got {type(payload).__name__}")
            return

        versions = cls._REGISTRY[event_type]
        if event_version not in versions:
            raise UnsupportedEventVersion(
                f"Unsupported version {event_version} for event type '{event_type}'. "
                f"Supported versions: {sorted(versions.keys())}"
            )

        validator = versions[event_version]
        validator(payload)

    @classmethod
    def build_event(
        cls,
        event_type: str,
        bop_organization_id: str,
        subject: BopEntityRef,
        payload: Dict[str, Any],
        event_version: int = 1,
        producer_app: str = LOCAL_APPLICATION_ID,
        correlation_id: Optional[str] = None,
        causation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        event_id: Optional[str] = None,
        occurred_at: Optional[str] = None,
    ) -> BopIntegrationEvent:
        """Factory method building and validating a canonical BopIntegrationEvent."""
        cls.validate_event_payload(event_type, event_version, payload)

        eid = event_id or str(uuid.uuid4())
        occ = occurred_at or datetime.now(timezone.utc).isoformat()
        corr = correlation_id or str(uuid.uuid4())

        return BopIntegrationEvent(
            event_id=eid,
            event_type=event_type,
            event_version=event_version,
            occurred_at=occ,
            producer_app=producer_app,
            bop_organization_id=bop_organization_id,
            subject=subject,
            correlation_id=corr,
            causation_id=causation_id,
            payload=payload,
            metadata=metadata or {},
        )
