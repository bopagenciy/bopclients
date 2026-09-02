"""IPublicSignalProvider interface and OfficialWebsiteSignalProvider implementation (P7.2 Audit Aligned)."""

import re
import urllib.parse
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone
from bopclients.domain.prospect import Prospect
from bopclients.domain.signal_observation import PublicSignalObservation
from bopclients.domain.enums import SignalType, SignalCategory, IntentStrength
from bopclients.application.signal_monitor_dto import PublicSignalProviderCapabilities, PublicSignalDiscoveryResult
from bopclients.infrastructure.security.network_validator import NetworkSafetyValidator


class IPublicSignalProvider(ABC):
    """Abstract interface for public signal discovery providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name identifier of the signal provider."""
        pass

    @property
    @abstractmethod
    def capabilities(self) -> PublicSignalProviderCapabilities:
        """Declared capabilities of this provider."""
        pass

    @abstractmethod
    def discover_signals(
        self,
        prospect: Prospect,
        existing_signals: Optional[List[Any]] = None,
        enrichment_snapshot: Optional[Any] = None,
        contacts: Optional[List[Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> PublicSignalDiscoveryResult:
        """Discover public signal observations for a given prospect."""
        pass


class DeterministicExistingDataSignalProvider(IPublicSignalProvider):
    """P6 legacy stub maintained for backwards compatibility."""

    @property
    def provider_name(self) -> str:
        return "deterministic_existing"

    @property
    def capabilities(self) -> PublicSignalProviderCapabilities:
        return PublicSignalProviderCapabilities(network_access=False)

    def discover_signals(
        self,
        prospect: Prospect,
        existing_signals: Optional[List[Any]] = None,
        enrichment_snapshot: Optional[Any] = None,
        contacts: Optional[List[Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> PublicSignalDiscoveryResult:
        return PublicSignalDiscoveryResult(queried_at=datetime.now(timezone.utc).isoformat())


class OfficialWebsiteSignalProvider(IPublicSignalProvider):
    """Safe, legitimate public signal provider inspecting prospect official website and candidate subpages within same-site boundary."""

    MAX_EXTRA_PAGES = 5
    MAX_RESPONSE_BYTES = 3 * 1024 * 1024  # 3 MB limit
    REQUEST_TIMEOUT_SECONDS = 6
    MAX_REDIRECTS = 3

    # Conservative Pattern Regexes
    RFP_PATTERNS = [
        (re.compile(r"(?:request\s+for\s+proposals?|rfp\b|invitation\s+to\s+bid|solicitation\s+for|convocatoria\s+para\s+proveedores|licitaci[oó]n)", re.IGNORECASE), "explicit_rfp_solicitation"),
    ]

    VENDOR_SEARCH_PATTERNS = [
        (re.compile(r"(?:seeking\s+(?:vendors?|agenc(?:y|ies)|suppliers?)|vendor\s+registration\s+open|supplier\s+opportunities?|inviting\s+proposals?\s+from\s+vendors?)", re.IGNORECASE), "explicit_vendor_search"),
    ]

    HIRING_MKT_PATTERNS = [
        (re.compile(r"(?:hiring|openings?|careers?|we['’]re\s+hiring).*?(?:digital\s+marketing|marketing\s+manager|growth\s+lead|seo\s+specialist|head\s+of\s+marketing)", re.IGNORECASE | re.DOTALL), "job_marketing_role"),
    ]

    HIRING_SALES_PATTERNS = [
        (re.compile(r"(?:hiring|openings?|careers?|we['’]re\s+hiring).*?(?:account\s+executive|sales\s+representative|business\s+development|head\s+of\s+sales)", re.IGNORECASE | re.DOTALL), "job_sales_role"),
    ]

    LOCATION_PATTERNS = [
        (re.compile(r"(?:opened|announcing|expanded\s+to|new\s+office\s+in|new\s+location\s+in)\s+(?:our\s+)?(?:new\s+)?([A-Z][a-z]+)", re.IGNORECASE), "location_expansion"),
    ]

    # Currentness Indicators
    CLOSED_INDICATORS = re.compile(r"(?:closed\b|archived|past\s+solicitations|awarded\s+contracts?|previous\s+rfps|submissions\s+are\s+closed|no\s+longer\s+accepting)", re.IGNORECASE)
    ACTIVE_INDICATORS = re.compile(r"(?:due|deadline|currently\s+being\s+accepted|open\s+solicitation|responses\s+must\s+be\s+received|inviting\s+proposals|now\s+open|currently\s+seeking|seeking\s+vendors|seeking\s+suppliers)", re.IGNORECASE)

    def __init__(self, scraper: Optional[Any] = None):
        self.scraper = scraper

    @property
    def provider_name(self) -> str:
        return "official_website"

    @property
    def capabilities(self) -> PublicSignalProviderCapabilities:
        """Declared capabilities matching exact implemented signal detectors (P7.2 truth audit)."""
        return PublicSignalProviderCapabilities(
            supports_rfp=True,           # Detects public_request_for_proposal and vendor_search
            supports_jobs=True,          # Detects hiring_marketing and hiring_sales
            supports_company_news=False, # Set to False (no dedicated company_news detector)
            supports_press_releases=False,# Set to False (no dedicated press_releases detector)
            supports_website_change=False,# Set to False (no historical snapshot engine)
            requires_api_key=False,
            network_access=True,
        )

    @classmethod
    def _is_same_official_site(cls, base_url: str, target_url: str) -> bool:
        """Check if target_url belongs to the same official site host (ignoring leading www)."""
        if not base_url or not target_url:
            return False
        b_host = urllib.parse.urlparse(base_url).netloc.lower().split(":")[0]
        t_host = urllib.parse.urlparse(target_url).netloc.lower().split(":")[0]
        if b_host.startswith("www."):
            b_host = b_host[4:]
        if t_host.startswith("www."):
            t_host = t_host[4:]
        return b_host == t_host

    def discover_signals(
        self,
        prospect: Prospect,
        existing_signals: Optional[List[Any]] = None,
        enrichment_snapshot: Optional[Any] = None,
        contacts: Optional[List[Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> PublicSignalDiscoveryResult:
        result = PublicSignalDiscoveryResult(queried_at=datetime.now(timezone.utc).isoformat())

        if not prospect.website_url:
            result.warnings.append(f"Prospect '{prospect.name}' has no website_url defined.")
            return result

        # 1. SSRF and DNS Pre-Validation Check
        is_safe, reason = NetworkSafetyValidator.validate_url(prospect.website_url)
        if not is_safe:
            result.errors.append(f"SSRF Safety Rejection for '{prospect.website_url}': {reason}")
            return result

        # 2. Fetch Homepage safely with redirect validation
        home_res = self._safe_fetch(prospect.website_url)
        if not home_res["success"]:
            result.warnings.append(f"Could not reach homepage '{prospect.website_url}': {home_res.get('error')}")
            return result

        result.pages_scanned += 1
        scanned_pages = [(prospect.website_url, home_res["text"], home_res.get("title", ""))]

        # 3. Extract candidate links restricted to same official site host
        candidate_links = self._extract_candidate_links(prospect.website_url, home_res["text"])

        for link_url in candidate_links[: self.MAX_EXTRA_PAGES]:
            # Same-site boundary check
            if not self._is_same_official_site(prospect.website_url, link_url):
                result.warnings.append(f"External candidate link '{link_url}' ignored (outside official host boundary)")
                continue

            l_safe, l_reason = NetworkSafetyValidator.validate_url(link_url)
            if not l_safe:
                result.warnings.append(f"Candidate link '{link_url}' rejected by SSRF validator: {l_reason}")
                continue

            sub_res = self._safe_fetch(link_url)
            if sub_res["success"]:
                result.pages_scanned += 1
                scanned_pages.append((link_url, sub_res["text"], sub_res.get("title", "")))

        # 4. Analyze scanned pages for conservative public signals
        now_iso = datetime.now(timezone.utc).isoformat()
        obs_map: Dict[str, PublicSignalObservation] = {}

        for page_url, text, page_title in scanned_pages:
            self._analyze_page(prospect.id, page_url, text, page_title, obs_map, now_iso)

        result.observations = list(obs_map.values())
        return result

    def _safe_fetch(self, url: str) -> Dict[str, Any]:
        """Fetch page with timeout, response size limits, Content-Type, and Redirect SSRF Validation."""
        if self.scraper and hasattr(self.scraper, "fetch_page"):
            try:
                res = self.scraper.fetch_page(url)
                if not res or res.get("status", 0) >= 400:
                    return {"success": False, "error": f"HTTP {res.get('status') if res else 'No response'}"}
                html_content = res.get("content", "")
                title_m = re.search(r"<title[^>]*>(.*?)</title>", html_content, re.IGNORECASE | re.DOTALL)
                title = title_m.group(1).strip() if title_m else ""
                clean_text = self._clean_html_text(html_content)
                return {"success": True, "text": clean_text, "raw_html": html_content, "title": title}
            except Exception as err:
                return {"success": False, "error": str(err)}

        current_url = url
        redirect_count = 0

        while redirect_count <= self.MAX_REDIRECTS:
            try:
                req = urllib.request.Request(
                    current_url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AntigravityBopClients/1.0"}
                )

                class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
                    def http_error_302(self, req, fp, code, msg, headers):
                        return fp
                    http_error_301 = http_error_302
                    http_error_303 = http_error_302
                    http_error_307 = http_error_302
                    http_error_308 = http_error_302

                opener = urllib.request.build_opener(NoRedirectHandler)
                with opener.open(req, timeout=self.REQUEST_TIMEOUT_SECONDS) as response:
                    status = response.getcode()
                    if status in (301, 302, 303, 307, 308):
                        redirect_count += 1
                        if redirect_count > self.MAX_REDIRECTS:
                            return {"success": False, "error": f"Max redirect limit of {self.MAX_REDIRECTS} exceeded"}

                        location = response.headers.get("Location")
                        if not location:
                            return {"success": False, "error": f"HTTP {status} redirect missing Location header"}

                        redirect_target = urllib.parse.urljoin(current_url, location)

                        # Re-validate redirect target URL through SSRF & DNS check!
                        is_r_safe, r_reason = NetworkSafetyValidator.validate_url(redirect_target)
                        if not is_r_safe:
                            return {"success": False, "error": f"Redirect to unsafe URL '{redirect_target}' blocked: {r_reason}"}

                        current_url = redirect_target
                        continue

                    if status >= 400:
                        return {"success": False, "error": f"HTTP {status}"}

                    c_type = response.headers.get("Content-Type", "").lower()
                    if c_type and not any(t in c_type for t in ["html", "text", "xhtml"]):
                        return {"success": False, "error": f"Disallowed Content-Type '{c_type}'"}

                    raw_bytes = response.read(self.MAX_RESPONSE_BYTES + 1)
                    if len(raw_bytes) > self.MAX_RESPONSE_BYTES:
                        return {"success": False, "error": "Response size exceeds 3 MB limit"}

                    html_content = raw_bytes.decode("utf-8", errors="replace")
                    title_m = re.search(r"<title[^>]*>(.*?)</title>", html_content, re.IGNORECASE | re.DOTALL)
                    title = title_m.group(1).strip() if title_m else ""
                    clean_text = self._clean_html_text(html_content)

                    return {"success": True, "text": clean_text, "raw_html": html_content, "title": title}
            except Exception as err:
                return {"success": False, "error": str(err)}

        return {"success": False, "error": f"Max redirect limit of {self.MAX_REDIRECTS} exceeded"}

    def _clean_html_text(self, html_content: str) -> str:
        clean_text = re.sub(r"<script[^>]*>.*?</script>", " ", html_content, flags=re.IGNORECASE | re.DOTALL)
        clean_text = re.sub(r"<style[^>]*>.*?</style>", " ", clean_text, flags=re.IGNORECASE | re.DOTALL)
        clean_text = re.sub(r"<[^>]+>", " ", clean_text)
        return " ".join(clean_text.split())

    def _extract_candidate_links(self, base_url: str, html_text: str) -> List[str]:
        found = []
        hrefs = re.findall(r'href=["\']([^"\']+)["\']', html_text, re.IGNORECASE)

        keywords = ["career", "job", "news", "press", "procurement", "vendor", "supplier", "rfp", "location", "tender"]
        for href in hrefs:
            full_url = urllib.parse.urljoin(base_url, href)

            # Strict same-site boundary check
            if not self._is_same_official_site(base_url, full_url):
                continue

            parsed = urllib.parse.urlparse(full_url)
            if parsed.scheme not in ("http", "https"):
                continue

            path_lower = parsed.path.lower()
            if any(kw in path_lower for kw in keywords) and full_url not in found and full_url != base_url:
                found.append(full_url)

        return found

    def _determine_currentness(self, snippet: str, text: str) -> Tuple[str, Optional[str]]:
        """Determine if an RFP/vendor opportunity is active, closed, or unknown, and extract due date."""
        target_text = f"{snippet} {text[:500]}"

        due_m = re.search(r"(?:due|deadline|proposals?\s+due|submit\s+by)\s*:?\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})", target_text, re.IGNORECASE)
        due_date = due_m.group(1) if due_m else None

        if self.CLOSED_INDICATORS.search(snippet):
            return "closed", due_date

        if due_date or self.ACTIVE_INDICATORS.search(snippet):
            return "active", due_date

        return "unknown", due_date

    def _analyze_page(
        self,
        prospect_id: str,
        page_url: str,
        text: str,
        page_title: str,
        obs_map: Dict[str, PublicSignalObservation],
        now_iso: str,
    ) -> None:
        is_educational = bool(re.search(r"(?:what\s+is\s+an?\s+rfp|how\s+to\s+write\s+an?\s+rfp|rfp\s+template|guide\s+to\s+rfp)", text, re.IGNORECASE))

        # 1. RFP Detection (BUYING INTENT / STRONG)
        if not is_educational:
            for pat, rule_id in self.RFP_PATTERNS:
                matches = list(pat.finditer(text))
                for match in matches[:3]:
                    snippet = self._extract_snippet(text, match.start(), match.end())
                    currentness, due_date = self._determine_currentness(snippet, text)

                    # Extract RFP title if present near match
                    title_m = re.search(r"(?:request\s+for\s+proposal|rfp)\s*[-:]?\s*([A-Za-z0-9\s]{5,40})", snippet, re.IGNORECASE)
                    rfp_title = title_m.group(1).strip() if title_m else rule_id

                    obs = PublicSignalObservation(
                        organization_id="",
                        prospect_id=prospect_id,
                        provider=self.provider_name,
                        signal_type=SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value,
                        category=SignalCategory.BUYING_INTENT.value,
                        intent_strength=IntentStrength.STRONG.value,
                        source_type="official_company_site",
                        source_url=page_url,
                        confidence=0.95 if currentness == "active" and due_date else (0.80 if currentness == "active" else 0.50),
                        evidence={
                            "snippet": snippet,
                            "page_title": page_title,
                            "rfp_title": rfp_title,
                            "matched_rule": rule_id,
                            "currentness": currentness,
                            "due_date": due_date,
                        },
                        raw_metadata={"matched_text": match.group(0), "currentness": currentness},
                        first_seen_at=now_iso,
                        last_seen_at=now_iso,
                    )
                    obs_map[obs.fingerprint] = obs

        # 2. Vendor Search Detection (BUYING INTENT / STRONG)
        for pat, rule_id in self.VENDOR_SEARCH_PATTERNS:
            matches = list(pat.finditer(text))
            for match in matches[:3]:
                snippet = self._extract_snippet(text, match.start(), match.end())
                currentness, due_date = self._determine_currentness(snippet, text)

                obs = PublicSignalObservation(
                    organization_id="",
                    prospect_id=prospect_id,
                    provider=self.provider_name,
                    signal_type=SignalType.VENDOR_SEARCH.value,
                    category=SignalCategory.BUYING_INTENT.value,
                    intent_strength=IntentStrength.STRONG.value,
                    source_type="official_company_site",
                    source_url=page_url,
                    confidence=0.85 if currentness == "active" else 0.50,
                    evidence={
                        "snippet": snippet,
                        "page_title": page_title,
                        "matched_rule": rule_id,
                        "currentness": currentness,
                    },
                    raw_metadata={"currentness": currentness},
                    first_seen_at=now_iso,
                    last_seen_at=now_iso,
                )
                obs_map[obs.fingerprint] = obs

        # 3. Hiring Marketing (COMPANY ACTIVITY / MEDIUM)
        for pat, rule_id in self.HIRING_MKT_PATTERNS:
            match = pat.search(text)
            if match:
                snippet = self._extract_snippet(text, match.start(), match.end())
                obs = PublicSignalObservation(
                    organization_id="",
                    prospect_id=prospect_id,
                    provider=self.provider_name,
                    signal_type=SignalType.HIRING_MARKETING.value,
                    category=SignalCategory.COMPANY_ACTIVITY.value,
                    intent_strength=IntentStrength.MEDIUM.value,
                    source_type="official_careers_site",
                    source_url=page_url,
                    confidence=0.90,
                    evidence={"snippet": snippet, "page_title": page_title, "matched_rule": rule_id, "job_title": "Marketing Manager", "currentness": "active"},
                    first_seen_at=now_iso,
                    last_seen_at=now_iso,
                )
                obs_map[obs.fingerprint] = obs

        # 4. Hiring Sales (COMPANY ACTIVITY / MEDIUM)
        for pat, rule_id in self.HIRING_SALES_PATTERNS:
            match = pat.search(text)
            if match:
                snippet = self._extract_snippet(text, match.start(), match.end())
                obs = PublicSignalObservation(
                    organization_id="",
                    prospect_id=prospect_id,
                    provider=self.provider_name,
                    signal_type=SignalType.HIRING_SALES.value,
                    category=SignalCategory.COMPANY_ACTIVITY.value,
                    intent_strength=IntentStrength.MEDIUM.value,
                    source_type="official_careers_site",
                    source_url=page_url,
                    confidence=0.90,
                    evidence={"snippet": snippet, "page_title": page_title, "matched_rule": rule_id, "job_title": "Sales Representative", "currentness": "active"},
                    first_seen_at=now_iso,
                    last_seen_at=now_iso,
                )
                obs_map[obs.fingerprint] = obs

        # 5. Location Expansion (COMPANY ACTIVITY / MEDIUM)
        for pat, rule_id in self.LOCATION_PATTERNS:
            match = pat.search(text)
            if match:
                snippet = self._extract_snippet(text, match.start(), match.end())
                loc_name = match.group(1) if match.groups() else ""
                obs = PublicSignalObservation(
                    organization_id="",
                    prospect_id=prospect_id,
                    provider=self.provider_name,
                    signal_type=SignalType.OPENED_NEW_LOCATION.value,
                    category=SignalCategory.COMPANY_ACTIVITY.value,
                    intent_strength=IntentStrength.MEDIUM.value,
                    source_type="official_company_site",
                    source_url=page_url,
                    confidence=0.85,
                    evidence={"snippet": snippet, "location_name": loc_name, "matched_rule": rule_id, "currentness": "active"},
                    first_seen_at=now_iso,
                    last_seen_at=now_iso,
                )
                obs_map[obs.fingerprint] = obs

    def _extract_snippet(self, text: str, start: int, end: int, window: int = 100) -> str:
        s = max(0, start - window)
        e = min(len(text), end + window)
        return text[s:e].strip()
