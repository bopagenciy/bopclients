"""Signal domain entity representing a buying/opportunity signal with taxonomy and intent strength."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Optional
from bopclients.domain.enums import SignalCategory, IntentStrength, SignalType


# Default strict taxonomy mapping for signals (P6.1 Audit Aligned)
SIGNAL_TAXONOMY_MAP = {
    # Need signals (Opportunity indicators — NOT buying intent)
    SignalType.WEBSITE_SLOW.value: (SignalCategory.NEED.value, IntentStrength.NONE.value),
    SignalType.NO_CHATBOT.value: (SignalCategory.NEED.value, IntentStrength.NONE.value),
    SignalType.NO_BOOKING.value: (SignalCategory.NEED.value, IntentStrength.NONE.value),
    SignalType.NO_ANALYTICS.value: (SignalCategory.NEED.value, IntentStrength.NONE.value),
    SignalType.NO_SSL.value: (SignalCategory.NEED.value, IntentStrength.NONE.value),

    # Company activity signals (Indirect activity / expansion — NOT direct vendor search)
    SignalType.HIRING_MARKETING.value: (SignalCategory.COMPANY_ACTIVITY.value, IntentStrength.MEDIUM.value),
    SignalType.HIRING_SALES.value: (SignalCategory.COMPANY_ACTIVITY.value, IntentStrength.MEDIUM.value),
    SignalType.OPENED_NEW_LOCATION.value: (SignalCategory.COMPANY_ACTIVITY.value, IntentStrength.MEDIUM.value),
    SignalType.NEW_FUNDING.value: (SignalCategory.COMPANY_ACTIVITY.value, IntentStrength.MEDIUM.value),
    SignalType.WEBSITE_RELAUNCH.value: (SignalCategory.COMPANY_ACTIVITY.value, IntentStrength.MEDIUM.value),
    SignalType.NEW_SERVICE_LAUNCH.value: (SignalCategory.COMPANY_ACTIVITY.value, IntentStrength.MEDIUM.value),
    SignalType.ACTIVE_ADS.value: (SignalCategory.COMPANY_ACTIVITY.value, IntentStrength.MEDIUM.value),
    SignalType.RECENT_NEWS.value: (SignalCategory.COMPANY_ACTIVITY.value, IntentStrength.WEAK.value),
    SignalType.LOCATION_EXPANSION.value: (SignalCategory.COMPANY_ACTIVITY.value, IntentStrength.MEDIUM.value),
    SignalType.LEADERSHIP_CHANGE.value: (SignalCategory.COMPANY_ACTIVITY.value, IntentStrength.WEAK.value),
    SignalType.TECHNOLOGY_CHANGE.value: (SignalCategory.COMPANY_ACTIVITY.value, IntentStrength.WEAK.value),
    SignalType.RECENT_WEBSITE_CHANGE.value: (SignalCategory.COMPANY_ACTIVITY.value, IntentStrength.WEAK.value),
    SignalType.NEW_CONTACT_FOUND.value: (SignalCategory.COMPANY_ACTIVITY.value, IntentStrength.MEDIUM.value),
    SignalType.NEW_SIGNAL_DETECTED.value: (SignalCategory.COMPANY_ACTIVITY.value, IntentStrength.WEAK.value),

    # Direct verified Buying / Intent signals (Requires explicit public search evidence)
    SignalType.VENDOR_SEARCH.value: (SignalCategory.BUYING_INTENT.value, IntentStrength.STRONG.value),
    SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value: (SignalCategory.BUYING_INTENT.value, IntentStrength.STRONG.value),

    # Data quality signals
    SignalType.SCRAPE_TIMEOUT.value: (SignalCategory.DATA_QUALITY.value, IntentStrength.NONE.value),
    SignalType.LIMITED_SOURCE_COVERAGE.value: (SignalCategory.DATA_QUALITY.value, IntentStrength.NONE.value),
    SignalType.STALE_RESEARCH.value: (SignalCategory.DATA_QUALITY.value, IntentStrength.NONE.value),
}


@dataclass
class Signal:
    """Signal entity representing a business opportunity or tech indicator on a prospect."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    prospect_id: str = ""
    type: str = ""  # SignalType value, e.g., "website_slow", "no_chatbot", "hiring_marketing"
    category: Optional[str] = None  # SignalCategory value: need, buying_intent, company_activity, data_quality
    intent_strength: str = IntentStrength.NONE.value  # none, weak, medium, strong
    value: Optional[str] = None
    confidence: float = 1.0  # 0.0 to 1.0
    source: str = "web_scrape"
    evidence: Optional[dict] = None
    detected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __post_init__(self):
        # Auto-infer taxonomy and intent strength if omitted
        if self.type in SIGNAL_TAXONOMY_MAP:
            cat, strg = SIGNAL_TAXONOMY_MAP[self.type]
            if not self.category:
                self.category = cat
            if self.intent_strength == IntentStrength.NONE.value and strg != IntentStrength.NONE.value:
                self.intent_strength = strg
        if not self.category:
            self.category = SignalCategory.NEED.value

    def validate(self) -> None:
        if not self.organization_id:
            raise ValueError("organization_id required")
        if not self.prospect_id:
            raise ValueError("prospect_id required")
        if not self.type.strip():
            raise ValueError("Signal type cannot be empty")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {self.confidence}")
