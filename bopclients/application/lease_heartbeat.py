"""LeaseHeartbeat helper managing lease renewal thresholds and ownership loss tracking."""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from bopclients.infrastructure.repositories.monitoring_schedule_repository import MonitoringScheduleRepository

logger = logging.getLogger("bopclients.heartbeat")


class LeaseHeartbeat:
    """Helper managing lease token renewal threshold evaluation and ownership loss detection."""

    def __init__(
        self,
        schedule_repo: MonitoringScheduleRepository,
        organization_id: str,
        schedule_id: str,
        lease_token: str,
        lease_duration_seconds: int = 300,
        renew_before_seconds: int = 90,
        start_now_dt: Optional[datetime] = None,
    ):
        if renew_before_seconds >= lease_duration_seconds:
            raise ValueError(f"renew_before_seconds ({renew_before_seconds}) must be strictly less than lease_duration_seconds ({lease_duration_seconds}).")

        self.schedule_repo = schedule_repo
        self.organization_id = organization_id
        self.schedule_id = schedule_id
        self.lease_token = lease_token
        self.lease_duration_seconds = lease_duration_seconds
        self.renew_before_seconds = renew_before_seconds

        now = start_now_dt or datetime.now(timezone.utc)
        self.lease_expires_at = now + timedelta(seconds=lease_duration_seconds)
        self.ownership_lost = False
        self.heartbeat_checks = 0
        self.lease_renewal_count = 0

    def heartbeat_if_needed(self, now_dt: Optional[datetime] = None) -> bool:
        """Evaluate if remaining lease duration is below threshold and renew if needed.
        
        Returns:
            True if lease is valid and active (or successfully renewed).
            False if lease ownership was lost (reclaimed by another process).
        """
        self.heartbeat_checks += 1
        if self.ownership_lost:
            return False

        now = now_dt or datetime.now(timezone.utc)
        remaining_seconds = (self.lease_expires_at - now).total_seconds()

        # Only execute database UPDATE if remaining lease duration <= renew_before_seconds threshold
        if remaining_seconds <= self.renew_before_seconds:
            renewed = self.schedule_repo.renew_lease(
                organization_id=self.organization_id,
                schedule_id=self.schedule_id,
                lease_token=self.lease_token,
                lease_duration_seconds=self.lease_duration_seconds,
                now_iso=now.isoformat(),
            )
            if renewed:
                self.lease_renewal_count += 1
                self.lease_expires_at = now + timedelta(seconds=self.lease_duration_seconds)
                logger.info(
                    f"Lease renewed for schedule {self.schedule_id[:8]} (count={self.lease_renewal_count}, "
                    f"new_expires={self.lease_expires_at.isoformat()[:19]})"
                )
        return True

    def verify_ownership(self, now_dt: Optional[datetime] = None) -> bool:
        """Explicitly verify if lease token is still owned in database before state updates."""
        if self.ownership_lost:
            return False

        p = self.schedule_repo._placeholder()
        sql = f"SELECT id FROM monitoring_schedules WHERE organization_id = {p} AND id = {p} AND lease_token = {p}"
        rows = self.schedule_repo.db.fetch_dicts(sql, (self.organization_id, self.schedule_id, self.lease_token))
        if not rows:
            self.ownership_lost = True
            logger.warning(f"LEASE_OWNERSHIP_LOST: Schedule {self.schedule_id[:8]} lease token ownership check failed.")
            return False
        return True
