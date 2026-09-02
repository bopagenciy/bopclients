"""Hallucination safeguards and policy validation for sales research drafts."""

from typing import List, Tuple, Optional, Dict, Any, Set
from bopclients.domain.contact import Contact
from bopclients.application.research_dto import ProspectResearchDraft, ResearchClaim, CommercialOpportunity


class ResearchValidationError(Exception):
    """Raised when a research draft violates evidence-first or anti-hallucination policy."""
    pass


class ResearchValidationPolicy:
    """Validates research drafts to enforce evidence-first rules and prevent AI hallucinations."""

    UNSUPPORTED_FACTUAL_TERMS = {
        "revenue", "annual sales", "employee count", "headcount",
        "actively seeking", "looking to buy", "evaluating vendors",
        "budget", "contract value"
    }

    def validate(
        self,
        draft: ProspectResearchDraft,
        verified_contacts: Optional[List[Contact]] = None,
        allowed_evidence_refs: Optional[List[str]] = None,
        allowed_source_refs: Optional[List[str]] = None,
        allowed_service_ids: Optional[List[str]] = None,
        signal_confidence_map: Optional[Dict[str, float]] = None,
    ) -> Tuple[ProspectResearchDraft, List[str], List[ResearchClaim]]:
        """Validate research draft, enforcing allowed references, anti-hallucination, and confidence caps."""
        warnings: List[str] = []
        valid_claims: List[ResearchClaim] = []
        rejected_claims: List[ResearchClaim] = []

        verified_names = {c.name.lower() for c in (verified_contacts or []) if c.name}
        allowed_ev_set = set(allowed_evidence_refs) if allowed_evidence_refs is not None else None
        allowed_src_set = set(allowed_source_refs) if allowed_source_refs is not None else None
        allowed_svc_set = set(allowed_service_ids) if allowed_service_ids is not None else None
        sig_map = signal_confidence_map or {}

        # 1. Validate Claims
        for claim in draft.claims:
            lower_stmt = claim.statement.lower()

            # Rule 1: Observed claim MUST have evidence references, otherwise REJECT!
            if claim.classification == "observed" and not claim.evidence_refs:
                warnings.append(
                    f"REJECTED_UNSUPPORTED_OBSERVED_CLAIM: Claim '{claim.statement}' rejected due to missing evidence_refs"
                )
                rejected_claims.append(claim)
                continue

            # Rule 2: Allowed evidence references check
            if allowed_ev_set is not None and claim.evidence_refs:
                unknown_ev = [ref for ref in claim.evidence_refs if ref not in allowed_ev_set]
                if unknown_ev:
                    warnings.append(
                        f"UNKNOWN_EVIDENCE_REFERENCE: Claim '{claim.statement}' contains invalid evidence refs: {unknown_ev}"
                    )
                    rejected_claims.append(claim)
                    continue

            # Rule 3: Allowed source references check
            if allowed_src_set is not None and claim.source_refs:
                unknown_src = [ref for ref in claim.source_refs if ref not in allowed_src_set]
                if unknown_src:
                    warnings.append(
                        f"UNKNOWN_SOURCE_REFERENCE: Claim '{claim.statement}' contains invalid source refs: {unknown_src}"
                    )
                    rejected_claims.append(claim)
                    continue

            # Rule 4: Reject unevidenced external factual assertions (revenue, employee count, purchase intent)
            has_factual_term = any(term in lower_stmt for term in self.UNSUPPORTED_FACTUAL_TERMS)
            if has_factual_term and not claim.evidence_refs:
                warnings.append(
                    f"REJECTED_UNSUPPORTED_FACTUAL_CLAIM: Factual assertion '{claim.statement}' rejected without supporting evidence"
                )
                rejected_claims.append(claim)
                continue

            # Rule 5: Reject unverified contact name/title claims
            if "director" in lower_stmt or "manager" in lower_stmt or "vp" in lower_stmt or "ceo" in lower_stmt:
                if not claim.evidence_refs and not claim.source_refs:
                    if not verified_names or not any(name in lower_stmt for name in verified_names):
                        warnings.append(
                            f"REJECTED_UNVERIFIED_CONTACT_CLAIM: Contact assertion '{claim.statement}' rejected without matching contact data"
                        )
                        rejected_claims.append(claim)
                        continue

            # Rule 6: Confidence Normalization & Capping (AI confidence is not authoritative)
            if claim.classification == "inferred":
                claim.confidence = min(claim.confidence, 0.40)
            elif claim.classification == "derived":
                claim.confidence = min(claim.confidence, 0.85)
            elif claim.classification == "observed" and claim.evidence_refs:
                ev_confs = [sig_map.get(ref, 1.0) for ref in claim.evidence_refs]
                max_ev_conf = max(ev_confs) if ev_confs else 1.0
                claim.confidence = min(claim.confidence, max_ev_conf)

            claim.confidence = max(0.0, min(1.0, claim.confidence))
            valid_claims.append(claim)

        draft.claims = valid_claims
        valid_claim_ids = {c.id for c in valid_claims}

        # 2. Validate Commercial Opportunities
        valid_opportunities: List[CommercialOpportunity] = []
        for opp in draft.commercial_opportunities:
            # Check for non-empty supporting evidence/claims
            has_valid_signals = bool(opp.supporting_signals)
            has_valid_claims = any(cid in valid_claim_ids for cid in opp.supporting_claims)

            if not (has_valid_signals or has_valid_claims):
                warnings.append(
                    f"REJECTED_UNSUPPORTED_COMMERCIAL_OPPORTUNITY: Opportunity '{opp.title}' rejected due to missing valid supporting evidence"
                )
                continue

            # Validate matched services against allowed service IDs/names
            if allowed_svc_set is not None and opp.matched_services:
                filtered_services = [s for s in opp.matched_services if s in allowed_svc_set]
                if len(filtered_services) != len(opp.matched_services):
                    rejected_svcs = [s for s in opp.matched_services if s not in allowed_svc_set]
                    warnings.append(
                        f"UNAVAILABLE_SERVICE_REFERENCE: Opportunity '{opp.title}' referenced unavailable services: {rejected_svcs}"
                    )
                opp.matched_services = filtered_services

            # Priority and confidence bounds
            opp.priority = opp.priority.lower() if opp.priority in ("low", "medium", "high") else "medium"
            opp.confidence = max(0.0, min(1.0, opp.confidence))
            valid_opportunities.append(opp)

        draft.commercial_opportunities = valid_opportunities
        draft.overall_confidence = max(0.0, min(1.0, draft.overall_confidence))

        # Determine confidence label
        if draft.overall_confidence >= 0.75:
            draft.confidence_label = "high"
        elif draft.overall_confidence >= 0.45:
            draft.confidence_label = "medium"
        else:
            draft.confidence_label = "low"

        return draft, warnings, rejected_claims
