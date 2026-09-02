"""IPriorityScorer interface and RuleBasedPriorityScorer implementation (v1.2 - P6.3 Audit & Trace Aligned)."""

import hashlib
import json
from abc import ABC, abstractmethod
from typing import List, Optional, Any, Dict, Tuple
from datetime import datetime, timezone
from bopclients.domain.prospect import Prospect
from bopclients.domain.signal import Signal
from bopclients.domain.lead_score import LeadScore
from bopclients.domain.prospect_intelligence import ProspectIntelligence
from bopclients.domain.prospect_priority import ProspectPriority, PriorityComponentScore
from bopclients.domain.enums import IntentStrength, SignalCategory


class IPriorityScorer(ABC):
    """Abstract interface for prospect prioritization scoring engines."""

    @abstractmethod
    def calculate_priority(
        self,
        organization_id: str,
        campaign_id: str,
        prospect: Prospect,
        lead_score: Optional[LeadScore],
        signals: List[Signal],
        intelligence: Optional[ProspectIntelligence],
        enrichment_snapshot: Optional[Any] = None,
    ) -> ProspectPriority:
        """Calculate rule-based priority score, label, and component explanations."""
        pass


class RuleBasedPriorityScorer(IPriorityScorer):
    """Deterministic, rule-based priority scorer (v1.2) with full component cap tracing and signal auditability."""

    POLICY_VERSION = "v1.2"

    def calculate_priority(
        self,
        organization_id: str,
        campaign_id: str,
        prospect: Prospect,
        lead_score: Optional[LeadScore],
        signals: List[Signal],
        intelligence: Optional[ProspectIntelligence],
        enrichment_snapshot: Optional[Any] = None,
    ) -> ProspectPriority:
        now_dt = datetime.now(timezone.utc)

        # Deduplicate signals defensively by (type, source) keeping highest confidence/most recent
        deduped_signals = self._deduplicate_signals(signals)

        # 1. Lead Quality Component (0 - 35 pts)
        ls_val = lead_score.score if lead_score else 0
        lead_raw = (ls_val / 100.0) * 35.0
        lead_applied = min(35.0, lead_raw)
        lead_cap_applied = lead_raw > 35.0
        lead_reason = f"LeadScore {ls_val}/100 contributes {lead_applied:.1f}/35 pts (reflects Need signals & ICP fit)"

        # 2. Verified Intent Component (0 - 25 pts)
        intent_raw, intent_applied, intent_cap_applied, has_recent_verified_buying_intent, intent_contribs, intent_reason = self._calculate_verified_intent_component(deduped_signals, now_dt)

        # 3. Company Activity Component (0 - 10 pts)
        activity_raw, activity_applied, activity_cap_applied, activity_contribs, activity_reason = self._calculate_company_activity_component(deduped_signals, now_dt)

        # 4. Research Confidence Component (0 - 15 pts)
        intel_conf = intelligence.confidence if intelligence else 0.0
        conf_raw = intel_conf * 15.0
        conf_applied = min(15.0, conf_raw)
        conf_cap_applied = conf_raw > 15.0
        conf_reason = f"Research confidence {intel_conf:.2f} contributes {conf_applied:.1f}/15 pts"

        # 5. Operational Research Need Component (0 - 15 pts)
        fresh_raw, fresh_applied, fresh_cap_applied, fresh_reason = self._calculate_operational_need_component(intelligence, enrichment_snapshot, deduped_signals, now_dt)

        # Total score calculation (clamped 0 to 100)
        raw_total_score = lead_applied + intent_applied + activity_applied + conf_applied + fresh_applied
        total_score = max(0, min(100, int(round(raw_total_score))))

        # 6. Label Determination & Strict Urgent Gate
        raw_label = self._determine_raw_label(total_score)
        final_label = raw_label
        urgent_capped = False

        if raw_label == "urgent" and not has_recent_verified_buying_intent:
            final_label = "high"
            urgent_capped = True

        reasons: List[Dict[str, Any]] = [
            {"factor": "lead_score", "score": round(lead_applied, 1), "max_possible": 35.0, "reason": lead_reason},
            {"factor": "verified_intent", "score": round(intent_applied, 1), "max_possible": 25.0, "reason": intent_reason},
            {"factor": "company_activity", "score": round(activity_applied, 1), "max_possible": 10.0, "reason": activity_reason},
            {"factor": "research_confidence", "score": round(conf_applied, 1), "max_possible": 15.0, "reason": conf_reason},
            {"factor": "operational_research_need", "score": round(fresh_applied, 1), "max_possible": 15.0, "reason": fresh_reason},
        ]

        if urgent_capped:
            reasons.append({
                "factor": "urgent_gate",
                "score": 0.0,
                "max_possible": 0.0,
                "reason": "Priority score >= 75 but label capped at HIGH because no verified recent STRONG buying-intent signal (e.g. public RFP or vendor search) was present."
            })

        # Compute deterministic component fingerprints
        ls_fp = self._compute_lead_score_fingerprint(lead_score)
        sig_fp = self._compute_signals_fingerprint(deduped_signals)
        intel_fp = self._compute_intelligence_fingerprint(intelligence)
        camp_fp = hashlib.sha256(f"campaign:{campaign_id}".encode("utf-8")).hexdigest()[:16]

        considered_signals = {
            "need": sorted(list(set(s.type for s in deduped_signals if getattr(s, 'category', None) == SignalCategory.NEED.value))),
            "company_activity": sorted(list(set(s.type for s in deduped_signals if getattr(s, 'category', None) == SignalCategory.COMPANY_ACTIVITY.value))),
            "buying_intent": sorted(list(set(s.type for s in deduped_signals if getattr(s, 'category', None) == SignalCategory.BUYING_INTENT.value))),
            "data_quality": sorted(list(set(s.type for s in deduped_signals if getattr(s, 'category', None) == SignalCategory.DATA_QUALITY.value))),
        }

        contributing_signals = {
            "verified_intent": intent_contribs,
            "company_activity": activity_contribs,
        }

        component_breakdown = {
            "lead_score": {"raw_total": round(lead_raw, 2), "applied_total": round(lead_applied, 2), "cap": 35.0, "cap_applied": lead_cap_applied},
            "verified_intent": {"raw_total": round(intent_raw, 2), "applied_total": round(intent_applied, 2), "cap": 25.0, "cap_applied": intent_cap_applied},
            "company_activity": {"raw_total": round(activity_raw, 2), "applied_total": round(activity_applied, 2), "cap": 10.0, "cap_applied": activity_cap_applied},
            "research_confidence": {"raw_total": round(conf_raw, 2), "applied_total": round(conf_applied, 2), "cap": 15.0, "cap_applied": conf_cap_applied},
            "operational_research_need": {"raw_total": round(fresh_raw, 2), "applied_total": round(fresh_applied, 2), "cap": 15.0, "cap_applied": fresh_cap_applied},
        }

        source_fp = hashlib.sha256(f"{ls_fp}:{sig_fp}:{intel_fp}:{camp_fp}".encode("utf-8")).hexdigest()[:16]

        priority_data = {
            "considered_signals": considered_signals,
            "contributing_signals": contributing_signals,
            "component_breakdown": component_breakdown,
            "reasons": reasons,
            "commercial_priority_component": round(lead_applied + intent_applied + activity_applied, 2),
            "research_priority_component": round(conf_applied + fresh_applied, 2),
            "urgent_gate_applied": urgent_capped,
            "has_recent_verified_buying_intent": has_recent_verified_buying_intent,
            "lead_score_fingerprint": ls_fp,
            "active_signals_fingerprint": sig_fp,
            "intelligence_fingerprint": intel_fp,
            "campaign_fingerprint": camp_fp,
            "source_fingerprint": source_fp,
            "evaluated_at": now_dt.isoformat(),
        }

        return ProspectPriority(
            organization_id=organization_id,
            campaign_id=campaign_id,
            prospect_id=prospect.id,
            priority_score=total_score,
            priority_label=final_label,
            lead_score_component=round(lead_applied, 2),
            intent_signal_component=round(intent_applied + activity_applied, 2),
            research_confidence_component=round(conf_applied, 2),
            freshness_component=round(fresh_applied, 2),
            policy_version=self.POLICY_VERSION,
            data=priority_data,
        )

    def _deduplicate_signals(self, signals: List[Signal]) -> List[Signal]:
        seen: Dict[Tuple[str, str], Signal] = {}
        for sig in signals:
            key = (sig.type, sig.source or "default")
            if key not in seen:
                seen[key] = sig
            else:
                existing = seen[key]
                if (sig.confidence or 0) > (existing.confidence or 0):
                    seen[key] = sig
        return list(seen.values())

    def _calculate_verified_intent_component(
        self, signals: List[Signal], now_dt: datetime
    ) -> Tuple[float, float, bool, bool, List[Dict[str, Any]], str]:
        raw_total = 0.0
        has_recent_verified_strong_intent = False
        contrib_details = []
        contrib_dicts = []

        for sig in sorted(signals, key=lambda s: s.type):
            cat = getattr(sig, 'category', None)
            if cat != SignalCategory.BUYING_INTENT.value:
                continue

            try:
                sig_dt = datetime.fromisoformat(sig.detected_at.replace("Z", "+00:00"))
                days_old = max(0.0, (now_dt - sig_dt).total_seconds() / 86400.0)
            except Exception:
                days_old = 0.0

            if days_old <= 7.0:
                recency_weight = 1.0
            elif days_old <= 30.0:
                recency_weight = 0.75
            elif days_old <= 90.0:
                recency_weight = 0.50
            else:
                recency_weight = 0.25

            has_valid_evidence = isinstance(sig.evidence, dict) and len(sig.evidence) > 0 and bool(sig.source)

            stg = getattr(sig, 'intent_strength', IntentStrength.NONE.value)
            if stg == IntentStrength.STRONG.value and has_valid_evidence:
                base_score = 25.0
                if days_old <= 30.0:
                    has_recent_verified_strong_intent = True
            elif stg == IntentStrength.MEDIUM.value and has_valid_evidence:
                base_score = 15.0
            else:
                base_score = 0.0

            conf = sig.confidence if sig.confidence is not None else 1.0
            sig_pts = base_score * recency_weight * conf
            raw_total += sig_pts

            if sig_pts > 0:
                contrib_details.append(f"{sig.type} ({stg}, {int(days_old)}d old, raw {sig_pts:.1f})")
                contrib_dicts.append({
                    "type": sig.type,
                    "category": sig.category,
                    "intent_strength": stg,
                    "confidence": conf,
                    "days_old": int(days_old),
                    "raw_contribution": round(sig_pts, 2),
                })

        applied_total = min(25.0, raw_total)
        cap_applied = raw_total > 25.0

        if contrib_details:
            cap_str = f" (raw {raw_total:.1f}, capped at 25.0)" if cap_applied else ""
            reason_text = f"Verified Buying Intent signals contribute {applied_total:.1f}/25 pts{cap_str}: {', '.join(contrib_details)}"
        else:
            reason_text = "No direct verified buying intent signals (e.g. public RFP or vendor search) detected (0/25 pts)"

        return raw_total, applied_total, cap_applied, has_recent_verified_strong_intent, contrib_dicts, reason_text

    def _calculate_company_activity_component(
        self, signals: List[Signal], now_dt: datetime
    ) -> Tuple[float, float, bool, List[Dict[str, Any]], str]:
        raw_total = 0.0
        contrib_details = []
        contrib_dicts = []

        for sig in sorted(signals, key=lambda s: s.type):
            cat = getattr(sig, 'category', None)
            if cat != SignalCategory.COMPANY_ACTIVITY.value:
                continue

            try:
                sig_dt = datetime.fromisoformat(sig.detected_at.replace("Z", "+00:00"))
                days_old = max(0.0, (now_dt - sig_dt).total_seconds() / 86400.0)
            except Exception:
                days_old = 0.0

            if days_old <= 7.0:
                recency_weight = 1.0
            elif days_old <= 30.0:
                recency_weight = 0.75
            elif days_old <= 90.0:
                recency_weight = 0.50
            else:
                recency_weight = 0.25

            stg = getattr(sig, 'intent_strength', IntentStrength.NONE.value)
            if stg == IntentStrength.MEDIUM.value:
                base_score = 5.0
            elif stg == IntentStrength.WEAK.value:
                base_score = 3.0
            else:
                base_score = 1.0

            conf = sig.confidence if sig.confidence is not None else 1.0
            sig_pts = base_score * recency_weight * conf
            raw_total += sig_pts

            if sig_pts > 0:
                contrib_details.append(f"{sig.type} ({int(days_old)}d old, raw {sig_pts:.1f})")
                contrib_dicts.append({
                    "type": sig.type,
                    "category": sig.category,
                    "intent_strength": stg,
                    "confidence": conf,
                    "days_old": int(days_old),
                    "raw_contribution": round(sig_pts, 2),
                })

        applied_total = min(10.0, raw_total)
        cap_applied = raw_total > 10.0

        if contrib_details:
            cap_str = f" (raw {raw_total:.1f}, capped at 10.0)" if cap_applied else ""
            reason_text = f"Company Activity signals contribute {applied_total:.1f}/10 pts{cap_str}: {', '.join(contrib_details)}"
        else:
            reason_text = "No active company activity signals detected (0/10 pts)"

        return raw_total, applied_total, cap_applied, contrib_dicts, reason_text

    def _calculate_operational_need_component(
        self,
        intelligence: Optional[ProspectIntelligence],
        enrichment: Optional[Any],
        signals: List[Signal],
        now_dt: datetime,
    ) -> Tuple[float, float, bool, str]:
        raw_pts = 0.0
        reasons = []

        if not intelligence:
            raw_pts += 15.0
            reasons.append("Missing prospect research (+15 operational research urgency)")
        else:
            try:
                intel_dt = datetime.fromisoformat(intelligence.updated_at.replace("Z", "+00:00"))
                days_old = (now_dt - intel_dt).total_seconds() / 86400.0
                if days_old > 30.0:
                    raw_pts += 10.0
                    reasons.append(f"Research is stale ({int(days_old)}d old, +10 operational research urgency)")
            except Exception:
                pass

        if enrichment and getattr(enrichment, 'updated_at', None):
            try:
                enr_dt = datetime.fromisoformat(enrichment.updated_at.replace("Z", "+00:00"))
                days_old = (now_dt - enr_dt).total_seconds() / 86400.0
                if days_old > 14.0:
                    raw_pts += 5.0
                    reasons.append(f"Enrichment is stale ({int(days_old)}d old, +5 operational research urgency)")
            except Exception:
                pass

        applied_pts = min(15.0, raw_pts)
        cap_applied = raw_pts > 15.0
        reason_text = "; ".join(reasons) if reasons else "Intelligence & enrichment data are fresh (0/15 operational research need)"
        return raw_pts, applied_pts, cap_applied, reason_text

    def _determine_raw_label(self, score: int) -> str:
        if score >= 75:
            return "urgent"
        elif score >= 50:
            return "high"
        elif score >= 25:
            return "medium"
        return "low"

    def _compute_lead_score_fingerprint(self, lead_score: Optional[LeadScore]) -> str:
        if not lead_score:
            return "none"
        raw = f"score:{lead_score.score}:version:{lead_score.scoring_version}:explanation:{lead_score.explanation or ''}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _compute_signals_fingerprint(self, signals: List[Signal]) -> str:
        if not signals:
            return "none"
        items = []
        for s in sorted(signals, key=lambda x: (x.type, x.detected_at)):
            items.append(f"{s.type}:{s.category}:{s.intent_strength}:{s.confidence}:{s.value}:{s.detected_at}:{s.source}")
        return hashlib.sha256(";".join(items).encode("utf-8")).hexdigest()[:16]

    def _compute_intelligence_fingerprint(self, intel: Optional[ProspectIntelligence]) -> str:
        if not intel:
            return "none"
        raw = f"provider:{intel.provider}:version:{intel.research_version}:confidence:{intel.confidence}:updated:{intel.updated_at}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
