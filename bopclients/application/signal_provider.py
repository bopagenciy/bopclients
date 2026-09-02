"""Public Signal Provider abstraction and deterministic data signal provider implementation."""

from abc import ABC, abstractmethod
from typing import List, Optional, Any, Dict
from datetime import datetime, timezone
from bopclients.domain.prospect import Prospect
from bopclients.domain.signal import Signal
from bopclients.domain.enums import SignalType, SignalCategory, IntentStrength


class IPublicSignalProvider(ABC):
    """Abstract interface for public activity and buying signal discovery providers."""

    @abstractmethod
    def discover_signals(
        self,
        prospect: Prospect,
        signals: List[Signal],
        enrichment_snapshot: Optional[Any] = None,
        contacts: Optional[List[Any]] = None,
    ) -> List[Signal]:
        """Discover verified public activity/intent signals for a prospect."""
        pass


class DeterministicExistingDataSignalProvider(IPublicSignalProvider):
    """Signal provider discovering public activity signals based on verified repository snapshots and evidence."""

    def discover_signals(
        self,
        prospect: Prospect,
        signals: List[Signal],
        enrichment_snapshot: Optional[Any] = None,
        contacts: Optional[List[Any]] = None,
    ) -> List[Signal]:
        discovered: List[Signal] = []
        now_dt = datetime.now(timezone.utc)

        # 1. New contact found signal
        if contacts and len(contacts) > 0:
            latest_contact = contacts[0]
            discovered.append(
                Signal(
                    organization_id=prospect.organization_id,
                    prospect_id=prospect.id,
                    type=SignalType.NEW_CONTACT_FOUND.value,
                    category=SignalCategory.COMPANY_ACTIVITY.value,
                    intent_strength=IntentStrength.MEDIUM.value,
                    value=f"Verified contact found: {getattr(latest_contact, 'name', 'Contact')}",
                    confidence=0.90,
                    source="public_signal_provider",
                    evidence={"contact_name": getattr(latest_contact, 'name', ''), "title": getattr(latest_contact, 'title', '')},
                    detected_at=now_dt.isoformat(),
                )
            )

        # 2. Technology change / detection signal
        if enrichment_snapshot and getattr(enrichment_snapshot, 'technologies', None):
            techs = enrichment_snapshot.technologies
            if isinstance(techs, list) and len(techs) > 0:
                discovered.append(
                    Signal(
                        organization_id=prospect.organization_id,
                        prospect_id=prospect.id,
                        type=SignalType.TECHNOLOGY_CHANGE.value,
                        category=SignalCategory.COMPANY_ACTIVITY.value,
                        intent_strength=IntentStrength.WEAK.value,
                        value=f"Verified tech stack: {', '.join(techs[:3])}",
                        confidence=0.85,
                        source="public_signal_provider",
                        evidence={"technologies": techs, "cms": getattr(enrichment_snapshot, 'cms', None)},
                        detected_at=now_dt.isoformat(),
                    )
                )

        # 3. Recent website activity / snapshot change
        if enrichment_snapshot and getattr(enrichment_snapshot, 'updated_at', None):
            try:
                up_dt = datetime.fromisoformat(enrichment_snapshot.updated_at.replace("Z", "+00:00"))
                days_old = (now_dt - up_dt).total_seconds() / 86400.0
                if days_old <= 14.0 and getattr(enrichment_snapshot, 'http_status', None) == 200:
                    discovered.append(
                        Signal(
                            organization_id=prospect.organization_id,
                            prospect_id=prospect.id,
                            type=SignalType.RECENT_WEBSITE_CHANGE.value,
                            category=SignalCategory.COMPANY_ACTIVITY.value,
                            intent_strength=IntentStrength.WEAK.value,
                            value=f"Active website inspected {int(days_old)} days ago",
                            confidence=0.80,
                            source="public_signal_provider",
                            evidence={"http_status": 200, "days_old": days_old},
                            detected_at=now_dt.isoformat(),
                        )
                    )
            except Exception:
                pass

        # 4. New signal detected meta-signal
        recent_signals = []
        for sig in signals:
            try:
                sig_dt = datetime.fromisoformat(sig.detected_at.replace("Z", "+00:00"))
                if (now_dt - sig_dt).total_seconds() <= 7 * 86400:
                    recent_signals.append(sig.type)
            except Exception:
                pass

        if recent_signals:
            discovered.append(
                Signal(
                    organization_id=prospect.organization_id,
                    prospect_id=prospect.id,
                    type=SignalType.NEW_SIGNAL_DETECTED.value,
                    category=SignalCategory.COMPANY_ACTIVITY.value,
                    intent_strength=IntentStrength.WEAK.value,
                    value=f"New signals detected recently: {', '.join(recent_signals[:3])}",
                    confidence=0.85,
                    source="public_signal_provider",
                    evidence={"recent_signal_types": recent_signals},
                    detected_at=now_dt.isoformat(),
                )
            )

        return discovered
