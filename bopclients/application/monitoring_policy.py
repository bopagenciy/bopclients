"""MonitoringPolicy and MonitoringBackoffPolicy for continuous prospect monitoring cadence."""

import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from bopclients.domain.prospect import Prospect
from bopclients.domain.prospect_priority import ProspectPriority
from bopclients.application.monitoring_dto import MonitoringPlanDecision


class MonitoringPolicy:
    """Deterministic policy calculating monitoring cadence, operations, and source fingerprints."""

    POLICY_VERSION = "v1.0"

    # Base cadence by priority label
    BASE_CADENCE_DAYS = {
        "URGENT": 3,
        "HIGH": 7,
        "MEDIUM": 14,
        "LOW": 30,
    }

    @classmethod
    def evaluate(
        cls,
        prospect: Prospect,
        priority: Optional[ProspectPriority] = None,
        active_signals: Optional[List[Any]] = None,
        available_providers: Optional[List[str]] = None,
        provider_capabilities: Optional[Dict[str, Any]] = None,
        now_dt: Optional[datetime] = None,
    ) -> MonitoringPlanDecision:
        """Evaluate prospect state and return deterministic MonitoringPlanDecision."""
        now = now_dt or datetime.now(timezone.utc)
        reasons = []

        # 1. Base cadence from priority label
        p_label = (priority.priority_label if priority else "MEDIUM").upper()
        base_days = cls.BASE_CADENCE_DAYS.get(p_label, 14)
        reasons.append(f"Priority {p_label} => {base_days}-day base cadence")

        interval_days = base_days
        signals = active_signals or []

        # 2. Check active verified buying intent / RFP due date
        has_active_rfp = False
        rfp_due_days: Optional[int] = None

        for sig in signals:
            sig_type = getattr(sig, "signal_type", "") if not isinstance(sig, dict) else sig.get("signal_type", "")
            ev = getattr(sig, "evidence", {}) if not isinstance(sig, dict) else sig.get("evidence", {})
            if isinstance(ev, dict) and ev.get("currentness") == "active":
                has_active_rfp = True
                due_str = ev.get("due_date")
                if due_str:
                    try:
                        due_dt = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
                        delta = (due_dt - now).days
                        if rfp_due_days is None or delta < rfp_due_days:
                            rfp_due_days = delta
                    except Exception:
                        pass

        if has_active_rfp:
            if rfp_due_days is not None and 0 <= rfp_due_days <= 7:
                interval_days = min(interval_days, 2)
                reasons.append(f"Active RFP due in {rfp_due_days} days => cadence reduced to 2 days")
            else:
                interval_days = min(interval_days, 3)
                reasons.append("Active strong buying intent detected => cadence reduced to 3 days")

        # Floor interval at 1 day
        interval_days = max(1, interval_days)

        # 3. Determine operations (executable vs recommended)
        executable_ops = ["monitor_public_signals"]
        recommended_ops = []

        # Check enrichment freshness
        has_enrichment = bool(getattr(prospect, "forge_record_id", None))
        if not has_enrichment:
            recommended_ops.append("refresh_enrichment")
            reasons.append("Missing enrichment link => recommended refresh_enrichment")

        recommended_ops.append("refresh_research")
        recommended_ops.append("find_contact")

        all_ops = executable_ops + recommended_ops

        # Provider selection
        prov_names = available_providers or ["official_website", "government_procurement", "public_news"]

        # 4. Compute next_check_at
        next_check_dt = now + timedelta(days=interval_days)
        next_check_iso = next_check_dt.isoformat()

        # 5. Compute comprehensive source fingerprint
        src_fingerprint = cls.compute_source_fingerprint(
            prospect=prospect,
            priority=priority,
            active_signals=signals,
            available_providers=prov_names,
            provider_capabilities=provider_capabilities,
        )

        return MonitoringPlanDecision(
            recommended_interval_days=interval_days,
            next_check_at=next_check_iso,
            provider_names=prov_names,
            operations=all_ops,
            executable_operations=executable_ops,
            recommended_operations=recommended_ops,
            reasons=reasons,
            policy_version=cls.POLICY_VERSION,
            source_fingerprint=src_fingerprint,
        )

    @classmethod
    def compute_source_fingerprint(
        cls,
        prospect: Prospect,
        priority: Optional[ProspectPriority] = None,
        active_signals: Optional[List[Any]] = None,
        available_providers: Optional[List[str]] = None,
        provider_capabilities: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Compute comprehensive source fingerprint for schedule invalidation / recalculation tracking."""
        # 1. Priority fingerprint
        p_label = priority.priority_label if priority else "MEDIUM"
        p_score = priority.priority_score if priority else 0
        p_src_fp = priority.data.get("source_fingerprint", "none") if (priority and isinstance(priority.data, dict)) else "none"
        prio_part = f"{p_label}:{p_score}:{p_src_fp}"

        # 2. Active signals fingerprint (deterministic sorted composition)
        sig_items = []
        for s in (active_signals or []):
            st = getattr(s, "signal_type", "") if not isinstance(s, dict) else s.get("signal_type", "")
            cat = getattr(s, "category", "") if not isinstance(s, dict) else s.get("category", "")
            stren = getattr(s, "intent_strength", "") if not isinstance(s, dict) else s.get("intent_strength", "")
            conf = getattr(s, "confidence", 1.0) if not isinstance(s, dict) else s.get("confidence", 1.0)
            ev = getattr(s, "evidence", {}) if not isinstance(s, dict) else s.get("evidence", {})
            event_key = ""
            if hasattr(s, "compute_semantic_event_key"):
                event_key = s.compute_semantic_event_key()
            elif isinstance(ev, dict):
                event_key = ev.get("semantic_event_key", "")
            sig_items.append(f"{st}:{cat}:{stren}:{conf:.2f}:{event_key}")

        sig_items.sort()
        signals_part = "|".join(sig_items)

        # 3. Provider availability & configured status fingerprint
        prov_part = ",".join(sorted(available_providers or []))
        caps_part = ""
        if provider_capabilities:
            caps_items = [f"{k}:{v}" for k, v in sorted(provider_capabilities.items())]
            caps_part = "|".join(caps_items)

        raw = f"{cls.POLICY_VERSION}:{prospect.id}:{prio_part}:{signals_part}:{prov_part}:{caps_part}:{prospect.updated_at}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class MonitoringBackoffPolicy:
    """Exponential backoff policy for monitoring execution retries."""

    @classmethod
    def compute_backoff_next_check(cls, failure_count: int, now_dt: Optional[datetime] = None) -> str:
        """Calculate next_check_at timestamp using backoff progression."""
        now = now_dt or datetime.now(timezone.utc)
        if failure_count <= 1:
            delay_minutes = 60  # +1 hour
        elif failure_count == 2:
            delay_minutes = 240  # +4 hours
        elif failure_count == 3:
            delay_minutes = 720  # +12 hours
        else:
            delay_minutes = 1440  # +24 hours

        next_dt = now + timedelta(minutes=delay_minutes)
        return next_dt.isoformat()
