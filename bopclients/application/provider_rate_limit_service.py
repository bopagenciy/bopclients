"""ProviderRateLimitService orchestrating distributed rate limiting policies, scope resolution, and Retry-After handling."""

import urllib.parse
import email.utils
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from bopclients.domain.prospect import Prospect
from bopclients.domain.rate_limit import (
    ProviderRateLimitPolicy,
    ProviderAcquireResult,
    ProviderAcquireStatus,
)
from bopclients.infrastructure.repositories.provider_rate_limit_repository import ProviderRateLimitRepository

logger = logging.getLogger("bopclients.application.rate_limit")


class ProviderRateLimitService:
    """Application service managing provider rate limiting policies, scope keys, and backpressure coordination."""

    DEFAULT_POLICIES: Dict[str, ProviderRateLimitPolicy] = {
        "official_website": ProviderRateLimitPolicy(
            provider_key="official_website",
            max_executions=30,
            window_seconds=60,
            max_concurrent=2,
            cooldown_on_429_seconds=60,
            cooldown_on_503_seconds=30,
            honor_retry_after=True,
            max_retry_after_seconds=3600,
            request_lease_duration_seconds=30,
        ),
        "government_procurement": ProviderRateLimitPolicy(
            provider_key="government_procurement",
            max_executions=10,
            window_seconds=60,
            max_concurrent=1,
            per_organization_max_executions=4,
            cooldown_on_429_seconds=60,
            cooldown_on_503_seconds=30,
            honor_retry_after=True,
            max_retry_after_seconds=3600,
            request_lease_duration_seconds=30,
        ),
        "public_news": ProviderRateLimitPolicy(
            provider_key="public_news",
            max_executions=5,
            window_seconds=60,
            max_concurrent=1,
            cooldown_on_429_seconds=60,
            cooldown_on_503_seconds=30,
            honor_retry_after=True,
            max_retry_after_seconds=3600,
            request_lease_duration_seconds=30,
            enabled=False,  # Disabled live until search backend connected
        ),
        "gemini": ProviderRateLimitPolicy(
            provider_key="gemini",
            max_executions=15,
            window_seconds=60,
            max_concurrent=2,
            cooldown_on_429_seconds=60,
            cooldown_on_503_seconds=30,
            honor_retry_after=True,
            max_retry_after_seconds=3600,
            request_lease_duration_seconds=45,
        ),
    }

    def __init__(
        self,
        repository: ProviderRateLimitRepository,
        policies: Optional[Dict[str, ProviderRateLimitPolicy]] = None,
    ):
        self.repository = repository
        self._policies: Dict[str, ProviderRateLimitPolicy] = dict(self.DEFAULT_POLICIES)
        if policies:
            for k, p in policies.items():
                self.register_policy(p)

    def register_policy(self, policy: ProviderRateLimitPolicy) -> None:
        """Register or override a provider rate limit policy."""
        policy.validate()
        self._policies[policy.provider_key.lower().strip()] = policy

    def get_policy(self, provider_key: str) -> ProviderRateLimitPolicy:
        """Fetch policy for provider key or conservative fallback policy."""
        key = provider_key.lower().strip()
        if key in self._policies:
            return self._policies[key]
        return ProviderRateLimitPolicy(
            provider_key=key,
            max_executions=20,
            window_seconds=60,
            max_concurrent=1,
            cooldown_on_429_seconds=60,
            cooldown_on_503_seconds=30,
        )

    @classmethod
    def resolve_scope_key(
        cls,
        provider_key: str,
        prospect: Optional[Prospect] = None,
        target_url: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> str:
        """Resolve coordination scope key deterministically.
        
        Official website crawler is scoped per host (e.g. host:acme.com) to prevent
        one slow website from blocking all website checks.
        API providers like SAM.gov or Gemini are scoped globally across tenants.
        """
        p_key = provider_key.lower().strip()

        if p_key == "official_website":
            url = target_url or (prospect.website_url if prospect else None)
            if url:
                try:
                    parsed = urllib.parse.urlparse(url)
                    netloc = (parsed.netloc or "").lower().split(":")[0]
                    if netloc.startswith("www."):
                        netloc = netloc[4:]
                    if netloc:
                        return f"host:{netloc}"
                except Exception:
                    pass
            return "global:official_website"

        return f"global:{p_key}"

    @classmethod
    def parse_retry_after(
        cls,
        header_value: Any,
        default_seconds: int,
        max_seconds: int = 3600,
        now_dt: Optional[datetime] = None,
    ) -> int:
        """Parse HTTP Retry-After header as integer seconds or RFC 7231 HTTP-date with ceiling cap."""
        if header_value is None:
            return default_seconds

        val = str(header_value).strip()
        if not val:
            return default_seconds

        # 1. Decimal integer seconds
        if val.isdigit():
            try:
                sec = int(val)
                if sec <= 0:
                    return default_seconds
                return min(sec, max_seconds)
            except ValueError:
                return default_seconds

        # 2. HTTP-date format (e.g. "Fri, 04 Sep 2026 21:00:00 GMT")
        try:
            parsed_dt = email.utils.parsedate_to_datetime(val)
            if parsed_dt:
                now = now_dt or datetime.now(timezone.utc)
                if parsed_dt.tzinfo is None:
                    parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
                diff = int((parsed_dt - now).total_seconds())
                if diff <= 0:
                    return default_seconds
                return min(diff, max_seconds)
        except Exception:
            pass

        # 3. Fallback on invalid/unparseable header
        return default_seconds

    def acquire_slot(
        self,
        provider_key: str,
        scope_key: str,
        now_dt: Optional[datetime] = None,
        organization_id: Optional[str] = None,
    ) -> ProviderAcquireResult:
        """Attempt to acquire a rate limit and concurrency slot."""
        policy = self.get_policy(provider_key)
        return self.repository.try_acquire(
            provider_key, scope_key, policy, now_dt=now_dt, organization_id=organization_id
        )

    def release_slot(self, provider_key: str, scope_key: str, lease_token: str) -> bool:
        """Release an active concurrency lease."""
        return self.repository.release_lease(provider_key, scope_key, lease_token)

    def record_response(
        self,
        provider_key: str,
        scope_key: str,
        status_code: int,
        retry_after_header: Optional[str] = None,
        now_dt: Optional[datetime] = None,
    ) -> None:
        """Record provider response status code and set cooldown on 429 or 503."""
        policy = self.get_policy(provider_key)

        if status_code == 429:
            cooldown = self.parse_retry_after(
                retry_after_header,
                default_seconds=policy.cooldown_on_429_seconds,
                max_seconds=policy.max_retry_after_seconds,
                now_dt=now_dt,
            )
            self.repository.record_cooldown(provider_key, scope_key, status_code, cooldown, now_dt=now_dt)

        elif status_code == 503:
            cooldown = self.parse_retry_after(
                retry_after_header,
                default_seconds=policy.cooldown_on_503_seconds,
                max_seconds=policy.max_retry_after_seconds,
                now_dt=now_dt,
            )
            self.repository.record_cooldown(provider_key, scope_key, status_code, cooldown, now_dt=now_dt)
