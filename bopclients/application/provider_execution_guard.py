"""ProviderExecutionGuard wrapping provider invocations with distributed rate limiting and cooldowns."""

import re
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from bopclients.domain.prospect import Prospect
from bopclients.domain.rate_limit import (
    ProviderAcquireResult,
    ProviderAcquireStatus,
)
from bopclients.application.signal_provider import IPublicSignalProvider
from bopclients.application.signal_monitor_dto import PublicSignalDiscoveryResult
from bopclients.application.provider_rate_limit_service import ProviderRateLimitService

logger = logging.getLogger("bopclients.application.provider_guard")


class ProviderExecutionGuard:
    """Execution guard ensuring provider calls obey rate limits, concurrency leases, and cooldowns."""

    def __init__(self, rate_limit_service: ProviderRateLimitService):
        self.rate_limit_service = rate_limit_service

    def execute_provider(
        self,
        provider: IPublicSignalProvider,
        prospect: Prospect,
        context: Optional[Dict[str, Any]] = None,
        now_dt: Optional[datetime] = None,
        target_url: Optional[str] = None,
    ) -> Tuple[Optional[PublicSignalDiscoveryResult], ProviderAcquireResult]:
        """Execute a provider invocation safely under distributed rate limits & concurrency guards.
        
        Returns:
            Tuple of (discovery_result, acquire_permit).
            If acquire_permit.acquired is False, discovery_result is None and provider was NOT called.
        """
        provider_key = provider.provider_name.lower().strip()
        scope_key = self.rate_limit_service.resolve_scope_key(
            provider_key, prospect=prospect, target_url=target_url
        )

        # 1. Acquire distributed slot (immediate, non-blocking)
        permit = self.rate_limit_service.acquire_slot(provider_key, scope_key, now_dt=now_dt)

        if not permit.acquired:
            logger.info(
                f"Provider '{provider_key}' backpressured for scope '{scope_key}': "
                f"{permit.status} (retry_not_before: {permit.retry_not_before})"
            )
            return None, permit

        # 2. Slot acquired: Execute provider with concurrency lease active
        try:
            disc_res = provider.discover_signals(prospect, context=context)
            self._inspect_and_record_feedback(provider_key, scope_key, disc_res, now_dt=now_dt)
            return disc_res, permit

        except Exception as err:
            self._inspect_exception_and_record_feedback(provider_key, scope_key, err, now_dt=now_dt)
            raise

        finally:
            # 3. Always release concurrency lease in finally
            if permit.lease_token:
                self.rate_limit_service.release_slot(provider_key, scope_key, permit.lease_token)

    def _inspect_and_record_feedback(
        self,
        provider_key: str,
        scope_key: str,
        disc_res: PublicSignalDiscoveryResult,
        now_dt: Optional[datetime] = None,
    ) -> None:
        """Inspect structured throttle feedback for 429/503 status to trigger cooldowns without string parsing."""
        if not disc_res or not disc_res.throttle_feedback:
            return

        fb = disc_res.throttle_feedback
        if fb.http_status in (429, 503):
            self.rate_limit_service.record_response(
                provider_key,
                scope_key,
                fb.http_status,
                retry_after_header=fb.retry_after,
                now_dt=now_dt,
            )

    def _inspect_exception_and_record_feedback(
        self,
        provider_key: str,
        scope_key: str,
        err: Exception,
        now_dt: Optional[datetime] = None,
    ) -> None:
        """Inspect caught exceptions for HTTP 429/503 status code attributes."""
        status_code = None
        retry_after = None

        # urllib.error.HTTPError
        if hasattr(err, "code") and isinstance(err.code, int):
            status_code = err.code
            if hasattr(err, "headers") and err.headers:
                retry_after = err.headers.get("Retry-After")

        # httpx.HTTPStatusError
        elif hasattr(err, "response") and hasattr(err.response, "status_code"):
            status_code = err.response.status_code
            if hasattr(err.response, "headers") and err.response.headers:
                retry_after = err.response.headers.get("Retry-After")

        # Generic status_code attribute
        elif hasattr(err, "status_code") and isinstance(getattr(err, "status_code"), int):
            status_code = getattr(err, "status_code")

        if status_code in (429, 503):
            self.rate_limit_service.record_response(
                provider_key, scope_key, status_code, retry_after_header=retry_after, now_dt=now_dt
            )
