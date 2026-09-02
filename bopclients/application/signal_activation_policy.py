"""SignalActivationPolicy governing activation, provenance, cross-provider corroboration, and TTL expiration of Signals."""

import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple, Dict, Any
from bopclients.domain.signal import Signal
from bopclients.domain.signal_observation import PublicSignalObservation
from bopclients.domain.enums import SignalCategory, IntentStrength, SignalType


class SourceReliability:
    """Source reliability weights for provenance scoring."""

    OFFICIAL_COMPANY_SITE = 1.0
    GOVERNMENT_PROCUREMENT = 1.0
    OFFICIAL_PRESS_RELEASE = 0.95
    PRESS_RELEASE_DISTRIBUTION = 0.95
    REPUTABLE_NEWS = 0.85
    UNKNOWN_NEWS = 0.60
    SEARCH_SNIPPET_ONLY = 0.50

    @classmethod
    def get_weight(cls, source_type: str) -> float:
        st = (source_type or "").lower().strip()
        if "official" in st or "company" in st or "careers" in st:
            return cls.OFFICIAL_COMPANY_SITE
        elif "government" in st or "procurement" in st:
            return cls.GOVERNMENT_PROCUREMENT
        elif "distribution" in st:
            return cls.PRESS_RELEASE_DISTRIBUTION
        elif "press" in st:
            return cls.OFFICIAL_PRESS_RELEASE
        elif "reputable" in st or "news" in st:
            return cls.REPUTABLE_NEWS
        elif "unknown" in st:
            return cls.UNKNOWN_NEWS
        return cls.SEARCH_SNIPPET_ONLY


class SignalActivationPolicy:
    """Policy governing activation threshold rules, evidence currentness, cross-provider corroboration, and signal expiration."""

    INTENT_MIN_CONFIDENCE = 0.70
    ACTIVITY_MIN_CONFIDENCE = 0.50
    DEFAULT_INTENT_TTL_DAYS = 30.0
    DEFAULT_ACTIVITY_TTL_DAYS = 60.0

    @classmethod
    def _is_same_host_boundary(cls, prospect_website_url: Optional[str], source_url: str) -> bool:
        if not prospect_website_url or not source_url:
            return False
        b_host = urllib.parse.urlparse(prospect_website_url).netloc.lower().split(":")[0]
        s_host = urllib.parse.urlparse(source_url).netloc.lower().split(":")[0]
        if b_host.startswith("www."):
            b_host = b_host[4:]
        if s_host.startswith("www."):
            s_host = s_host[4:]
        return b_host == s_host

    def evaluate_activation(
        self,
        observation: PublicSignalObservation,
        now_dt: Optional[datetime] = None,
        prospect_website_url: Optional[str] = None,
        supporting_observations: Optional[List[PublicSignalObservation]] = None,
    ) -> Tuple[bool, Optional[Signal], str]:
        """Evaluate if an observation should activate or update a domain Signal with strict cross-provider corroboration."""
        now_dt = now_dt or datetime.now(timezone.utc)
        rel_weight = SourceReliability.get_weight(observation.source_type)
        base_conf = min(1.0, observation.confidence * rel_weight)

        primary_event_key = observation.compute_semantic_event_key()

        # Cross-Provider Corroboration & Syndication Policy:
        # Corroboration applies ONLY to distinct observations matching the SAME semantic_event_key with unique URLs
        obs_refs = [observation.id]
        seen_urls = {(observation.source_url or "").strip().lower()}

        if supporting_observations:
            for supp in supporting_observations:
                supp_key = supp.compute_semantic_event_key()
                supp_url = (supp.source_url or "").strip().lower()

                # Deduplicate exact same canonical URL (syndication / duplicate crawl)
                if supp_key == primary_event_key and supp_url not in seen_urls:
                    seen_urls.add(supp_url)
                    obs_refs.append(supp.id)

        corroboration_count = len(obs_refs)
        corroboration_bonus = min(0.10, 0.05 * (corroboration_count - 1)) if corroboration_count > 1 else 0.0
        effective_conf = min(1.0, base_conf + corroboration_bonus)

        # 1. Buying Intent Activation Gate
        if observation.category == SignalCategory.BUYING_INTENT.value:
            if effective_conf < self.INTENT_MIN_CONFIDENCE:
                return False, None, f"Confidence {effective_conf:.2f} is below minimum threshold ({self.INTENT_MIN_CONFIDENCE})"

            if not observation.evidence or not isinstance(observation.evidence, dict) or len(observation.evidence) == 0:
                return False, None, "Buying intent requires non-empty evidence dictionary"

            if not observation.source_url:
                return False, None, "Buying intent requires non-empty source_url provenance"

            # Strict Official Host Boundary Enforcement for Official Website Provider
            if prospect_website_url and observation.provider == "official_website":
                if not self._is_same_host_boundary(prospect_website_url, observation.source_url):
                    return False, None, f"Buying intent activation rejected: source_url '{observation.source_url}' is outside official prospect host boundary"

            currentness = observation.evidence.get("currentness", "unknown")
            if currentness != "active":
                return False, None, f"Buying intent activation rejected: currentness is '{currentness}' (requires 'active')"

            due_str = observation.evidence.get("due_date")
            if due_str:
                try:
                    due_dt = datetime.fromisoformat(str(due_str).replace("Z", "+00:00"))
                    if now_dt > due_dt:
                        return False, None, f"Buying intent activation rejected: due_date '{due_str}' is in the past"
                except Exception:
                    pass

            sig = Signal(
                organization_id=observation.organization_id,
                prospect_id=observation.prospect_id,
                type=observation.signal_type,
                category=observation.category,
                intent_strength=observation.intent_strength,
                confidence=round(effective_conf, 2),
                source=observation.provider,
                evidence={
                    "semantic_event_key": primary_event_key,
                    "observation_id": observation.id,
                    "observation_refs": obs_refs,
                    "corroboration_count": corroboration_count,
                    "source_url": observation.source_url,
                    "source_type": observation.source_type,
                    "snippet": observation.evidence.get("snippet", ""),
                    "page_title": observation.evidence.get("page_title", ""),
                    "currentness": currentness,
                    "due_date": due_str,
                    "matched_rule": observation.evidence.get("matched_rule"),
                },
                detected_at=observation.last_seen_at or now_dt.isoformat(),
            )
            return True, sig, f"Buying intent signal activated (conf {effective_conf:.2f}, corroboration_count={corroboration_count})"

        # 2. Company Activity Activation Gate
        elif observation.category == SignalCategory.COMPANY_ACTIVITY.value:
            if effective_conf < self.ACTIVITY_MIN_CONFIDENCE:
                return False, None, f"Confidence {effective_conf:.2f} is below minimum activity threshold ({self.ACTIVITY_MIN_CONFIDENCE})"

            sig = Signal(
                organization_id=observation.organization_id,
                prospect_id=observation.prospect_id,
                type=observation.signal_type,
                category=observation.category,
                intent_strength=observation.intent_strength,
                confidence=round(effective_conf, 2),
                source=observation.provider,
                evidence={
                    "semantic_event_key": primary_event_key,
                    "observation_id": observation.id,
                    "observation_refs": obs_refs,
                    "corroboration_count": corroboration_count,
                    "source_url": observation.source_url,
                    "source_type": observation.source_type,
                    "snippet": observation.evidence.get("snippet", "") if isinstance(observation.evidence, dict) else "",
                },
                detected_at=observation.last_seen_at or now_dt.isoformat(),
            )
            return True, sig, f"Company activity signal activated (conf {effective_conf:.2f}, corroboration_count={corroboration_count})"

        return False, None, f"Category '{observation.category}' does not trigger signal activation"

    def reconcile_expirations(
        self,
        organization_id: str,
        prospect_id: str,
        current_signals: List[Signal],
        observations: List[PublicSignalObservation],
        now_dt: Optional[datetime] = None,
    ) -> Tuple[List[Signal], List[Signal], List[str]]:
        """Reconcile active signals against observations currentness state, TTLs and due dates."""
        now_dt = now_dt or datetime.now(timezone.utc)
        retained = []
        expired = []
        reasons = []

        obs_by_type = {obs.signal_type: obs for obs in observations}

        for sig in current_signals:
            is_expired = False
            reason = ""

            matching_obs = obs_by_type.get(sig.type)
            if matching_obs and isinstance(matching_obs.evidence, dict):
                obs_cur = matching_obs.evidence.get("currentness", "")
                if obs_cur and obs_cur != "active":
                    is_expired = True
                    reason = f"Signal '{sig.type}' deactivated because observation currentness transitioned to '{obs_cur}'"

            # Check evidence due_date if present for RFP
            if not is_expired and sig.type == SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value and isinstance(sig.evidence, dict):
                due_str = sig.evidence.get("due_date")
                if due_str:
                    try:
                        due_dt = datetime.fromisoformat(str(due_str).replace("Z", "+00:00"))
                        if now_dt > due_dt:
                            is_expired = True
                            reason = f"RFP due date '{due_str}' has passed"
                    except Exception:
                        pass

            # Check TTL relative to detected_at or last observation
            if not is_expired and sig.detected_at:
                try:
                    sig_dt = datetime.fromisoformat(sig.detected_at.replace("Z", "+00:00"))
                    days_old = (now_dt - sig_dt).total_seconds() / 86400.0

                    ttl = self.DEFAULT_INTENT_TTL_DAYS if sig.category == SignalCategory.BUYING_INTENT.value else self.DEFAULT_ACTIVITY_TTL_DAYS
                    if days_old > ttl and sig.type not in obs_by_type:
                        is_expired = True
                        reason = f"Signal '{sig.type}' expired after {int(days_old)} days (TTL is {int(ttl)}d)"
                except Exception:
                    pass

            if is_expired:
                expired.append(sig)
                reasons.append(reason)
            else:
                retained.append(sig)

        return retained, expired, reasons
