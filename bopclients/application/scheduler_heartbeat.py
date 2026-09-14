"""SchedulerHeartbeat managing autonomous background thread lease renewals and ownership tracking."""

import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, Callable, Any

from bopclients.infrastructure.repositories.scheduler_repository import SchedulerRepository
from bopclients.infrastructure.db.connection import BopDBConnection

logger = logging.getLogger("bopclients.scheduler.heartbeat")


class SchedulerHeartbeat:
    """Autonomous background thread managing scheduler dispatch lease renewals during worker execution."""

    def __init__(
        self,
        scheduler_repo: SchedulerRepository,
        scheduler_key: str,
        lease_token: str,
        lease_duration_seconds: int = 300,
        renew_before_seconds: int = 90,
        start_now_dt: Optional[datetime] = None,
        clock: Optional[Callable[[], datetime]] = None,
        db_factory: Optional[Callable[[], BopDBConnection]] = None,
    ):
        if renew_before_seconds >= lease_duration_seconds:
            raise ValueError(
                f"renew_before_seconds ({renew_before_seconds}) must be strictly less than "
                f"lease_duration_seconds ({lease_duration_seconds})."
            )
        if renew_before_seconds <= 0:
            raise ValueError(f"renew_before_seconds ({renew_before_seconds}) must be strictly positive.")

        self.scheduler_repo = scheduler_repo
        self.scheduler_key = scheduler_key
        self.lease_token = lease_token
        self.lease_duration_seconds = lease_duration_seconds
        self.renew_before_seconds = renew_before_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.db_factory = db_factory

        start_time = start_now_dt or self.clock()
        self.lease_expires_at = start_time + timedelta(seconds=lease_duration_seconds)
        self.ownership_lost = False
        self.renewal_count = 0
        self.checks_count = 0

        # Thread synchronization and state
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_thread: Optional[threading.Thread] = None

        # Calculate check interval: at most half of the safety headroom, bounded between 0.1s and 5.0s
        safety_headroom = lease_duration_seconds - renew_before_seconds
        self.check_interval = max(0.1, min(5.0, safety_headroom / 2.0))

        # Optional dedicated DB connection/repository for thread safety
        self._dedicated_db: Optional[BopDBConnection] = None
        self._heartbeat_repo = scheduler_repo

    @property
    def thread(self) -> Optional[threading.Thread]:
        """Return the current or most recent background thread instance."""
        return self._thread or self._last_thread

    def start(self) -> "SchedulerHeartbeat":
        """Start the autonomous heartbeat renewal background thread."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self

            # If a db_factory is provided, create a dedicated DB connection for the thread
            if self.db_factory is not None:
                try:
                    self._dedicated_db = self.db_factory()
                    self._heartbeat_repo = SchedulerRepository(self._dedicated_db)
                except Exception as ex:
                    logger.warning("Could not establish dedicated DB for heartbeat thread, falling back to shared repo: %s", ex)
                    self._heartbeat_repo = self.scheduler_repo

            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name=f"SchedulerHeartbeat-{self.scheduler_key}",
                daemon=True,
            )
            self._last_thread = self._thread
            self._thread.start()
            logger.info(
                "Autonomous scheduler heartbeat thread started for key '%s' (check_interval=%.2fs)",
                self.scheduler_key,
                self.check_interval,
            )
            return self

    def stop(self) -> None:
        """Stop the background renewal thread cleanly and close dedicated connections."""
        self._stop_event.set()
        thread = None
        with self._lock:
            thread = self._thread
            self._thread = None

        if thread and thread.is_alive():
            thread.join(timeout=3.0)
            if thread.is_alive():
                logger.warning(
                    "Heartbeat thread '%s' did not terminate within 3.0s timeout.",
                    thread.name,
                )

        with self._lock:
            if self._dedicated_db:
                try:
                    self._dedicated_db.close()
                except Exception:
                    pass
                self._dedicated_db = None

    def __enter__(self) -> "SchedulerHeartbeat":
        return self.start()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()

    def _run_loop(self) -> None:
        """Background thread main execution loop."""
        while not self._stop_event.is_set():
            if self._stop_event.wait(timeout=self.check_interval):
                break
            if self._stop_event.is_set():
                break
            try:
                active = self.heartbeat_if_needed()
                if not active or self._stop_event.is_set():
                    if not active and not self._stop_event.is_set():
                        logger.warning("Heartbeat loop exiting: lease ownership was lost.")
                    break
            except Exception as ex:
                logger.error("Unexpected error in scheduler heartbeat loop: %s", ex)

    def heartbeat_if_needed(self, now_dt: Optional[datetime] = None) -> bool:
        """Check lease expiration and renew if within renewal threshold.

        Returns:
            True if lease is active/renewed successfully.
            False if lease ownership was lost or stop was requested.
        """
        with self._lock:
            if self._stop_event.is_set():
                return False
            self.checks_count += 1
            if self.ownership_lost:
                return False

            now = now_dt or self.clock()
            remaining_sec = (self.lease_expires_at - now).total_seconds()

            if remaining_sec <= self.renew_before_seconds:
                if self._stop_event.is_set():
                    return False
                try:
                    renewed = self._heartbeat_repo.renew_dispatch_lease(
                        scheduler_key=self.scheduler_key,
                        lease_token=self.lease_token,
                        lease_duration_seconds=self.lease_duration_seconds,
                        now_dt=now,
                    )
                except Exception as ex:
                    logger.warning("Failed executing lease renewal query: %s", ex)
                    renewed = False

                if self._stop_event.is_set():
                    return False

                if renewed:
                    self.renewal_count += 1
                    self.lease_expires_at = now + timedelta(seconds=self.lease_duration_seconds)
                    logger.info(
                        "Scheduler lease renewed for key '%s' (renewal_count=%d, new_expires=%s)",
                        self.scheduler_key,
                        self.renewal_count,
                        self.lease_expires_at.isoformat(),
                    )
                    return True
                else:
                    self.ownership_lost = True
                    logger.warning(
                        "Scheduler lease renewal FAILED for key '%s'. Ownership lost.",
                        self.scheduler_key,
                    )
                    return False

            return True

    def should_stop_callback(self) -> bool:
        """Cooperative callback suitable for passing to MonitoringWorker.run(should_stop=...).

        Returns:
            True if worker should stop (due to lease ownership loss).
            False if worker can continue.
        """
        with self._lock:
            if self.ownership_lost:
                return True
            # Also check if lease has completely expired without renewal
            now = self.clock()
            if (self.lease_expires_at - now).total_seconds() <= 0:
                self.ownership_lost = True
                return True
            return False
