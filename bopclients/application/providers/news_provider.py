"""PublicNewsSignalProvider implementing IPublicSignalProvider for corporate news & press release signal discovery."""

import re
import urllib.parse
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple, Set
from bopclients.domain.prospect import Prospect
from bopclients.domain.signal_observation import PublicSignalObservation
from bopclients.domain.enums import SignalType, SignalCategory, IntentStrength
from bopclients.application.signal_provider import IPublicSignalProvider
from bopclients.application.signal_monitor_dto import (
    PublicSignalProviderCapabilities,
    PublicSignalDiscoveryResult,
    ProviderValidationLevel,
)
from bopclients.infrastructure.security.network_validator import NetworkSafetyValidator


class PublicNewsSignalProvider(IPublicSignalProvider):
    """Specialized provider discovering corporate news and press releases via safe public web queries."""

    DEFAULT_REPUTABLE_JOURNALISM_DOMAINS = {
        "bizjournals.com",
        "techcrunch.com",
        "reuters.com",
        "bloomberg.com",
        "wsj.com",
        "marketwatch.com",
    }

    DEFAULT_PRESS_RELEASE_DISTRIBUTION_DOMAINS = {
        "prnewswire.com",
        "businesswire.com",
        "globenewswire.com",
    }

    QUERY_BUDGET_PER_PROSPECT = 4
    MAX_ARTICLES_FETCHED = 3

    # Activity Detectors for News
    LOCATION_EXPANSION_PATTERNS = [
        (re.compile(r"(?:opened\s+(?:a\s+)?(?:new\s+)?office|opened\s+(?:our\s+)?(?:new\s+)?location|expanded\s+to|announcing\s+new\s+location\s+in|grand\s+opening\s+in)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", re.IGNORECASE), "news_location_expansion"),
    ]

    FUNDING_PATTERNS = [
        (re.compile(r"(?:raised|secured|closed)\s+(\$\d+(?:\.\d+)?\s*(?:million|M|billion|B)?)\s+(?:in\s+)?(?:Series\s+[A-Z]|seed|funding|capital)", re.IGNORECASE), "news_funding_event"),
    ]

    SERVICE_LAUNCH_PATTERNS = [
        (re.compile(r"(?:launching|launches|introduced|introducing|now\s+offering)\s+(?:new\s+)?([A-Za-z0-9\s]{5,35})\s+(?:platform|service|solution|product)", re.IGNORECASE), "news_service_launch"),
    ]

    LEADERSHIP_PATTERNS = [
        (re.compile(r"(?:appointed|hires|named|welcomes)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)\s+as\s+(?:new\s+)?(CEO|CMO|CTO|VP\s+of\s+Marketing|Head\s+of\s+Sales)", re.IGNORECASE), "news_leadership_change"),
    ]

    def __init__(
        self,
        search_backend: Optional[Any] = None,
        reputable_domains: Optional[Set[str]] = None,
        distribution_domains: Optional[Set[str]] = None,
    ):
        self.search_backend = search_backend
        self.reputable_domains = set(reputable_domains) if reputable_domains else self.DEFAULT_REPUTABLE_JOURNALISM_DOMAINS
        self.distribution_domains = set(distribution_domains) if distribution_domains else self.DEFAULT_PRESS_RELEASE_DISTRIBUTION_DOMAINS

    @property
    def provider_name(self) -> str:
        return "public_news"

    @property
    def capabilities(self) -> PublicSignalProviderCapabilities:
        is_configured = self.search_backend is not None
        val_level = ProviderValidationLevel.FIXTURE_VALIDATED.value if is_configured else ProviderValidationLevel.SKIPPED_NO_BACKEND.value
        return PublicSignalProviderCapabilities(
            supports_company_news=True,
            supports_press_releases=True,
            supports_rfp=False,
            supports_jobs=False,
            supports_website_change=False,
            requires_api_key=False,
            network_access=True,
            provider_version="1.0.0",
            source_types=["official_press_release", "press_release_distribution", "reputable_news", "unknown_news"],
            configured=is_configured,
            validation_level=val_level,
            applicable_countries=["GLOBAL"],
        )

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
            result.warnings.append(f"Provider '{self.provider_name}' is not configured (missing search_backend).")
            return result

        if not prospect.name:
            result.warnings.append("Prospect name is empty for news discovery.")
            return result

        # 1. Generate Query Budget
        queries = self._generate_search_queries(prospect.name)
        candidate_articles = self._discover_candidate_articles(prospect, queries, result)

        # 2. Fetch and Extract Evidence from Candidate Source Pages
        now_iso = datetime.now(timezone.utc).isoformat()
        obs_map: Dict[str, PublicSignalObservation] = {}

        for article in candidate_articles[: self.MAX_ARTICLES_FETCHED]:
            article_url = article.get("url", "")
            is_safe, reason = NetworkSafetyValidator.validate_url(article_url)
            if not is_safe:
                result.warnings.append(f"News URL '{article_url}' rejected by SSRF validator: {reason}")
                continue

            result.pages_scanned += 1
            text = article.get("content", article.get("snippet", ""))

            # Article Prospect Matching: Confirm prospect is explicitly mentioned in content
            if not self._verify_prospect_content_match(prospect, text, article_url):
                result.warnings.append(f"News article '{article_url}' skipped: Prospect '{prospect.name}' not mentioned in content.")
                continue

            self._analyze_news_text(prospect.id, article_url, text, article.get("title", ""), obs_map, now_iso)

        result.observations = list(obs_map.values())
        return result

    def _generate_search_queries(self, company_name: str) -> List[str]:
        base = company_name.strip()
        return [
            f'"{base}" expansion new office',
            f'"{base}" funding raised',
            f'"{base}" launch new service',
            f'"{base}" press release',
        ][: self.QUERY_BUDGET_PER_PROSPECT]

    def _discover_candidate_articles(self, prospect: Prospect, queries: List[str], result: PublicSignalDiscoveryResult) -> List[Dict[str, Any]]:
        articles = []
        if self.search_backend and hasattr(self.search_backend, "search"):
            for q in queries:
                try:
                    res = self.search_backend.search(q)
                    for item in res:
                        if item.get("url") and item not in articles:
                            articles.append(item)
                except Exception as err:
                    result.warnings.append(f"News query '{q}' failed: {err}")
        return articles

    def _verify_prospect_content_match(self, prospect: Prospect, text: str, article_url: str) -> bool:
        if not text or not isinstance(text, str):
            return False
        p_name = prospect.name.strip().lower()
        if p_name in text.lower():
            return True
        if prospect.website_url:
            p_host = urllib.parse.urlparse(prospect.website_url).netloc.lower().replace("www.", "")
            if p_host and p_host in text.lower():
                return True
        return False

    def _determine_source_trust(self, source_url: str) -> Tuple[str, float]:
        host = urllib.parse.urlparse(source_url).netloc.lower().split(":")[0].replace("www.", "")
        if any(dd in host for dd in self.distribution_domains):
            return "press_release_distribution", 0.95
        elif any(rd in host for rd in self.reputable_domains):
            return "reputable_news", 0.85
        elif "press" in host or "pr" in host:
            return "official_press_release", 0.95
        return "unknown_news", 0.60

    def _analyze_news_text(
        self,
        prospect_id: str,
        source_url: str,
        text: str,
        title: str,
        obs_map: Dict[str, PublicSignalObservation],
        now_iso: str,
    ) -> None:
        source_type, confidence = self._determine_source_trust(source_url)

        # 1. Location Expansion
        for pat, rule_id in self.LOCATION_EXPANSION_PATTERNS:
            match = pat.search(text)
            if match:
                loc_name = match.group(1) if match.groups() else ""
                obs = PublicSignalObservation(
                    organization_id="",
                    prospect_id=prospect_id,
                    provider=self.provider_name,
                    signal_type=SignalType.OPENED_NEW_LOCATION.value,
                    category=SignalCategory.COMPANY_ACTIVITY.value,
                    intent_strength=IntentStrength.MEDIUM.value,
                    source_type=source_type,
                    source_url=source_url,
                    confidence=confidence,
                    evidence={
                        "snippet": match.group(0),
                        "page_title": title,
                        "location_name": loc_name,
                        "matched_rule": rule_id,
                        "currentness": "active",
                    },
                    first_seen_at=now_iso,
                    last_seen_at=now_iso,
                )
                obs_map[obs.fingerprint] = obs

        # 2. Funding Event
        for pat, rule_id in self.FUNDING_PATTERNS:
            match = pat.search(text)
            if match:
                amount = match.group(1) if match.groups() else ""
                obs = PublicSignalObservation(
                    organization_id="",
                    prospect_id=prospect_id,
                    provider=self.provider_name,
                    signal_type="new_funding",
                    category=SignalCategory.COMPANY_ACTIVITY.value,
                    intent_strength=IntentStrength.MEDIUM.value,
                    source_type=source_type,
                    source_url=source_url,
                    confidence=confidence,
                    evidence={
                        "snippet": match.group(0),
                        "page_title": title,
                        "funding_amount": amount,
                        "matched_rule": rule_id,
                        "currentness": "active",
                    },
                    first_seen_at=now_iso,
                    last_seen_at=now_iso,
                )
                obs_map[obs.fingerprint] = obs

        # 3. Service Launch
        for pat, rule_id in self.SERVICE_LAUNCH_PATTERNS:
            match = pat.search(text)
            if match:
                service_name = match.group(1).strip() if match.groups() else ""
                obs = PublicSignalObservation(
                    organization_id="",
                    prospect_id=prospect_id,
                    provider=self.provider_name,
                    signal_type="new_service_launch",
                    category=SignalCategory.COMPANY_ACTIVITY.value,
                    intent_strength=IntentStrength.MEDIUM.value,
                    source_type=source_type,
                    source_url=source_url,
                    confidence=confidence,
                    evidence={
                        "snippet": match.group(0),
                        "page_title": title,
                        "service_name": service_name,
                        "matched_rule": rule_id,
                        "currentness": "active",
                    },
                    first_seen_at=now_iso,
                    last_seen_at=now_iso,
                )
                obs_map[obs.fingerprint] = obs

        # 4. Leadership Change
        for pat, rule_id in self.LEADERSHIP_PATTERNS:
            match = pat.search(text)
            if match:
                exec_name = match.group(1) if len(match.groups()) > 0 else ""
                exec_role = match.group(2) if len(match.groups()) > 1 else ""
                obs = PublicSignalObservation(
                    organization_id="",
                    prospect_id=prospect_id,
                    provider=self.provider_name,
                    signal_type="leadership_change",
                    category=SignalCategory.COMPANY_ACTIVITY.value,
                    intent_strength=IntentStrength.MEDIUM.value,
                    source_type=source_type,
                    source_url=source_url,
                    confidence=confidence,
                    evidence={
                        "snippet": match.group(0),
                        "page_title": title,
                        "executive_name": exec_name,
                        "executive_role": exec_role,
                        "matched_rule": rule_id,
                        "currentness": "active",
                    },
                    first_seen_at=now_iso,
                    last_seen_at=now_iso,
                )
                obs_map[obs.fingerprint] = obs
