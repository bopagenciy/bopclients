"""Candidate Investigation Service for single-candidate evidence verification and requalification.

Implements Phase P30.5G.5H.6B.1:
Provides an operator-controlled, strictly bounded (1 query, max 5 results), zero-persistence
investigation mechanism to resolve missing qualification evidence (official website,
local presence, or operational freshness) and requalify ephemeral candidates.
"""

import re
import urllib.parse
import unicodedata
import uuid
from typing import List, Dict, Any, Optional, Set, Tuple

from bopclients.domain.candidate_qualification import (
    CandidateQualificationStatus,
    EntityArchetype,
    GeographicEvidenceStatus,
    CurrentActivityStatus,
    CandidateQualificationResult,
)
from bopclients.domain.exceptions import TenantAccessError, DiscoveryExecutionError
from bopclients.application.search_dto import DiscoveryTask
from bopclients.application.discovery.candidate_classifier import (
    OrganizationCandidateClassifier,
    CandidateClassificationRequest,
    ClassificationDecision,
    CandidateClassificationStatus,
)
from bopclients.application.discovery.candidate_qualifier import (
    OrganizationCandidateQualifier,
)
from bopclients.application.interfaces.search_interfaces import IDiscoveryProvider
from bopclients.application.interfaces.repositories import ICampaignRepository
from bopclients.application.search_dto import (
    CandidateSourceEvidence,
    CandidateInvestigationRequest,
    CandidateInvestigationResponse,
)


class CandidateInvestigationService:
    """Orchestrates bounded investigation and requalification for ephemeral discovery candidates."""

    MAX_INVESTIGATION_QUERIES: int = 1
    MAX_RESULTS_PER_QUERY: int = 5

    SHARED_PLATFORM_HOSTS: Set[str] = set(OrganizationCandidateQualifier.DIRECTORY_HOSTS) | set(
        OrganizationCandidateQualifier.ARCHIVE_HOSTS
    ) | {
        "gov.co", "valledelcauca.gov.co", "cali.gov.co", "bogota.gov.co",
        "medellin.gov.co", "usa.gov", "nih.gov", "who.int", "paho.org",
        "medium.com", "blogspot.com", "wordpress.com", "wixsite.com",
        "sites.google.com", "github.io", "github.com", "facebook.com",
        "instagram.com", "twitter.com", "x.com", "linkedin.com", "youtube.com"
    }

    SOCIAL_DOMAINS: Set[str] = {
        "facebook.com", "x.com", "twitter.com", "linkedin.com", "instagram.com", "youtube.com"
    }

    GOV_DOMAINS: Set[str] = {
        "gov.co", "valledelcauca.gov.co", "cali.gov.co", "bogota.gov.co",
        "medellin.gov.co", "usa.gov", "nih.gov", "who.int", "paho.org"
    }

    def __init__(
        self,
        providers: Optional[List[IDiscoveryProvider]] = None,
        campaign_repo: Optional[ICampaignRepository] = None,
        qualifier: Optional[OrganizationCandidateQualifier] = None,
        classifier: Optional[OrganizationCandidateClassifier] = None,
    ):
        self.providers: Dict[str, IDiscoveryProvider] = {}
        if providers:
            for p in providers:
                p_name = p.name.lower()
                self.providers[p_name] = p
                if p_name == "web_search":
                    self.providers["tavily"] = p
        self.campaign_repo = campaign_repo
        self.qualifier = qualifier or OrganizationCandidateQualifier()
        self.classifier = classifier or OrganizationCandidateClassifier()

    def determine_objective(
        self,
        missing_evidence: List[str],
        organization_website: Optional[str],
        geographic_evidence_status: Optional[str],
        current_activity_status: Optional[str],
        city: Optional[str],
        target_override: Optional[str] = None,
    ) -> str:
        """Deterministically identify which missing evidence objective to investigate."""
        valid_objectives = {"OFFICIAL_WEBSITE", "LOCAL_PRESENCE", "CURRENT_ACTIVITY"}
        if target_override and target_override in valid_objectives:
            return target_override

        # Priority 1: Official website unknown or missing
        has_unknown_website = (
            not organization_website
            or organization_website == "UNKNOWN"
            or "OFFICIAL_ORGANIZATION_WEBSITE_UNKNOWN" in missing_evidence
        )
        if has_unknown_website:
            return "OFFICIAL_WEBSITE"

        # Priority 2: Local presence unverified when target city is specified
        needs_local_presence = (
            bool(city)
            and (
                "LOCATION_UNVERIFIED_FOR_TARGET_CITY" in missing_evidence
                or "LOCAL_PHYSICAL_PRESENCE_UNVERIFIED_FOR_NATIONAL_SCOPE" in missing_evidence
                or geographic_evidence_status in ("LOCATION_UNVERIFIED", "NATIONAL_SCOPE", None)
            )
        )
        if needs_local_presence:
            return "LOCAL_PRESENCE"

        # Priority 3: Current operational activity unknown
        needs_activity = (
            "CURRENT_ACTIVITY_EVIDENCE_REQUIRED" in missing_evidence
            or "HISTORICAL_ARCHIVE_LACKS_CURRENT_ACTIVITY_EVIDENCE" in missing_evidence
            or current_activity_status in ("CURRENT_STATUS_UNKNOWN", "HISTORICAL_ACTIVITY_ONLY", None)
        )
        if needs_activity:
            return "CURRENT_ACTIVITY"

        return "OFFICIAL_WEBSITE"

    def synthesize_query(
        self,
        candidate_name: str,
        objective: str,
        city: Optional[str] = None,
        country: Optional[str] = "CO",
    ) -> str:
        """Synthesize a general-purpose, deterministic query seeking specific missing evidence."""
        clean_name = candidate_name.strip()
        clean_country = (country or "CO").strip().upper()

        if objective == "OFFICIAL_WEBSITE":
            if clean_country == "CO" or not clean_country:
                return f"{clean_name} sitio web oficial"
            return f"{clean_name} official website"

        elif objective == "LOCAL_PRESENCE":
            loc = (city or "").strip()
            if loc:
                return f"{clean_name} {loc}"
            return f"{clean_name} sede"

        elif objective == "CURRENT_ACTIVITY":
            return f"{clean_name} 2026"

        return clean_name

    def _determine_source_evidence(
        self,
        url: str,
        title: Optional[str] = None,
        snippet: Optional[str] = None,
        archetype: Optional[str] = None,
        org_website: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Classify source authority and preserve provenance."""
        clean_url = (url or "").strip()
        norm_url = clean_url.lower().rstrip("/")
        parsed = urllib.parse.urlparse(norm_url)
        host = (parsed.netloc or "").lower().strip()
        if host.startswith("www."):
            host = host[4:]

        platform = None
        for sd in self.SOCIAL_DOMAINS:
            if host == sd or host.endswith(f".{sd}"):
                platform = sd
                break

        if platform:
            src_type = "SOCIAL_PROFILE"
        elif any(host == gd or host.endswith(f".{gd}") for gd in self.GOV_DOMAINS) or host.endswith(".gov") or host.endswith(".gov.co"):
            src_type = "GOVERNMENT_SOURCE"
        elif (
            host in OrganizationCandidateQualifier.DIRECTORY_HOSTS
            or OrganizationCandidateQualifier.DIRECTORY_PATH_PATTERN.search(parsed.path or "")
            or archetype in ("DIRECTORY_LISTING", EntityArchetype.DIRECTORY_LISTING.value)
        ):
            src_type = "DIRECTORY_LISTING"
        elif org_website and org_website != "UNKNOWN":
            p_org = urllib.parse.urlparse(org_website if "://" in org_website else f"https://{org_website}")
            org_h = (p_org.netloc or "").lower().strip()
            if org_h.startswith("www."):
                org_h = org_h[4:]
            if org_h == host or host.endswith(f".{org_h}"):
                src_type = "OFFICIAL_WEBSITE"
            else:
                src_type = "THIRD_PARTY_PAGE"
        else:
            # Check if this host is a genuine first-party candidate website
            is_shared = (
                host in self.SHARED_PLATFORM_HOSTS
                or any(host.endswith(f".{sph}") for sph in self.SHARED_PLATFORM_HOSTS)
            )
            if not is_shared and host and not platform:
                src_type = "OFFICIAL_WEBSITE"
            else:
                src_type = "THIRD_PARTY_PAGE"

        return {
            "source_url": clean_url,
            "source_host": host,
            "source_type": src_type,
            "platform": platform,
            "title": title or "",
            "snippet": snippet or "",
        }

    def _clean_entity_name(self, name: str) -> str:
        if not name:
            return ""
        cleaned = re.sub(r"\s*\(@?[a-zA-Z0-9_.-]+\)", "", name)
        cleaned = re.sub(
            r"\s+[-–—|/]\s*(?:facebook|twitter|instagram|linkedin|youtube|x|photos\s+and\s+videos|fotos\s+y\s+videos|inicio|home|perfil|profile)\b.*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+@([a-zA-Z0-9_.-]+)$", "", cleaned)
        return cleaned.strip()

    def _tokenize(self, text: str) -> List[str]:
        if not text:
            return []
        cleaned = self._clean_entity_name(text)
        normalized = unicodedata.normalize("NFKD", cleaned.lower())
        ascii_text = "".join(c for c in normalized if not unicodedata.combining(c))
        clean = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
        stopwords = {
            "de", "del", "la", "el", "los", "las", "y", "en", "por", "para", "con",
            "of", "the", "and", "in", "for", "at", "by", "un", "una", "unos", "unas",
            "facebook", "twitter", "instagram", "linkedin", "youtube", "sitio", "oficial",
            "web", "website", "inicio", "home", "colombia"
        }
        return [t for t in clean.split() if t and t not in stopwords]

    def _is_attributable_result(
        self, candidate_name: str, result_name: str, result_title: str, result_url: str
    ) -> bool:
        """Validate concordance: ensure returned result genuinely pertains to the candidate entity."""
        c_tokens = set(self._tokenize(candidate_name))
        if not c_tokens:
            return False

        r_tokens = set(self._tokenize(f"{result_name} {result_title}"))
        parsed = urllib.parse.urlparse(result_url or "")
        host = (parsed.netloc or "").lower().replace("www.", "")
        path = (parsed.path or "").lower()
        url_text = f"{host} {path}"

        # Match tokens against result title/name and URL
        matched_tokens = c_tokens.intersection(r_tokens)
        for tok in c_tokens:
            if tok in url_text:
                matched_tokens.add(tok)

        # Entity concordance threshold:
        # If candidate has >= 3 tokens, require >= 2 matches.
        # If candidate has 2 tokens, require both or 1 distinctive token (>4 chars).
        # If candidate has 1 token, require match.
        if len(c_tokens) >= 3:
            return len(matched_tokens) >= 2
        elif len(c_tokens) == 2:
            return len(matched_tokens) == 2 or (len(matched_tokens) == 1 and any(len(t) >= 5 for t in matched_tokens))
        else:
            return len(matched_tokens) >= 1

    def investigate_candidate(
        self,
        org_id: str,
        request: CandidateInvestigationRequest,
    ) -> CandidateInvestigationResponse:
        """Execute a controlled 1-query investigation, attach new evidence, and requalify."""
        if not org_id:
            raise TenantAccessError("Organization context required.")

        # 1. Validate campaign ownership if provided
        if request.campaign_id and self.campaign_repo:
            camp = self.campaign_repo.get_by_id(org_id, request.campaign_id)
            if not camp:
                raise TenantAccessError(
                    f"Investigation rejected: Campaign '{request.campaign_id}' not found for tenant '{org_id}'"
                )

        cand_id = request.candidate_id or str(uuid.uuid4())
        prev_status = request.current_qualification_status or CandidateQualificationStatus.SEARCH_MATCH.value

        # 2. Determine investigation objective
        objective = self.determine_objective(
            missing_evidence=request.missing_evidence,
            organization_website=request.organization_website,
            geographic_evidence_status=request.geographic_evidence_status,
            current_activity_status=request.current_activity_status,
            city=request.city,
            target_override=request.target_objective,
        )

        # 3. Synthesize targeted query
        investigation_query = self.synthesize_query(
            candidate_name=request.candidate_name,
            objective=objective,
            city=request.city,
            country=request.country,
        )

        # 4. Resolve web search discovery provider
        provider = self.providers.get("web_search") or self.providers.get("tavily")
        if not provider:
            return CandidateInvestigationResponse(
                status="failed",
                candidate_id=cand_id,
                candidate_name=request.candidate_name,
                investigation_objective=objective,
                investigation_query=investigation_query,
                results_received=0,
                previous_qualification_status=prev_status,
                qualification_status=prev_status,
                qualification_changed=False,
                is_commercial_review_ready=False,
                qualification_reasons=request.qualification_reasons,
                missing_evidence=request.missing_evidence,
                entity_archetype=request.entity_archetype,
                organization_website=request.organization_website,
                geographic_evidence_status=request.geographic_evidence_status,
                current_activity_status=request.current_activity_status,
                sources_count=len(request.sources) or 1,
                sources=request.sources,
                new_sources_added=0,
                database_writes=0,
                errors=["Web search discovery provider is not available or registered."],
            )

        # 5. Dispatch strictly bounded query (max 1 query, max 5 results)
        task = DiscoveryTask(
            id=str(uuid.uuid4()),
            provider="web_search",
            query=investigation_query,
            category=request.category,
            city=request.city,
            region=request.state,
            country=request.country or "CO",
            limit=self.MAX_RESULTS_PER_QUERY,
            metadata={
                "organization_id": org_id,
                "investigation": True,
                "preview": True,
            },
        )

        try:
            discovered_batch = provider.discover(task)
        except Exception as prov_err:
            return CandidateInvestigationResponse(
                status="failed",
                candidate_id=cand_id,
                candidate_name=request.candidate_name,
                investigation_objective=objective,
                investigation_query=investigation_query,
                results_received=0,
                previous_qualification_status=prev_status,
                qualification_status=prev_status,
                qualification_changed=False,
                is_commercial_review_ready=False,
                qualification_reasons=request.qualification_reasons,
                missing_evidence=request.missing_evidence,
                entity_archetype=request.entity_archetype,
                organization_website=request.organization_website,
                geographic_evidence_status=request.geographic_evidence_status,
                current_activity_status=request.current_activity_status,
                sources_count=len(request.sources) or 1,
                sources=request.sources,
                new_sources_added=0,
                database_writes=0,
                errors=[f"Discovery provider investigation query failed: {prov_err}"],
            )

        # 6. Process returned results and update attributable evidence
        existing_sources = list(request.sources)
        seen_urls: Set[str] = {
            s.source_url.lower().rstrip("/") for s in existing_sources if s.source_url
        }

        new_sources: List[CandidateSourceEvidence] = []
        resolved_website: Optional[str] = request.organization_website
        if resolved_website == "UNKNOWN":
            resolved_website = None

        new_evidence_snippets: List[str] = []
        new_evidence_titles: List[str] = []

        for biz in discovered_batch[: self.MAX_RESULTS_PER_QUERY]:
            b_url = (biz.website_url or "").strip()
            norm_b_url = b_url.lower().rstrip("/")
            b_raw = biz.raw_data or {}
            b_title = b_raw.get("title") or biz.name or ""
            b_snippet = b_raw.get("snippet") or ""

            # Concordance check: skip results that do not belong to candidate
            if not self._is_attributable_result(
                candidate_name=request.candidate_name,
                result_name=biz.name or "",
                result_title=b_title,
                result_url=b_url,
            ):
                continue

            # Classify source evidence
            src_info = self._determine_source_evidence(
                url=b_url,
                title=b_title,
                snippet=b_snippet,
                archetype=request.entity_archetype,
                org_website=resolved_website,
            )

            # Check for official first-party website resolution
            if not resolved_website or resolved_website == "UNKNOWN":
                if src_info["source_type"] == "OFFICIAL_WEBSITE":
                    p = urllib.parse.urlparse(b_url)
                    host = (p.netloc or "").lower().strip()
                    if host and host not in self.SHARED_PLATFORM_HOSTS:
                        scheme = p.scheme or "https"
                        resolved_website = f"{scheme}://{host}"
                        src_info["source_type"] = "OFFICIAL_WEBSITE"

            # Directory isolation: directories must never become official website
            if src_info["source_type"] == "DIRECTORY_LISTING":
                if resolved_website and (
                    src_info["source_host"] in resolved_website
                    or src_info["source_host"] in OrganizationCandidateQualifier.DIRECTORY_HOSTS
                ):
                    resolved_website = None

            # Collect attributable evidence texts
            new_evidence_titles.append(b_title)
            new_evidence_snippets.append(b_snippet)

            # Attach to source bundle if not duplicate
            if norm_b_url and norm_b_url not in seen_urls:
                seen_urls.add(norm_b_url)
                new_src = CandidateSourceEvidence(
                    source_url=src_info["source_url"],
                    source_host=src_info["source_host"],
                    source_type=src_info["source_type"],
                    platform=src_info["platform"],
                    title=src_info["title"],
                    snippet=src_info["snippet"],
                )
                new_sources.append(new_src)

        updated_sources = existing_sources + new_sources

        # 7. Requalification using existing OrganizationCandidateQualifier
        combined_snippets_list = [s.snippet for s in updated_sources if s.snippet]
        if request.snippet and request.snippet not in combined_snippets_list:
            combined_snippets_list.insert(0, request.snippet)
        combined_snippet = " ".join(combined_snippets_list)

        # Select best title: prefer official website source title, then non-directory title, then candidate name
        official_src = next((s for s in updated_sources if s.source_type == "OFFICIAL_WEBSITE" and s.title), None)
        if official_src and official_src.title:
            primary_title = official_src.title
        elif request.title and "directorio" not in request.title.lower():
            primary_title = request.title
        else:
            primary_title = request.candidate_name

        # Primary qualification URL: prioritize verified official website, else primary source
        primary_url = resolved_website or (
            updated_sources[0].source_url if updated_sources else ""
        )

        target_norm = (request.target_intent or request.category or "medical_association").strip().lower()

        # Step 7a: Run base classification
        base_req = CandidateClassificationRequest(
            name=request.candidate_name,
            target_intent=target_norm,
            raw_metadata={"title": primary_title, "snippet": combined_snippet, "url": primary_url},
        )
        base_classification = self.classifier.classify(base_req)

        # Step 7b: Run qualification gates
        eval_task = DiscoveryTask(
            id=str(uuid.uuid4()),
            provider="web_search",
            query=investigation_query,
            category=request.category,
            city=request.city,
            region=request.state,
            country=request.country or "CO",
            limit=5,
            metadata={"allow_national": False, "require_current_activity": False},
        )

        qual_result: CandidateQualificationResult = self.qualifier.qualify(
            candidate_name=request.candidate_name,
            target_intent=target_norm,
            base_classification=base_classification,
            raw_title=primary_title,
            url=primary_url,
            snippet=combined_snippet,
            task=eval_task,
        )

        # 8. Check qualification outcome
        new_status = qual_result.qualification_status.value
        status_changed = (new_status != prev_status)

        # Final organization website normalization
        final_org_website = qual_result.organization_website
        if final_org_website == "UNKNOWN" and resolved_website:
            final_org_website = resolved_website

        return CandidateInvestigationResponse(
            status="completed",
            candidate_id=cand_id,
            candidate_name=request.candidate_name,
            investigation_objective=objective,
            investigation_query=investigation_query,
            results_received=len(discovered_batch),
            previous_qualification_status=prev_status,
            qualification_status=new_status,
            qualification_changed=status_changed,
            is_commercial_review_ready=qual_result.is_commercial_review_ready,
            qualification_reasons=qual_result.qualification_reasons,
            missing_evidence=qual_result.missing_evidence,
            entity_archetype=qual_result.entity_archetype.value,
            organization_website=final_org_website,
            geographic_evidence_status=qual_result.geographic_evidence_status.value,
            current_activity_status=qual_result.current_activity_status.value,
            sources_count=len(updated_sources),
            sources=updated_sources,
            new_sources_added=len(new_sources),
            database_writes=0,
            warnings=[],
            errors=[],
        )
