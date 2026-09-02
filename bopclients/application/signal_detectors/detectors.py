"""Deterministic signal detectors analyzing prospect enrichment snapshots."""

from typing import List, Optional, Dict, Any
from bopclients.domain.prospect import Prospect
from bopclients.application.enrichment_dto import EnrichmentSnapshot, DetectedSignalDTO
from bopclients.application.interfaces.enrichment_interfaces import ISignalDetector


def can_infer_absence(snapshot: EnrichmentSnapshot) -> bool:
    """Helper ensuring negative absence signals are only inferred if homepage was properly inspected."""
    return (
        snapshot.website_reachable
        and snapshot.scrape_status in ("success", "partial_timeout")
        and snapshot.http_status not in (403, 429)
    )


class NoWebsiteDetector(ISignalDetector):
    """Detects missing website URL."""

    @property
    def name(self) -> str:
        return "no_website_detector"

    def detect(
        self, prospect: Prospect, snapshot: EnrichmentSnapshot, context: Optional[Dict[str, Any]] = None
    ) -> List[DetectedSignalDTO]:
        if not prospect.website_url or not prospect.website_url.strip():
            return [
                DetectedSignalDTO(
                    type="no_website",
                    value="No website URL provided for prospect",
                    confidence=1.0,
                    source="bopclients_detector",
                    evidence={"website_url": None, "provider": snapshot.provider},
                )
            ]
        return []


class WebsiteUnreachableDetector(ISignalDetector):
    """Detects confirmed website connection/DNS failures (excluding 403, 429, 5xx, or ambiguous timeout)."""

    @property
    def name(self) -> str:
        return "website_unreachable_detector"

    def detect(
        self, prospect: Prospect, snapshot: EnrichmentSnapshot, context: Optional[Dict[str, Any]] = None
    ) -> List[DetectedSignalDTO]:
        if not prospect.website_url:
            return []

        # 403 Forbidden / 429 Rate Limited / HTTP 5xx / Ambiguous crawler timeouts DO NOT mean dead host
        if (
            (snapshot.http_status and (snapshot.http_status in (403, 429) or snapshot.http_status >= 500))
            or snapshot.scrape_status in ("forbidden", "partial_timeout", "timeout")
        ):
            return []

        # Conclusive evidence of unreachable host (DNS failure, connection refused, host not found)
        if snapshot.scrape_status in ("dns_failure", "connection_refused", "host_not_found"):
            return [
                DetectedSignalDTO(
                    type="website_unreachable",
                    value=f"Website host unreachable ({snapshot.scrape_status})",
                    confidence=0.9,
                    source="bopclients_detector",
                    evidence={
                        "scrape_status": snapshot.scrape_status,
                        "http_status": snapshot.http_status,
                        "provider": snapshot.provider,
                    },
                )
            ]
        return []


class WebsiteSlowDetector(ISignalDetector):
    """Detects slow website latency based on response_time_ms thresholds."""

    @property
    def name(self) -> str:
        return "website_slow_detector"

    def detect(
        self, prospect: Prospect, snapshot: EnrichmentSnapshot, context: Optional[Dict[str, Any]] = None
    ) -> List[DetectedSignalDTO]:
        if not snapshot.website_reachable or snapshot.response_time_ms is None:
            return []

        ms = snapshot.response_time_ms
        if ms < 1500:
            return []

        confidence = 0.6 if ms <= 3000 else 0.9
        return [
            DetectedSignalDTO(
                type="website_slow",
                value=f"Slow response time: {int(ms)}ms",
                confidence=confidence,
                source="bopclients_detector",
                evidence={
                    "response_time_ms": ms,
                    "threshold_ms": 1500,
                    "provider": snapshot.provider,
                },
            )
        ]


class NoSSLDetector(ISignalDetector):
    """Detects unencrypted HTTP or missing SSL certificates."""

    @property
    def name(self) -> str:
        return "no_ssl_detector"

    def detect(
        self, prospect: Prospect, snapshot: EnrichmentSnapshot, context: Optional[Dict[str, Any]] = None
    ) -> List[DetectedSignalDTO]:
        if not snapshot.website_reachable:
            return []

        # Require explicit ssl_valid is False
        if snapshot.ssl_valid is False:
            return [
                DetectedSignalDTO(
                    type="no_ssl",
                    value="Website lacks valid SSL certificate (HTTP only)",
                    confidence=0.95,
                    source="bopclients_detector",
                    evidence={"ssl_valid": False, "url": snapshot.website_url, "provider": snapshot.provider},
                )
            ]
        return []


class NoChatbotDetector(ISignalDetector):
    """Detects absence of interactive AI or live chat widgets."""

    @property
    def name(self) -> str:
        return "no_chatbot_detector"

    def detect(
        self, prospect: Prospect, snapshot: EnrichmentSnapshot, context: Optional[Dict[str, Any]] = None
    ) -> List[DetectedSignalDTO]:
        if not can_infer_absence(snapshot):
            return []

        if not snapshot.has_chatbot:
            return [
                DetectedSignalDTO(
                    type="no_chatbot",
                    value="No AI chatbot or live chat widget detected",
                    confidence=0.9,
                    source="bopclients_detector",
                    evidence={"has_chatbot": False, "provider": snapshot.provider},
                )
            ]
        return []


class NoBookingDetector(ISignalDetector):
    """Detects absence of online booking/scheduling widgets for relevant industries."""

    RELEVANT_CATEGORIES = {
        "dentist", "doctor", "clinic", "healthcare", "beauty", "salon",
        "spa", "barber_shop"
    }

    @property
    def name(self) -> str:
        return "no_booking_detector"

    def detect(
        self, prospect: Prospect, snapshot: EnrichmentSnapshot, context: Optional[Dict[str, Any]] = None
    ) -> List[DetectedSignalDTO]:
        if not can_infer_absence(snapshot):
            return []

        ind = (prospect.industry or "").lower()
        if not any(c in ind for c in self.RELEVANT_CATEGORIES):
            return []

        if not snapshot.has_booking:
            return [
                DetectedSignalDTO(
                    type="no_booking",
                    value=f"No online booking/appointment system detected for category '{prospect.industry}'",
                    confidence=0.85,
                    source="bopclients_detector",
                    evidence={"has_booking": False, "industry": prospect.industry, "provider": snapshot.provider},
                )
            ]
        return []


class NoAnalyticsDetector(ISignalDetector):
    """Detects absence of analytics or tag management trackers."""

    @property
    def name(self) -> str:
        return "no_analytics_detector"

    def detect(
        self, prospect: Prospect, snapshot: EnrichmentSnapshot, context: Optional[Dict[str, Any]] = None
    ) -> List[DetectedSignalDTO]:
        if not can_infer_absence(snapshot):
            return []

        if not snapshot.has_analytics:
            return [
                DetectedSignalDTO(
                    type="no_analytics",
                    value="No Google Analytics or tag manager tracking detected",
                    confidence=0.8,
                    source="bopclients_detector",
                    evidence={"has_analytics": False, "provider": snapshot.provider},
                )
            ]
        return []
