"""GovernmentProcurementProvider implementing IPublicSignalProvider for public solicitation discovery (SAM.gov Opportunities v2 Aligned)."""

import os
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple
from bopclients.domain.prospect import Prospect
from bopclients.domain.signal_observation import PublicSignalObservation
from bopclients.domain.enums import SignalType, SignalCategory, IntentStrength
from bopclients.application.signal_provider import IPublicSignalProvider
from bopclients.application.signal_monitor_dto import (
    PublicSignalProviderCapabilities,
    PublicSignalDiscoveryResult,
    ProviderValidationLevel,
    ProviderThrottleFeedback,
)
from bopclients.infrastructure.security.network_validator import NetworkSafetyValidator


@dataclass
class MatchResult:
    """Detailed result of issuer matching policy."""

    status: str  # "MATCHED", "AMBIGUOUS", "REJECTED"
    match_confidence: float
    match_method: str
    reason: str


class ProspectSourceMatch:
    """Validator evaluating if a solicitation/opportunity issuer matches a target prospect with strict governance."""

    @classmethod
    def match_issuer(cls, prospect: Prospect, issuer_name: str, issuer_url: Optional[str] = None, prospect_role: str = "issuer") -> MatchResult:
        """Evaluate if prospect is the ISSUER/BUYER of a public solicitation with strict match rules."""
        if prospect_role and prospect_role.lower() != "issuer":
            return MatchResult(
                status="REJECTED",
                match_confidence=0.0,
                match_method="role_check",
                reason=f"Prospect role is '{prospect_role}', not issuer/buyer",
            )

        if not issuer_name or not isinstance(issuer_name, str):
            return MatchResult(
                status="REJECTED",
                match_confidence=0.0,
                match_method="missing_issuer",
                reason="Missing issuer name",
            )

        p_name_norm = prospect.name.strip().lower()
        i_name_norm = issuer_name.strip().lower()

        # 1. Exact canonical organization name match
        if p_name_norm == i_name_norm:
            return MatchResult(
                status="MATCHED",
                match_confidence=1.0,
                match_method="exact_canonical_name",
                reason=f"Exact canonical name match '{prospect.name}' == '{issuer_name}'",
            )

        # 2. Verified domain host match
        if prospect.website_url and issuer_url:
            p_host = urllib.parse.urlparse(prospect.website_url).netloc.lower().split(":")[0].replace("www.", "")
            i_host = urllib.parse.urlparse(issuer_url).netloc.lower().split(":")[0].replace("www.", "")
            if p_host and p_host == i_host:
                return MatchResult(
                    status="MATCHED",
                    match_confidence=1.0,
                    match_method="domain_match",
                    reason=f"Verified domain match '{p_host}'",
                )

        # 3. Partial/Ambiguous substring match (e.g. "General Health" ~ "Department of Health") -> AMBIGUOUS
        if p_name_norm in i_name_norm or i_name_norm in p_name_norm:
            return MatchResult(
                status="AMBIGUOUS",
                match_confidence=0.50,
                match_method="partial_ambiguous_name",
                reason=f"Partial/ambiguous name overlap '{prospect.name}' ~ '{issuer_name}' (cannot activate strong intent alone)",
            )

        return MatchResult(
            status="REJECTED",
            match_confidence=0.0,
            match_method="no_match",
            reason=f"Issuer '{issuer_name}' does not match prospect '{prospect.name}'",
        )


class GovernmentProcurementProvider(IPublicSignalProvider):
    """Specialized provider for public government procurement RFP opportunities (SAM.gov Opportunities Public API v2 Aligned)."""

    SAM_OPPORTUNITIES_V2_ENDPOINT = "https://api.sam.gov/opportunities/v2/search"

    def __init__(self, api_key: Optional[str] = None, client: Optional[Any] = None):
        self.api_key = (api_key or os.environ.get("SAM_GOV_API_KEY", "")).strip()
        self.client = client

    @property
    def provider_name(self) -> str:
        return "government_procurement"

    @property
    def capabilities(self) -> PublicSignalProviderCapabilities:
        is_configured = bool(self.api_key or self.client)
        val_level = (
            ProviderValidationLevel.FIXTURE_VALIDATED.value
            if self.client
            else (ProviderValidationLevel.LIVE_VALIDATED.value if is_configured else ProviderValidationLevel.SKIPPED_NO_KEY.value)
        )
        return PublicSignalProviderCapabilities(
            supports_rfp=True,
            supports_jobs=False,
            supports_company_news=False,
            supports_press_releases=False,
            supports_website_change=False,
            requires_api_key=True,
            network_access=True,
            provider_version="2.0.0",
            source_types=["government_procurement"],
            configured=is_configured,
            validation_level=val_level,
            applicable_countries=["US"],
        )

    def _sanitize_secret(self, text: str) -> str:
        """Sanitize raw text, exceptions, URLs or metadata so API key never leaks in diagnostics."""
        if not text:
            return ""
        sanitized = str(text)
        if self.api_key and self.api_key in sanitized:
            sanitized = sanitized.replace(self.api_key, "[REDACTED_API_KEY]")
        return sanitized

    def discover_signals(
        self,
        prospect: Prospect,
        existing_signals: Optional[List[Any]] = None,
        enrichment_snapshot: Optional[Any] = None,
        contacts: Optional[List[Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> PublicSignalDiscoveryResult:
        result = PublicSignalDiscoveryResult(
            queried_at=datetime.now(timezone.utc).isoformat(),
            validation_level=self.capabilities.validation_level,
        )

        if not self.capabilities.configured:
            result.warnings.append(f"Provider '{self.provider_name}' is not configured (missing SAM_GOV_API_KEY).")
            return result

        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            raw_opportunities = self._fetch_solicitations(prospect)
        except Exception as err:
            status_code = None
            retry_after = None
            error_type = "api_error"

            if hasattr(err, "code") and isinstance(err.code, int):
                status_code = err.code
                if hasattr(err, "headers") and err.headers:
                    retry_after = err.headers.get("Retry-After")
            elif hasattr(err, "response") and hasattr(err.response, "status_code"):
                status_code = err.response.status_code
                if hasattr(err.response, "headers") and err.response.headers:
                    retry_after = err.response.headers.get("Retry-After")
            elif hasattr(err, "status_code") and isinstance(getattr(err, "status_code"), int):
                status_code = getattr(err, "status_code")

            if status_code == 429:
                error_type = "rate_limit"
            elif status_code == 503:
                error_type = "service_unavailable"
            elif status_code == 403:
                error_type = "forbidden"

            result.throttle_feedback = ProviderThrottleFeedback(
                http_status=status_code,
                retry_after=retry_after,
                error_type=error_type,
            )
            result.errors.append(self._sanitize_secret(f"SAM API query failed: {err}"))
            return result

        for opp in raw_opportunities:
            issuer = opp.get("organizationName", opp.get("buyer_organization", opp.get("issuer_name", "")))
            issuer_url = opp.get("source_url", "")
            prospect_role = opp.get("prospect_role", "issuer")

            # Match Issuer Governance
            match_res = ProspectSourceMatch.match_issuer(prospect, issuer, issuer_url, prospect_role=prospect_role)
            if match_res.status != "MATCHED":
                result.warnings.append(self._sanitize_secret(f"Solicitation '{opp.get('solicitationNumber', opp.get('noticeId'))}' skipped: {match_res.reason}"))
                continue

            # SSRF check on opportunity URL
            if issuer_url:
                is_safe, s_reason = NetworkSafetyValidator.validate_url(issuer_url)
                if not is_safe:
                    result.warnings.append(self._sanitize_secret(f"Solicitation URL '{issuer_url}' rejected by SSRF validator: {s_reason}"))
                    continue

            sol_status = str(opp.get("active", opp.get("status", "open"))).lower()
            is_active_flag = sol_status in ("true", "open", "active", "1")
            due_str = opp.get("responseDeadLine", opp.get("due_date"))

            currentness = "active" if is_active_flag and (not due_str or str(due_str)[:10] >= now_iso[:10]) else "closed"

            # Sanitized Raw Metadata (Ensure API key is purged)
            clean_raw = {k: self._sanitize_secret(str(v)) for k, v in opp.items() if k != "api_key"}

            obs = PublicSignalObservation(
                organization_id="",
                prospect_id=prospect.id,
                provider=self.provider_name,
                signal_type=SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value,
                category=SignalCategory.BUYING_INTENT.value,
                intent_strength=IntentStrength.STRONG.value,
                source_type="government_procurement",
                source_url=self._sanitize_secret(issuer_url),
                external_id=opp.get("solicitationNumber", opp.get("noticeId", opp.get("id"))),
                confidence=0.95 if currentness == "active" else 0.50,
                evidence={
                    "snippet": self._sanitize_secret(opp.get("title", "") + " - " + str(opp.get("description", ""))[:100]),
                    "rfp_title": self._sanitize_secret(opp.get("title", "Procurement Opportunity")),
                    "solicitation_number": opp.get("solicitationNumber"),
                    "notice_id": opp.get("noticeId"),
                    "buyer_organization": self._sanitize_secret(issuer),
                    "currentness": currentness,
                    "due_date": due_str,
                    "prospect_match_confidence": match_res.match_confidence,
                    "match_method": match_res.match_method,
                    "matched_rule": "government_procurement_solicitation",
                },
                raw_metadata=clean_raw,
                published_at=opp.get("postedDate", opp.get("published_at")),
                first_seen_at=now_iso,
                last_seen_at=now_iso,
            )
            result.observations.append(obs)

        return result

    def _fetch_solicitations(self, prospect: Prospect) -> List[Dict[str, Any]]:
        """Fetch raw solicitations from client or SAM API fixture."""
        if self.client and hasattr(self.client, "search_solicitations"):
            return self.client.search_solicitations(prospect.name)
        return []
