"""Hallucination safeguards and policy validation for sales research drafts."""

from typing import List, Tuple, Optional
from bopclients.domain.contact import Contact
from bopclients.application.research_dto import ProspectResearchDraft, ResearchClaim


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
        self, draft: ProspectResearchDraft, verified_contacts: Optional[List[Contact]] = None
    ) -> Tuple[ProspectResearchDraft, List[str], List[ResearchClaim]]:
        """Validate research draft, rejecting unevidenced observed claims and unverified factual assertions."""
        warnings: List[str] = []
        valid_claims: List[ResearchClaim] = []
        rejected_claims: List[ResearchClaim] = []

        verified_names = {c.name.lower() for c in (verified_contacts or []) if c.name}

        for claim in draft.claims:
            lower_stmt = claim.statement.lower()

            # Rule 1: Observed claim MUST have evidence references, otherwise REJECT!
            if claim.classification == "observed" and not claim.evidence_refs:
                warnings.append(
                    f"REJECTED_UNSUPPORTED_OBSERVED_CLAIM: Claim '{claim.statement}' rejected due to missing evidence_refs"
                )
                rejected_claims.append(claim)
                continue

            # Rule 2: Reject unevidenced external factual assertions (revenue, employee count, purchase intent)
            has_factual_term = any(term in lower_stmt for term in self.UNSUPPORTED_FACTUAL_TERMS)
            if has_factual_term and not claim.evidence_refs:
                warnings.append(
                    f"REJECTED_UNSUPPORTED_FACTUAL_CLAIM: Factual assertion '{claim.statement}' rejected without supporting evidence"
                )
                rejected_claims.append(claim)
                continue

            # Rule 3: Reject unverified contact name/title claims
            if "director" in lower_stmt or "manager" in lower_stmt or "vp" in lower_stmt or "ceo" in lower_stmt:
                # If statement claims a specific person name not present in verified contacts
                if not claim.evidence_refs and verified_names:
                    if not any(name in lower_stmt for name in verified_names):
                        warnings.append(
                            f"REJECTED_UNVERIFIED_CONTACT_CLAIM: Contact assertion '{claim.statement}' rejected without matching contact data"
                        )
                        rejected_claims.append(claim)
                        continue

            # Rule 4: Enforce confidence bounds
            claim.confidence = max(0.0, min(1.0, claim.confidence))
            valid_claims.append(claim)

        draft.claims = valid_claims
        draft.overall_confidence = max(0.0, min(1.0, draft.overall_confidence))

        # Determine confidence label
        if draft.overall_confidence >= 0.75:
            draft.confidence_label = "high"
        elif draft.overall_confidence >= 0.45:
            draft.confidence_label = "medium"
        else:
            draft.confidence_label = "low"

        return draft, warnings, rejected_claims
