"""Deterministic sales research provider generating evidence-first prospect intelligence."""

import uuid
from typing import List, Dict, Any
from bopclients.domain.prospect import Prospect
from bopclients.application.research_dto import (
    ProspectResearchContext,
    ProspectResearchDraft,
    ResearchClaim,
    CommercialOpportunity,
)
from bopclients.application.interfaces.research_interfaces import IProspectResearchProvider


class DeterministicResearchProvider(IProspectResearchProvider):
    """Deterministic research provider converting observed signals, snapshot, and ICP match into evidence-backed research."""

    @property
    def name(self) -> str:
        return "deterministic"

    def research(self, context: ProspectResearchContext) -> ProspectResearchDraft:
        p = context.prospect
        snap = context.enrichment_snapshot
        signals = context.signals
        services = context.services
        icp = context.icp

        claims: List[ResearchClaim] = []
        opportunities: List[CommercialOpportunity] = []
        risks: List[str] = []
        unknowns: List[str] = []

        # 1. Business Profile (Only verified observed fields)
        profile: Dict[str, Any] = {
            "name": p.name,
            "industry": p.industry or "Unknown",
            "country": p.country or "Unknown",
            "city": p.city,
            "website_url": p.website_url,
            "phone": p.phone,
            "email": p.email,
            "technologies": snap.technologies if snap else [],
            "cms": snap.cms if snap else None,
        }

        # 2. Process Observed Signals into Claims
        sig_types = {sig.type: sig for sig in signals}
        for sig in signals:
            claim_id = f"claim:{sig.type}:{uuid.uuid4().hex[:6]}"
            stmt = f"Observed signal: {sig.value or sig.type}"
            if sig.type == "website_slow" and sig.value:
                stmt = f"Website response time was measured at approximately {sig.value}."
            elif sig.type == "no_chatbot":
                stmt = "No AI chatbot widget was detected during website inspection."
            elif sig.type == "no_booking":
                stmt = "No online booking functionality was detected during website inspection."
            elif sig.type == "no_ssl":
                stmt = "No valid SSL certificate marker was detected during website inspection."
            elif sig.type == "no_analytics":
                stmt = "No analytics tracking scripts were detected during website inspection."

            claims.append(
                ResearchClaim(
                    id=claim_id,
                    claim_type=sig.type,
                    statement=stmt,
                    classification="observed",
                    confidence=sig.confidence,
                    evidence_refs=[f"signal:{sig.type}"],
                    source_refs=[f"provider:{sig.source}"],
                )
            )

        # 3. Process Derived Opportunities
        # Map sellable services
        sellable_cats = {(s.category or s.name).lower().replace(" ", "_"): s for s in services}
        
        if "no_chatbot" in sig_types or "no_booking" in sig_types:
            matching = []
            if "automation" in sellable_cats:
                matching.append(sellable_cats["automation"].name)
            if "ai_solutions" in sellable_cats:
                matching.append(sellable_cats["ai_solutions"].name)
            if matching:
                opp_id = f"opp:auto:{uuid.uuid4().hex[:6]}"
                opportunities.append(
                    CommercialOpportunity(
                        opportunity_type="contact_and_booking_automation",
                        title="Conversational & Booking Automation",
                        description="Opportunity to implement automated booking and AI chat interface to capture leads.",
                        confidence=0.85,
                        supporting_signals=[s for s in ("no_chatbot", "no_booking") if s in sig_types],
                        supporting_claims=[c.id for c in claims if c.claim_type in ("no_chatbot", "no_booking")],
                        matched_services=matching,
                        priority="high" if len(matching) > 1 else "medium",
                    )
                )
                claims.append(
                    ResearchClaim(
                        id=f"claim:derived:auto:{uuid.uuid4().hex[:6]}",
                        claim_type="opportunity_derived",
                        statement="Contact and booking automation is commercially relevant based on missing markers.",
                        classification="derived",
                        confidence=0.80,
                        evidence_refs=[f"signal:{s}" for s in ("no_chatbot", "no_booking") if s in sig_types],
                    )
                )

        if "website_slow" in sig_types or "no_ssl" in sig_types:
            matching = []
            if "web_development" in sellable_cats:
                matching.append(sellable_cats["web_development"].name)
            if matching:
                opportunities.append(
                    CommercialOpportunity(
                        opportunity_type="website_modernization",
                        title="Web Performance & Redesign",
                        description="Opportunity to optimize website speed, security, and mobile layout.",
                        confidence=0.80,
                        supporting_signals=[s for s in ("website_slow", "no_ssl") if s in sig_types],
                        supporting_claims=[c.id for c in claims if c.claim_type in ("website_slow", "no_ssl")],
                        matched_services=matching,
                        priority="high" if "website_slow" in sig_types else "medium",
                    )
                )

        if "no_analytics" in sig_types:
            matching = []
            if "marketing" in sellable_cats:
                matching.append(sellable_cats["marketing"].name)
            if matching:
                opportunities.append(
                    CommercialOpportunity(
                        opportunity_type="analytics_setup",
                        title="Digital Marketing & Analytics Setup",
                        description="Opportunity to implement analytics tracking and conversion optimization.",
                        confidence=0.75,
                        supporting_signals=["no_analytics"],
                        supporting_claims=[c.id for c in claims if c.claim_type == "no_analytics"],
                        matched_services=matching,
                        priority="medium",
                    )
                )

        # 4. Assess Risks & Unknowns
        if not snap or snap.scrape_status in ("timeout", "partial_timeout", "forbidden", "dns_failure"):
            risks.append(f"Technical inspection incomplete or timed out (scrape_status: {snap.scrape_status if snap else 'none'})")
        if not p.email and not (snap and snap.emails):
            risks.append("No verified public email address available for direct outreach")

        unknowns.extend([
            "Decision maker contact identity unknown",
            "Annual marketing budget unknown",
            "Employee headcount unknown",
            "Current agency or vendor relationship unknown",
        ])

        # 5. Overall Confidence Calculation
        if snap and snap.scrape_status == "success" and signals:
            overall_conf = 0.85
        elif snap and snap.scrape_status in ("success", "partial_timeout"):
            overall_conf = 0.65
        else:
            overall_conf = 0.40

        # Executive Summary
        if opportunities:
            summary = f"{p.name} presents {len(opportunities)} commercial opportunity area(s) based on observed website and technology signals."
        else:
            summary = f"{p.name} was analyzed. Limited or no active commercial opportunity signals were identified."

        return ProspectResearchDraft(
            executive_summary=summary,
            business_profile=profile,
            claims=claims,
            commercial_opportunities=opportunities,
            recommended_services=[],  # Will be populated from context
            risks=risks,
            unknowns=unknowns,
            overall_confidence=overall_conf,
        )
