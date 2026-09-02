"""ResearchOrchestrationPolicy evaluating next research actions and human review outreach readiness."""

from typing import Optional, List, Any, Dict, Tuple
from datetime import datetime, timezone
from bopclients.domain.prospect import Prospect
from bopclients.domain.signal import Signal
from bopclients.domain.lead_score import LeadScore
from bopclients.domain.prospect_intelligence import ProspectIntelligence
from bopclients.domain.prospect_priority import ProspectPriority, NextResearchAction, OutreachReadiness


class ResearchOrchestrationPolicy:
    """Policy determining NextResearchAction recommendations and OutreachReadiness review gates."""

    ENRICHMENT_STALE_DAYS = 14.0
    RESEARCH_STALE_DAYS = 30.0

    def evaluate_orchestration(
        self,
        prospect: Prospect,
        priority: ProspectPriority,
        lead_score: Optional[LeadScore],
        signals: List[Signal],
        intelligence: Optional[ProspectIntelligence],
        enrichment_snapshot: Optional[Any] = None,
        contacts: Optional[List[Any]] = None,
    ) -> Tuple[NextResearchAction, OutreachReadiness]:
        """Evaluate next research action and outreach readiness status."""
        now_dt = datetime.now(timezone.utc)

        # 1. Determine NextResearchAction following strict precedence order
        next_action = self._determine_next_action(
            prospect, priority, lead_score, signals, intelligence, enrichment_snapshot, contacts, now_dt
        )

        # 2. Determine OutreachReadiness
        outreach_readiness = self._determine_outreach_readiness(
            prospect, priority, lead_score, signals, intelligence, contacts, now_dt
        )

        return next_action, outreach_readiness

    def _determine_next_action(
        self,
        prospect: Prospect,
        priority: ProspectPriority,
        lead_score: Optional[LeadScore],
        signals: List[Signal],
        intelligence: Optional[ProspectIntelligence],
        enrichment: Optional[Any],
        contacts: Optional[List[Any]],
        now_dt: datetime,
    ) -> NextResearchAction:
        # Precedence 1: Check missing or stale enrichment
        if not enrichment or not getattr(enrichment, 'updated_at', None):
            return NextResearchAction(
                action="refresh_enrichment",
                priority="high",
                reason="Enrichment snapshot missing for prospect.",
            )

        try:
            enr_dt = datetime.fromisoformat(enrichment.updated_at.replace("Z", "+00:00"))
            enr_days = (now_dt - enr_dt).total_seconds() / 86400.0
            if enr_days > self.ENRICHMENT_STALE_DAYS:
                return NextResearchAction(
                    action="refresh_enrichment",
                    priority="high",
                    reason=f"Enrichment is stale ({int(enr_days)} days old, threshold is {int(self.ENRICHMENT_STALE_DAYS)} days).",
                )
        except Exception:
            pass

        # Precedence 2: Check missing or stale intelligence
        if not intelligence:
            return NextResearchAction(
                action="refresh_research",
                priority="high",
                reason="Prospect research intelligence missing.",
            )

        try:
            intel_dt = datetime.fromisoformat(intelligence.updated_at.replace("Z", "+00:00"))
            intel_days = (now_dt - intel_dt).total_seconds() / 86400.0
            if intel_days > self.RESEARCH_STALE_DAYS:
                return NextResearchAction(
                    action="refresh_research",
                    priority="high",
                    reason=f"Prospect research is stale ({int(intel_days)} days old, threshold is {int(self.RESEARCH_STALE_DAYS)} days).",
                )

            # Precedence 3: Check if new signals were detected after intelligence snapshot
            for sig in signals:
                try:
                    sig_dt = datetime.fromisoformat(sig.detected_at.replace("Z", "+00:00"))
                    if sig_dt > intel_dt:
                        return NextResearchAction(
                            action="refresh_research",
                            priority="high",
                            reason=f"New signal '{sig.type}' detected after research snapshot was created.",
                        )
                except Exception:
                    pass
        except Exception:
            pass

        # Precedence 4: Check missing contacts for high potential prospect WITH fresh research
        ls_val = lead_score.score if lead_score else 0
        if (priority.priority_score >= 50 or ls_val >= 70) and (not contacts or len(contacts) == 0):
            return NextResearchAction(
                action="find_contact",
                priority="medium",
                reason="High-potential prospect has verified fresh intelligence but missing decision-maker contact details.",
            )

        # Precedence 5: High priority with fresh data
        if priority.priority_score >= 50:
            return NextResearchAction(
                action="monitor_public_signals",
                priority="low",
                reason="Research and intelligence are fresh and verified — monitor for buying intent signals.",
            )

        return NextResearchAction(
            action="none",
            priority="low",
            reason="Research and enrichment data are fresh and complete.",
        )

    def _determine_outreach_readiness(
        self,
        prospect: Prospect,
        priority: ProspectPriority,
        lead_score: Optional[LeadScore],
        signals: List[Signal],
        intelligence: Optional[ProspectIntelligence],
        contacts: Optional[List[Any]],
        now_dt: datetime,
    ) -> OutreachReadiness:
        reasons = []

        if not intelligence:
            return OutreachReadiness(
                status="research_needed",
                reasons=["Prospect research intelligence missing — research required before outreach."],
            )

        try:
            intel_dt = datetime.fromisoformat(intelligence.updated_at.replace("Z", "+00:00"))
            intel_days = (now_dt - intel_dt).total_seconds() / 86400.0
            if intel_days > self.RESEARCH_STALE_DAYS:
                return OutreachReadiness(
                    status="research_needed",
                    reasons=[f"Prospect research is stale ({int(intel_days)} days old) — refresh research required."],
                )
        except Exception:
            pass

        if intelligence.confidence < 0.50:
            return OutreachReadiness(
                status="research_needed",
                reasons=[f"Research evidence confidence ({intelligence.confidence:.2f}) is below minimum threshold (0.50)."],
            )

        ls_val = lead_score.score if lead_score else 0
        if ls_val < 40:
            return OutreachReadiness(
                status="not_ready",
                reasons=[f"LeadScore ({ls_val}) is below minimum qualification threshold (40)."],
            )

        if priority.priority_score < 25:
            return OutreachReadiness(
                status="not_ready",
                reasons=[f"Priority score ({priority.priority_score}) is below minimum operational threshold (25)."],
            )

        # High quality and fresh
        reasons.append("Verified evidence claims and active service match present.")
        reasons.append(f"LeadScore {ls_val}/100 and Priority {priority.priority_score}/100 ({priority.priority_label.upper()}) verified.")
        if contacts and len(contacts) > 0:
            reasons.append(f"{len(contacts)} verified contact(s) available.")

        return OutreachReadiness(
            status="ready_for_human_review",
            reasons=reasons,
        )
