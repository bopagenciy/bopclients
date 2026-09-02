"""Rule-based Opportunity Scorer calculating LeadScore and Service Recommendations."""

from typing import List, Optional, Tuple, Dict, Set
from bopclients.domain.prospect import Prospect
from bopclients.domain.service import Service
from bopclients.domain.icp import IdealCustomerProfile
from bopclients.domain.signal import Signal
from bopclients.application.enrichment_dto import ServiceRecommendation
from bopclients.application.interfaces.enrichment_interfaces import IOpportunityScorer


class RuleBasedOpportunityScorer(IOpportunityScorer):
    """Deterministic v1.1 confidence-weighted opportunity scorer mapping signals to commercial service relevance."""

    VERSION = "v1.1"

    # Signal to service category mapping & weight rules
    SIGNAL_WEIGHTS = {
        "no_website": {
            "web_development": 25,
            "digital_presence": 25,
            "base_weight": 25,
            "name": "No website URL provided",
        },
        "website_unreachable": {
            "web_development": 20,
            "digital_presence": 20,
            "base_weight": 20,
            "name": "Confirmed website unreachable",
        },
        "website_slow": {
            "web_development": 15,
            "digital_presence": 15,
            "base_weight": 15,
            "name": "Slow website latency",
        },
        "no_ssl": {
            "web_development": 10,
            "base_weight": 10,
            "name": "Unencrypted HTTP / Missing SSL",
        },
        "no_chatbot": {
            "ai_solutions": 20,
            "automation": 15,
            "base_weight": 15,
            "name": "No AI chatbot or live chat",
        },
        "no_booking": {
            "automation": 20,
            "web_development": 15,
            "base_weight": 15,
            "name": "No online booking/scheduling system",
        },
        "no_analytics": {
            "marketing": 15,
            "digital_presence": 10,
            "base_weight": 10,
            "name": "No analytics tracking",
        },
    }

    def score(
        self,
        org_id: str,
        prospect: Prospect,
        signals: List[Signal],
        services: List[Service],
        icp: Optional[IdealCustomerProfile] = None,
    ) -> Tuple[int, str, List[ServiceRecommendation]]:
        accumulated = 0
        reasons: List[str] = []

        # Map available organization services by category / code (WHO WE ARE / WHAT WE SELL)
        sellable_services: Dict[str, Service] = {}
        for s in services:
            key = (s.category or s.name).lower().replace(" ", "_")
            sellable_services[key] = s
            # Map common category synonyms
            if any(k in key for k in ("web", "diseño", "desarrollo", "site")):
                sellable_services["web_development"] = s
                sellable_services["digital_presence"] = s
            if any(k in key for k in ("auto", "bot", "flujo", "process")):
                sellable_services["automation"] = s
            if any(k in key for k in ("ia", "ai", "chat")):
                sellable_services["ai_solutions"] = s
            if any(k in key for k in ("mark", "seo", "ads", "growth")):
                sellable_services["marketing"] = s

        service_relevance: Dict[str, Tuple[int, List[str]]] = {}

        # 1. Process signals with confidence weighting
        for sig in signals:
            rule = self.SIGNAL_WEIGHTS.get(sig.type)
            if not rule:
                continue

            base_w = rule["base_weight"]
            contrib = int(round(base_w * sig.confidence))
            accumulated += contrib
            reasons.append(f"{rule['name']} (+{contrib}, conf={sig.confidence:.1f})")

            # Accumulate service relevance scores
            for srv_key, bonus in rule.items():
                if srv_key in ("base_weight", "name"):
                    continue

                curr_score, curr_sigs = service_relevance.get(srv_key, (50, []))
                srv_contrib = int(round(bonus * sig.confidence))
                new_score = min(100, curr_score + srv_contrib)
                curr_sigs.append(sig.type)
                service_relevance[srv_key] = (new_score, curr_sigs)

        # 2. Process ICP Match
        if icp:
            if icp.industries and prospect.industry:
                if any(ind.lower() in prospect.industry.lower() for ind in icp.industries):
                    accumulated += 15
                    reasons.append("Matches ICP target industry (+15)")
            if icp.countries and prospect.country:
                if prospect.country in icp.countries:
                    accumulated += 5
                    reasons.append("Matches ICP target country (+5)")

        final_score = max(0, min(100, accumulated))

        # 3. Filter recommendations to ONLY services the organization sells!
        recommendations: List[ServiceRecommendation] = []
        for srv_key, (rel_score, rel_sigs) in service_relevance.items():
            matching_service = sellable_services.get(srv_key)
            if not matching_service:
                # SKIP service recommendation if organization DOES NOT SELL it!
                continue

            if any(r.service_id == matching_service.id for r in recommendations):
                continue

            explanation_str = f"Relevant for {matching_service.name} based on signals: {', '.join(rel_sigs)}"
            recommendations.append(
                ServiceRecommendation(
                    service_id=matching_service.id,
                    service_name=matching_service.name,
                    relevance_score=rel_score,
                    reasoning=explanation_str,
                    supporting_signals=rel_sigs,
                )
            )

        recommendations.sort(key=lambda r: r.relevance_score, reverse=True)

        if not reasons:
            reasons.append("No active opportunity signals or ICP match detected (0)")

        explanation_text = f"Opportunity Score {final_score}/100. Factors: " + "; ".join(reasons)
        return final_score, explanation_text, recommendations
