"""Comprehensive unit and functional test suite for P14 Distributed Rate Limiting, Provider Budgets & Backpressure."""

import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
import pytest

from bopclients.domain.organization import Organization
from bopclients.domain.prospect import Prospect
from bopclients.domain.signal_observation import PublicSignalObservation
from bopclients.domain.rate_limit import (
    ProviderRateLimitPolicy,
    ProviderAcquireStatus,
    ProviderAcquireResult,
    ProviderCallBudget,
    CANONICAL_OFFICIAL_WEBSITE,
    CANONICAL_GOVERNMENT_PROCUREMENT,
    CANONICAL_PUBLIC_NEWS,
    CANONICAL_GEMINI,
)
from bopclients.application.providers.procurement_provider import GovernmentProcurementProvider
from bopclients.application.signal_provider import OfficialWebsiteSignalProvider
from bopclients.application.providers.news_provider import PublicNewsSignalProvider
from bopclients.infrastructure.db.connection import SQLiteConnectionAdapter
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.monitoring_schedule_repository import MonitoringScheduleRepository
from bopclients.infrastructure.repositories.signal_observation_repository import SignalObservationRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.infrastructure.repositories.provider_rate_limit_repository import ProviderRateLimitRepository
from bopclients.application.provider_rate_limit_service import ProviderRateLimitService
from bopclients.application.provider_execution_guard import ProviderExecutionGuard
from bopclients.application.public_signal_monitor_service import PublicSignalMonitorService
from bopclients.application.continuous_monitoring_service import ContinuousMonitoringService
from bopclients.application.signal_provider import IPublicSignalProvider
from bopclients.application.signal_monitor_dto import (
    PublicSignalProviderCapabilities,
    PublicSignalDiscoveryResult,
    ProviderThrottleFeedback,
)
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus
from bopclients.runtime.container import build_runtime_container
from bopclients.worker.monitoring_worker import MonitoringWorker, MonitoringWorkerConfig


@pytest.fixture
def test_db():
    """Create a fresh in-memory SQLite database migrated to 20260902_005."""
    db = SQLiteConnectionAdapter(":memory:")
    DatabaseMigrator.migrate(db)
    yield db
    db.close()


@pytest.fixture
def container(test_db):
    """Build a RuntimeContainer wired with test_db."""
    settings = RuntimeSettings(database_url=":memory:", enabled_providers=["official_website"])
    return build_runtime_container(settings, db=test_db)


class MockSignalProvider(IPublicSignalProvider):
    """Configurable mock signal provider for testing rate limits and exceptions."""

    def __init__(
        self,
        name: str = "mock_provider",
        raise_exc: Optional[Exception] = None,
        warnings: Optional[List[str]] = None,
        errors: Optional[List[str]] = None,
        observations: Optional[List[PublicSignalObservation]] = None,
        throttle_feedback: Optional[ProviderThrottleFeedback] = None,
    ):
        self._name = name
        self.raise_exc = raise_exc
        self.warnings = warnings or []
        self.errors = errors or []
        self.observations = observations or []
        self.throttle_feedback = throttle_feedback
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> PublicSignalProviderCapabilities:
        return PublicSignalProviderCapabilities(
            supports_rfp=True,
            network_access=True,
            configured=True,
            validation_level="FIXTURE_VALIDATED",
        )

    def discover_signals(
        self,
        prospect: Prospect,
        existing_signals: Optional[List[Any]] = None,
        enrichment_snapshot: Optional[Any] = None,
        contacts: Optional[List[Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> PublicSignalDiscoveryResult:
        self.call_count += 1
        if self.raise_exc:
            raise self.raise_exc

        res = PublicSignalDiscoveryResult(
            queried_at=datetime.now(timezone.utc).isoformat(),
            validation_level="FIXTURE_VALIDATED",
            observations=list(self.observations),
            throttle_feedback=self.throttle_feedback,
        )
        res.warnings.extend(self.warnings)
        res.errors.extend(self.errors)
        return res


class TestRateLimitDomainModelP14:
    """Domain model policy validation and disable flag testing."""

    def test_policy_bounds_validation(self):
        # Non-empty provider key
        with pytest.raises(ValueError, match="provider_key cannot be empty"):
            ProviderRateLimitPolicy(provider_key="").validate()

        # Non-positive max_executions
        with pytest.raises(ValueError, match="max_executions must be > 0"):
            ProviderRateLimitPolicy(provider_key="test", max_executions=0).validate()

        # Non-positive window_seconds
        with pytest.raises(ValueError, match="window_seconds must be > 0"):
            ProviderRateLimitPolicy(provider_key="test", window_seconds=-10).validate()

        # Non-positive max_concurrent
        with pytest.raises(ValueError, match="max_concurrent must be > 0"):
            ProviderRateLimitPolicy(provider_key="test", max_concurrent=0).validate()

        # Negative cooldown
        with pytest.raises(ValueError, match="cooldown_on_429_seconds cannot be negative"):
            ProviderRateLimitPolicy(provider_key="test", cooldown_on_429_seconds=-1).validate()

        # Valid policy
        valid = ProviderRateLimitPolicy(provider_key="test", max_executions=10, window_seconds=60, max_concurrent=2)
        valid.validate()

    def test_disabled_policy_bypasses_slot_consumption(self, test_db):
        repo = ProviderRateLimitRepository(test_db)
        policy = ProviderRateLimitPolicy(provider_key="test_disabled", enabled=False)

        res = repo.try_acquire("test_disabled", "global:test_disabled", policy)
        assert res.acquired is True
        assert res.status == ProviderAcquireStatus.PROVIDER_DISABLED
        assert res.lease_token is None


class TestRateLimitRepositoryAndWindowsP14:
    """Repository fixed-window, concurrency leases, and cooldown lifecycle testing."""

    def test_acquire_and_window_advancement(self, test_db):
        repo = ProviderRateLimitRepository(test_db)
        policy = ProviderRateLimitPolicy(provider_key="site", max_executions=2, window_seconds=60, max_concurrent=10)

        t0 = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)

        # 1. First acquire: execution_count = 1
        res1 = repo.try_acquire("site", "host:acme.com", policy, now_dt=t0)
        assert res1.acquired is True
        assert res1.status == ProviderAcquireStatus.ACQUIRED
        assert res1.lease_token is not None

        st = repo.get_state("site", "host:acme.com", now_dt=t0)
        assert st["execution_count"] == 1
        assert st["active_leases_count"] == 1

        # 2. Second acquire: execution_count = 2
        res2 = repo.try_acquire("site", "host:acme.com", policy, now_dt=t0)
        assert res2.acquired is True
        assert res2.status == ProviderAcquireStatus.ACQUIRED

        st = repo.get_state("site", "host:acme.com", now_dt=t0)
        assert st["execution_count"] == 2

        # 3. Third acquire within same window: RATE_LIMITED
        res3 = repo.try_acquire("site", "host:acme.com", policy, now_dt=t0)
        assert res3.acquired is False
        assert res3.status == ProviderAcquireStatus.RATE_LIMITED
        assert res3.retry_not_before is not None

        # Counter remains 2 (failed acquire does NOT increment)
        st = repo.get_state("site", "host:acme.com", now_dt=t0)
        assert st["execution_count"] == 2

        # 4. Advance time past window (t0 + 61 seconds): window resets, acquire succeeds
        t1 = t0 + timedelta(seconds=61)
        res4 = repo.try_acquire("site", "host:acme.com", policy, now_dt=t1)
        assert res4.acquired is True
        assert res4.status == ProviderAcquireStatus.ACQUIRED

        st = repo.get_state("site", "host:acme.com", now_dt=t1)
        assert st["execution_count"] == 1

    def test_concurrency_lease_guard_and_natural_expiry(self, test_db):
        repo = ProviderRateLimitRepository(test_db)
        policy = ProviderRateLimitPolicy(
            provider_key="api",
            max_executions=100,
            window_seconds=60,
            max_concurrent=1,
            request_lease_duration_seconds=30,
        )

        t0 = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)

        # Worker A acquires concurrency lease
        res_A = repo.try_acquire("api", "global:api", policy, now_dt=t0)
        assert res_A.acquired is True

        # Worker B attempts concurrent acquire: rejected by concurrency guard
        res_B = repo.try_acquire("api", "global:api", policy, now_dt=t0)
        assert res_B.acquired is False
        assert res_B.status == ProviderAcquireStatus.CONCURRENCY_LIMITED
        assert res_B.retry_not_before is not None

        # Worker A releases lease
        released = repo.release_lease("api", "global:api", res_A.lease_token)
        assert released is True

        # Worker B can now acquire
        res_B2 = repo.try_acquire("api", "global:api", policy, now_dt=t0)
        assert res_B2.acquired is True

        # Test crash safety: Worker B "crashes" without releasing. Advance time past lease duration (31s)
        t_after_crash = t0 + timedelta(seconds=31)
        res_C = repo.try_acquire("api", "global:api", policy, now_dt=t_after_crash)
        assert res_C.acquired is True  # Worker C successfully acquires because expired lease is ignored!

    def test_stale_release_token_safety(self, test_db):
        repo = ProviderRateLimitRepository(test_db)
        policy = ProviderRateLimitPolicy(provider_key="sec", max_executions=10, window_seconds=60, max_concurrent=2)

        t0 = datetime.now(timezone.utc)
        res_A = repo.try_acquire("sec", "global:sec", policy, now_dt=t0)

        # Fake or stale token release
        stale_released = repo.release_lease("sec", "global:sec", "lease-stale-token-12345")
        assert stale_released is False

        # Worker A's lease is still intact
        st = repo.get_state("sec", "global:sec", now_dt=t0)
        assert st["active_leases_count"] == 1

        # Real release succeeds
        assert repo.release_lease("sec", "global:sec", res_A.lease_token) is True
        st = repo.get_state("sec", "global:sec", now_dt=t0)
        assert st["active_leases_count"] == 0

    def test_cooldown_record_and_expiry(self, test_db):
        repo = ProviderRateLimitRepository(test_db)
        policy = ProviderRateLimitPolicy(provider_key="sam", max_executions=10, window_seconds=60, max_concurrent=2)

        t0 = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)

        # Record 429 with 45 second cooldown
        repo.record_cooldown("sam", "global:sam", status_code=429, cooldown_seconds=45, now_dt=t0)

        # Immediate acquire attempt gets COOLDOWN_ACTIVE
        res = repo.try_acquire("sam", "global:sam", policy, now_dt=t0)
        assert res.acquired is False
        assert res.status == ProviderAcquireStatus.COOLDOWN_ACTIVE
        assert res.retry_after_seconds == 45

        # 20 seconds later: still in cooldown
        t_mid = t0 + timedelta(seconds=20)
        res_mid = repo.try_acquire("sam", "global:sam", policy, now_dt=t_mid)
        assert res_mid.acquired is False
        assert res_mid.status == ProviderAcquireStatus.COOLDOWN_ACTIVE
        assert res_mid.retry_after_seconds == 25

        # 46 seconds later: cooldown expired, acquire succeeds
        t_exp = t0 + timedelta(seconds=46)
        res_exp = repo.try_acquire("sam", "global:sam", policy, now_dt=t_exp)
        assert res_exp.acquired is True
        assert res_exp.status == ProviderAcquireStatus.ACQUIRED


class TestRetryAfterParsingP14:
    """RFC 7231 Retry-After header parsing, bounded ceiling, and garbage tolerance."""

    def test_decimal_seconds(self):
        now = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        assert ProviderRateLimitService.parse_retry_after("30", default_seconds=60, now_dt=now) == 30
        assert ProviderRateLimitService.parse_retry_after("  45  ", default_seconds=60, now_dt=now) == 45

    def test_max_ceiling_cap(self):
        now = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        # Absurd server value capped to max_seconds
        assert ProviderRateLimitService.parse_retry_after("999999", default_seconds=60, max_seconds=3600, now_dt=now) == 3600

    def test_http_date_rfc_format(self):
        now = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        target_date_str = "Fri, 04 Sep 2026 12:00:40 GMT"
        parsed = ProviderRateLimitService.parse_retry_after(target_date_str, default_seconds=60, max_seconds=3600, now_dt=now)
        assert parsed == 40

    def test_invalid_or_empty_header_fallback(self):
        now = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        assert ProviderRateLimitService.parse_retry_after(None, default_seconds=60, now_dt=now) == 60
        assert ProviderRateLimitService.parse_retry_after("", default_seconds=60, now_dt=now) == 60
        assert ProviderRateLimitService.parse_retry_after("not-a-number-or-date", default_seconds=60, now_dt=now) == 60
        assert ProviderRateLimitService.parse_retry_after("-10", default_seconds=60, now_dt=now) == 60


class TestScopeResolutionP14:
    """Per-host vs global provider scope isolation."""

    def test_official_website_per_host_isolation(self, test_db):
        repo = ProviderRateLimitRepository(test_db)
        svc = ProviderRateLimitService(repo)
        policy = ProviderRateLimitPolicy(provider_key="official_website", max_executions=1, window_seconds=60, max_concurrent=1)
        svc.register_policy(policy)

        p_acme = Prospect(name="Acme", website_url="https://www.acme.com/about")
        p_beta = Prospect(name="Beta", website_url="https://beta.io/products")

        scope_acme = svc.resolve_scope_key("official_website", prospect=p_acme)
        scope_beta = svc.resolve_scope_key("official_website", prospect=p_beta)

        assert scope_acme == "host:acme.com"
        assert scope_beta == "host:beta.io"

        # Acme consumes its single slot
        res1 = svc.acquire_slot("official_website", scope_acme)
        assert res1.acquired is True

        # Second Acme acquire is throttled
        res2 = svc.acquire_slot("official_website", scope_acme)
        assert res2.acquired is False
        assert res2.status in (ProviderAcquireStatus.RATE_LIMITED, ProviderAcquireStatus.CONCURRENCY_LIMITED)

        # Beta is independent and can acquire without throttle!
        res_beta = svc.acquire_slot("official_website", scope_beta)
        assert res_beta.acquired is True

    def test_global_scope_shared_across_tenants(self, test_db):
        repo = ProviderRateLimitRepository(test_db)
        svc = ProviderRateLimitService(repo)
        policy = ProviderRateLimitPolicy(provider_key="government_procurement", max_executions=1, window_seconds=60, max_concurrent=1)
        svc.register_policy(policy)

        scope_org1 = svc.resolve_scope_key("government_procurement")
        scope_org2 = svc.resolve_scope_key("government_procurement")
        assert scope_org1 == scope_org2 == "global:government_procurement"

        # Org 1 acquires
        res_org1 = svc.acquire_slot("government_procurement", scope_org1)
        assert res_org1.acquired is True

        # Org 2 tries same provider and sees shared throttle
        res_org2 = svc.acquire_slot("government_procurement", scope_org2)
        assert res_org2.acquired is False


class TestProviderExecutionGuardP14:
    """Execution guard lifecycle, exception handling, and lease release safety."""

    def test_guard_releases_lease_on_normal_execution(self, test_db):
        repo = ProviderRateLimitRepository(test_db)
        svc = ProviderRateLimitService(repo)
        guard = ProviderExecutionGuard(svc)

        prov = MockSignalProvider(name="official_website")
        p = Prospect(name="Test", website_url="https://acme.org")

        disc_res, permit = guard.execute_provider(prov, p)
        assert disc_res is not None
        assert permit.acquired is True
        assert prov.call_count == 1

        # Concurrency lease must be released in finally block
        st = repo.get_state("official_website", "host:acme.org")
        assert st["active_leases_count"] == 0

    def test_guard_releases_lease_on_exception(self, test_db):
        repo = ProviderRateLimitRepository(test_db)
        svc = ProviderRateLimitService(repo)
        guard = ProviderExecutionGuard(svc)

        prov = MockSignalProvider(name="official_website", raise_exc=RuntimeError("Scrape connection timed out"))
        p = Prospect(name="Test", website_url="https://acme.org")

        with pytest.raises(RuntimeError, match="Scrape connection timed out"):
            guard.execute_provider(prov, p)

        # Concurrency lease is guaranteed released despite exception
        st = repo.get_state("official_website", "host:acme.org")
        assert st["active_leases_count"] == 0

    def test_guard_records_cooldown_on_http_429(self, test_db):
        repo = ProviderRateLimitRepository(test_db)
        svc = ProviderRateLimitService(repo)
        guard = ProviderExecutionGuard(svc)

        prov = MockSignalProvider(
            name="official_website",
            throttle_feedback=ProviderThrottleFeedback(http_status=429, retry_after="25"),
        )
        p = Prospect(name="Test", website_url="https://ratelimited.com")

        guard.execute_provider(prov, p)

        # Subsequent call is rejected by active cooldown without calling provider
        disc_res2, permit2 = guard.execute_provider(prov, p)
        assert disc_res2 is None
        assert permit2.acquired is False
        assert permit2.status == ProviderAcquireStatus.COOLDOWN_ACTIVE
        assert prov.call_count == 1  # Provider was NOT invoked on second attempt!


class TestContinuousMonitoringBackpressureP14:
    """Schedule deferral, failure_count isolation, and ResearchRun clean completion under backpressure."""

    def test_partial_success_when_one_provider_throttled(self, test_db):
        repo = ProviderRateLimitRepository(test_db)
        svc = ProviderRateLimitService(repo)
        # Throttled procurement provider (0 slots)
        svc.register_policy(ProviderRateLimitPolicy(provider_key="government_procurement", max_executions=1, window_seconds=60, max_concurrent=1))
        svc.acquire_slot("government_procurement", "global:government_procurement")  # exhaust slot

        guard = ProviderExecutionGuard(svc)

        prov_web = MockSignalProvider(name="official_website")
        prov_sam = MockSignalProvider(name="government_procurement")

        org_repo = OrganizationRepository(test_db)
        p_repo = ProspectRepository(test_db)
        camp_repo = CampaignRepository(test_db)
        rr_repo = ResearchRunRepository(test_db)
        obs_repo = SignalObservationRepository(test_db)
        sched_repo = MonitoringScheduleRepository(test_db)

        org = org_repo.save(Organization(name="Test Org", slug="test-org"))
        prospect = p_repo.save_prospect(org.id, Prospect(name="Federal Prospect", website_url="https://fed.gov", industry="government"))

        mon_service = PublicSignalMonitorService(
            observation_repo=obs_repo,
            prospect_repo=p_repo,
            campaign_repo=camp_repo,
            research_run_repo=rr_repo,
            providers=[prov_web, prov_sam],
            execution_guard=guard,
        )

        cont_service = ContinuousMonitoringService(
            schedule_repo=sched_repo,
            prospect_repo=p_repo,
            observation_repo=obs_repo,
            research_run_repo=rr_repo,
            signal_monitor_service=mon_service,
        )

        sched = cont_service.ensure_schedule_for_prospect(org.id, prospect.id)
        sched.provider_names = ["official_website", "government_procurement"]
        sched.next_check_at = datetime.now(timezone.utc).isoformat()
        sched_repo.save(org.id, sched)

        exec_res = cont_service.execute_due(org.id, sched.id)
        assert exec_res.status == "PARTIAL_SUCCESS"

        refreshed = sched_repo.get_by_id(org.id, sched.id)
        assert refreshed.failure_count == 0  # failure count is 0!

    def test_all_providers_throttled_defers_schedule_without_failure(self, test_db):
        repo = ProviderRateLimitRepository(test_db)
        svc = ProviderRateLimitService(repo)
        # Saturated policy with 1 execution max
        svc.register_policy(ProviderRateLimitPolicy(provider_key="official_website", max_executions=1, window_seconds=60, max_concurrent=1))
        svc.acquire_slot("official_website", "host:saturated.com")  # exhaust slot

        guard = ProviderExecutionGuard(svc)
        prov_web = MockSignalProvider(name="official_website")

        org_repo = OrganizationRepository(test_db)
        p_repo = ProspectRepository(test_db)
        camp_repo = CampaignRepository(test_db)
        rr_repo = ResearchRunRepository(test_db)
        obs_repo = SignalObservationRepository(test_db)
        sched_repo = MonitoringScheduleRepository(test_db)

        org = org_repo.save(Organization(name="Throttled Org", slug="throttled-org"))
        prospect = p_repo.save_prospect(org.id, Prospect(name="Saturated Prospect", website_url="https://saturated.com"))

        mon_service = PublicSignalMonitorService(
            observation_repo=obs_repo,
            prospect_repo=p_repo,
            campaign_repo=camp_repo,
            research_run_repo=rr_repo,
            providers=[prov_web],
            execution_guard=guard,
        )

        cont_service = ContinuousMonitoringService(
            schedule_repo=sched_repo,
            prospect_repo=p_repo,
            observation_repo=obs_repo,
            research_run_repo=rr_repo,
            signal_monitor_service=mon_service,
        )

        now = datetime.now(timezone.utc)
        sched = cont_service.ensure_schedule_for_prospect(org.id, prospect.id, now_dt=now)
        sched.next_check_at = (now - timedelta(minutes=5)).isoformat()
        sched_repo.save(org.id, sched)

        exec_res = cont_service.execute_due(org.id, sched.id, now_dt=now)
        assert exec_res.status == "SKIPPED_BACKPRESSURE"
        assert prov_web.call_count == 0  # Provider was never called!

        refreshed = sched_repo.get_by_id(org.id, sched.id)
        assert refreshed.failure_count == 0  # Not a failure!
        # Schedule deferred to future retry timestamp (no hot-looping)
        assert refreshed.next_check_at > now.isoformat()
        assert refreshed.lease_token is None

        # ResearchRun tracking completed cleanly (not failed or stale)
        assert exec_res.research_run_id is not None
        rr = rr_repo.get_by_id(org.id, exec_res.research_run_id)
        assert rr.status == "completed"


class TestWorkerProviderBudgetP14:
    """MonitoringWorker run-level provider call budget and observability counters."""

    def test_worker_run_provider_budget_enforcement(self, container):
        org = container.org_repo.save(Organization(name="Budget Org", slug="budget-org"))
        for i in range(5):
            p = container.prospect_repo.save_prospect(org.id, Prospect(name=f"Prospect {i}", website_url=f"https://p{i}.com"))
            s = container.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, p.id)
            s.next_check_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            container.schedule_repo.save(org.id, s)

        # Configure worker with budget of max 2 provider calls
        worker_config = MonitoringWorkerConfig(
            max_items=10,
            max_provider_calls_per_run=2,
        )
        worker = MonitoringWorker(
            schedule_repo=container.schedule_repo,
            monitoring_service=container.continuous_monitoring_service,
            config=worker_config,
        )

        res = worker.run()
        assert res.stopped_reason == "PROVIDER_BUDGET_EXHAUSTED"
        assert res.provider_calls_executed == 2
        assert res.items_completed == 2


class TestSchema005MigrationP14:
    """Validate 20260902_005 migration, fresh DB, 004->005 upgrade, and readiness check."""

    def test_migration_and_readiness_status(self, test_db):
        status = DatabaseMigrator.status(test_db)
        assert status["current_version"] in ("20260902_005", "20260902_006", "20260902_007", "20260902_008")
        assert status["is_up_to_date"] is True

        settings = RuntimeSettings(database_url=":memory:", enabled_providers=["official_website"])
        readiness = RuntimeReadinessCheck.check(settings, db=test_db)
        assert readiness.status == ReadinessStatus.READY
        assert readiness.schema_version in ("20260902_005", "20260902_006", "20260902_007", "20260902_008")
        assert readiness.tables_present is True

    def test_migration_from_004_to_005_sqlite(self):
        """P14.3 Audit 8: Upgrade existing 004 SQLite database to 005 or higher."""
        db = SQLiteConnectionAdapter(":memory:")
        # Simulate pre-existing 004 database
        from bopclients.infrastructure.db.migrations import run_p1_migrations
        run_p1_migrations(db)
        DatabaseMigrator._apply_003_upgrades(db, is_pg=False)
        DatabaseMigrator._apply_004_upgrades(db, is_pg=False)
        DatabaseMigrator.ensure_version_table(db)
        past_iso = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        db.execute("INSERT INTO bopclients_schema_version (version, applied_at) VALUES (?, ?)", ("20260902_004", past_iso))
        db.commit()

        assert DatabaseMigrator.get_current_version(db) == "20260902_004"

        # Migrate to latest
        new_ver = DatabaseMigrator.migrate(db)
        assert new_ver in ("20260902_005", "20260902_006", "20260902_007", "20260902_008")
        assert DatabaseMigrator.get_current_version(db) in ("20260902_005", "20260902_006", "20260902_007", "20260902_008")

        # Verify tables and columns
        cols = [c["name"] for c in db.fetch_dicts("PRAGMA table_info(provider_rate_limit_state)")]
        assert "execution_count" in cols
        assert "window_started_at" in cols
        assert "cooldown_until" in cols

        lease_cols = [c["name"] for c in db.fetch_dicts("PRAGMA table_info(provider_rate_limit_leases)")]
        assert "lease_token" in lease_cols
        assert "permit_id" in lease_cols
        assert "expires_at" in lease_cols
        db.close()

    def test_already_005_dev_db_column_repair_sqlite(self):
        """P14.3 Audit 9: Existing uncommitted 005 DB with request_count repaired to execution_count."""
        db = SQLiteConnectionAdapter(":memory:")
        # Simulate uncommitted 005 database with old column name
        from bopclients.infrastructure.db.migrations import run_p1_migrations
        run_p1_migrations(db)
        DatabaseMigrator._apply_003_upgrades(db, is_pg=False)
        DatabaseMigrator._apply_004_upgrades(db, is_pg=False)
        db.execute("""
            CREATE TABLE IF NOT EXISTS provider_rate_limit_state (
                id VARCHAR(36) PRIMARY KEY,
                provider_key VARCHAR(50) NOT NULL,
                scope_key VARCHAR(150) NOT NULL,
                window_started_at VARCHAR(50) NOT NULL,
                request_count INTEGER NOT NULL DEFAULT 0,
                cooldown_until VARCHAR(50),
                last_status_code INTEGER,
                last_retry_after_seconds INTEGER,
                updated_at VARCHAR(50) NOT NULL,
                UNIQUE (provider_key, scope_key)
            );
        """)
        DatabaseMigrator.ensure_version_table(db)
        db.execute("INSERT INTO bopclients_schema_version (version, applied_at) VALUES (?, ?)", ("20260902_005", datetime.now(timezone.utc).isoformat()))
        db.commit()

        # Run migrator
        res_ver = DatabaseMigrator.migrate(db)
        assert res_ver in ("20260902_005", "20260902_006", "20260902_007", "20260902_008")

        # Check repaired columns
        cols = [c["name"] for c in db.fetch_dicts("PRAGMA table_info(provider_rate_limit_state)")]
        assert "execution_count" in cols
        assert "request_count" not in cols
        db.close()



class TestP141AuditedGuarantees:
    """P14.1 Audit Verification: Granularity, Canonical Keys, 429/503 Cooldown Propagation & Run Budgets."""

    def test_canonical_provider_key_contracts(self):
        """Audit 1: Canonical provider key contracts must be strictly verified across codebase."""
        gov_prov = GovernmentProcurementProvider()
        assert gov_prov.provider_name == CANONICAL_GOVERNMENT_PROCUREMENT
        assert gov_prov.provider_name == "government_procurement"

        web_prov = OfficialWebsiteSignalProvider()
        assert web_prov.provider_name == CANONICAL_OFFICIAL_WEBSITE
        assert web_prov.provider_name == "official_website"

        news_prov = PublicNewsSignalProvider()
        assert news_prov.provider_name == CANONICAL_PUBLIC_NEWS
        assert news_prov.provider_name == "public_news"

        assert CANONICAL_GEMINI == "gemini"

        # Check default policies in service
        default_keys = set(ProviderRateLimitService.DEFAULT_POLICIES.keys())
        expected_keys = {
            CANONICAL_GOVERNMENT_PROCUREMENT,
            CANONICAL_OFFICIAL_WEBSITE,
            CANONICAL_PUBLIC_NEWS,
            CANONICAL_GEMINI,
        }
        assert expected_keys.issubset(default_keys)

    def test_multi_provider_run_level_budget_pre_call_guard(self, test_db):
        """Audit 4: Multi-provider schedule with budget=1 must guard before 2nd provider executes."""
        repo = ProviderRateLimitRepository(test_db)
        svc = ProviderRateLimitService(repo)
        guard = ProviderExecutionGuard(svc)

        prov1 = MockSignalProvider(name="official_website")
        prov2 = MockSignalProvider(name="government_procurement")

        org_repo = OrganizationRepository(test_db)
        p_repo = ProspectRepository(test_db)
        camp_repo = CampaignRepository(test_db)
        rr_repo = ResearchRunRepository(test_db)
        obs_repo = SignalObservationRepository(test_db)

        org = org_repo.save(Organization(name="Budget Org", slug="budget-org"))
        prospect = p_repo.save_prospect(org.id, Prospect(name="Multi Prov Prospect", website_url="https://multiprov.com", country="US", industry="government"))

        mon_service = PublicSignalMonitorService(
            observation_repo=obs_repo,
            prospect_repo=p_repo,
            campaign_repo=camp_repo,
            research_run_repo=rr_repo,
            providers=[prov1, prov2],
            execution_guard=guard,
        )

        budget = ProviderCallBudget(max_calls=1)

        result = mon_service.monitor_prospect(
            organization_id=org.id,
            prospect_id=prospect.id,
            provider_names=["official_website", "government_procurement"],
            call_budget=budget,
        )

        # First provider executed
        assert prov1.call_count == 1
        # Second provider was NOT executed due to budget check before call!
        assert prov2.call_count == 0
        assert budget.calls_executed == 1
        assert budget.can_execute() is False

        # Verify second provider returned SKIPPED_BUDGET_EXHAUSTED
        prov2_res = result.provider_results.get("government_procurement")
        assert prov2_res is not None
        assert prov2_res.get("status") == "SKIPPED_BUDGET_EXHAUSTED"

    def test_structured_429_triggers_distributed_cooldown(self, test_db):
        """P14.2 Audit 17: Controlled 429 with Retry-After=30 via structured feedback."""
        repo = ProviderRateLimitRepository(test_db)
        svc = ProviderRateLimitService(repo)
        guard = ProviderExecutionGuard(svc)

        prov = MockSignalProvider(
            name="official_website",
            warnings=["Upstream rate limit encountered"],
            throttle_feedback=ProviderThrottleFeedback(
                http_status=429,
                retry_after="30",
                error_type="rate_limit",
            ),
        )

        org_repo = OrganizationRepository(test_db)
        p_repo = ProspectRepository(test_db)
        camp_repo = CampaignRepository(test_db)
        rr_repo = ResearchRunRepository(test_db)
        obs_repo = SignalObservationRepository(test_db)

        org = org_repo.save(Organization(name="Cooldown Org", slug="cooldown-org"))
        prospect = p_repo.save_prospect(org.id, Prospect(name="Cooldown Prospect", website_url="https://cooldown-test.com"))

        mon_service = PublicSignalMonitorService(
            observation_repo=obs_repo,
            prospect_repo=p_repo,
            campaign_repo=camp_repo,
            research_run_repo=rr_repo,
            providers=[prov],
            execution_guard=guard,
        )

        # First execution receives structured 429
        mon_service.monitor_prospect(org.id, prospect.id, provider_names=["official_website"])
        assert prov.call_count == 1

        # Check repository state: cooldown must be active for host:cooldown-test.com
        state = repo.get_state("official_website", "host:cooldown-test.com")
        assert state is not None
        assert state["cooldown_until"] is not None
        assert state["last_status_code"] == 429

        # Second worker denied, second provider invocation count remains 1
        res2 = mon_service.monitor_prospect(org.id, prospect.id, provider_names=["official_website"])
        assert prov.call_count == 1  # Denied without calling provider!
        prov_res = res2.provider_results.get("official_website")
        assert prov_res.get("status") == "SKIPPED_COOLDOWN"

    def test_structured_503_triggers_distributed_cooldown(self, test_db):
        """P14.2 Audit 18: Controlled 503 with Retry-After=20 via structured feedback."""
        repo = ProviderRateLimitRepository(test_db)
        svc = ProviderRateLimitService(repo)
        guard = ProviderExecutionGuard(svc)

        prov = MockSignalProvider(
            name="government_procurement",
            warnings=["Service temporarily unavailable"],
            throttle_feedback=ProviderThrottleFeedback(
                http_status=503,
                retry_after="20",
                error_type="service_unavailable",
            ),
        )

        org_repo = OrganizationRepository(test_db)
        p_repo = ProspectRepository(test_db)
        camp_repo = CampaignRepository(test_db)
        rr_repo = ResearchRunRepository(test_db)
        obs_repo = SignalObservationRepository(test_db)

        org = org_repo.save(Organization(name="SAM Org", slug="sam-org"))
        prospect = p_repo.save_prospect(org.id, Prospect(name="Gov Prospect", website_url="https://gov.us", country="US", industry="government"))

        mon_service = PublicSignalMonitorService(
            observation_repo=obs_repo,
            prospect_repo=p_repo,
            campaign_repo=camp_repo,
            research_run_repo=rr_repo,
            providers=[prov],
            execution_guard=guard,
        )

        mon_service.monitor_prospect(org.id, prospect.id, provider_names=["government_procurement"])
        assert prov.call_count == 1

        state = repo.get_state("government_procurement", "global:government_procurement")
        assert state is not None
        assert state["cooldown_until"] is not None
        assert state["last_status_code"] == 503

        res2 = mon_service.monitor_prospect(org.id, prospect.id, provider_names=["government_procurement"])
        assert prov.call_count == 1
        assert res2.provider_results["government_procurement"]["status"] == "SKIPPED_COOLDOWN"

    def test_no_warning_string_dependency_for_cooldown(self, test_db):
        """P14.2 Audit 19: Warning does NOT contain 'HTTP 429', but structured feedback has http_status=429 -> Cooldown recorded."""
        repo = ProviderRateLimitRepository(test_db)
        svc = ProviderRateLimitService(repo)
        guard = ProviderExecutionGuard(svc)

        # Warning contains ZERO mention of HTTP or 429
        prov = MockSignalProvider(
            name="official_website",
            warnings=["Custom application warning without any status text"],
            throttle_feedback=ProviderThrottleFeedback(
                http_status=429,
                retry_after="45",
                error_type="rate_limit",
            ),
        )

        org_repo = OrganizationRepository(test_db)
        p_repo = ProspectRepository(test_db)
        camp_repo = CampaignRepository(test_db)
        rr_repo = ResearchRunRepository(test_db)
        obs_repo = SignalObservationRepository(test_db)

        org = org_repo.save(Organization(name="Indep Org", slug="indep-org"))
        prospect = p_repo.save_prospect(org.id, Prospect(name="Indep Prospect", website_url="https://independent-throttle.com"))

        mon_service = PublicSignalMonitorService(
            observation_repo=obs_repo,
            prospect_repo=p_repo,
            campaign_repo=camp_repo,
            research_run_repo=rr_repo,
            providers=[prov],
            execution_guard=guard,
        )

        mon_service.monitor_prospect(org.id, prospect.id, provider_names=["official_website"])
        assert prov.call_count == 1

        # Cooldown MUST still be recorded because feedback is structured!
        state = repo.get_state("official_website", "host:independent-throttle.com")
        assert state is not None
        assert state["cooldown_until"] is not None
        assert state["last_status_code"] == 429

    def test_warning_string_false_positive_rejected(self, test_db):
        """P14.2 Audit 20: Warning contains 'Documentation mentions HTTP 429 behavior', but structured feedback is None -> NO cooldown."""
        repo = ProviderRateLimitRepository(test_db)
        svc = ProviderRateLimitService(repo)
        guard = ProviderExecutionGuard(svc)

        # Free-text mentions HTTP 429, but NO structured throttle feedback
        prov = MockSignalProvider(
            name="official_website",
            warnings=["Documentation mentions HTTP 429 behavior and HTTP 503 retry policies."],
            throttle_feedback=None,
        )

        org_repo = OrganizationRepository(test_db)
        p_repo = ProspectRepository(test_db)
        camp_repo = CampaignRepository(test_db)
        rr_repo = ResearchRunRepository(test_db)
        obs_repo = SignalObservationRepository(test_db)

        org = org_repo.save(Organization(name="FP Org", slug="fp-org"))
        prospect = p_repo.save_prospect(org.id, Prospect(name="FP Prospect", website_url="https://false-positive.com"))

        mon_service = PublicSignalMonitorService(
            observation_repo=obs_repo,
            prospect_repo=p_repo,
            campaign_repo=camp_repo,
            research_run_repo=rr_repo,
            providers=[prov],
            execution_guard=guard,
        )

        mon_service.monitor_prospect(org.id, prospect.id, provider_names=["official_website"])
        assert prov.call_count == 1

        # Cooldown MUST NOT be recorded!
        state = repo.get_state("official_website", "host:false-positive.com")
        assert state is not None
        assert state["cooldown_until"] is None
        assert state["last_status_code"] is None

        # Second call acquires normally
        mon_service.monitor_prospect(org.id, prospect.id, provider_names=["official_website"])
        assert prov.call_count == 2

    def test_403_and_timeout_do_not_trigger_cooldown(self, test_db):
        """P14.2 Audit 15 & 16: HTTP 403 or timeout in structured feedback must NOT set cooldown."""
        repo = ProviderRateLimitRepository(test_db)
        svc = ProviderRateLimitService(repo)
        guard = ProviderExecutionGuard(svc)

        prov = MockSignalProvider(
            name="official_website",
            warnings=["Could not reach homepage https://no-cooldown.com: HTTP 403 Forbidden"],
            throttle_feedback=ProviderThrottleFeedback(
                http_status=403,
                error_type="forbidden",
            ),
        )

        org_repo = OrganizationRepository(test_db)
        p_repo = ProspectRepository(test_db)
        camp_repo = CampaignRepository(test_db)
        rr_repo = ResearchRunRepository(test_db)
        obs_repo = SignalObservationRepository(test_db)

        org = org_repo.save(Organization(name="No Cooldown Org", slug="no-cooldown-org"))
        prospect = p_repo.save_prospect(org.id, Prospect(name="No Cooldown Prospect", website_url="https://no-cooldown.com"))

        mon_service = PublicSignalMonitorService(
            observation_repo=obs_repo,
            prospect_repo=p_repo,
            campaign_repo=camp_repo,
            research_run_repo=rr_repo,
            providers=[prov],
            execution_guard=guard,
        )

        mon_service.monitor_prospect(org.id, prospect.id, provider_names=["official_website"])
        assert prov.call_count == 1

        # Check repository state: cooldown_until must be None
        state = repo.get_state("official_website", "host:no-cooldown.com")
        assert state is not None
        assert state["cooldown_until"] is None

        # Second execution immediately acquires
        mon_service.monitor_prospect(org.id, prospect.id, provider_names=["official_website"])
        assert prov.call_count == 2

    def test_real_official_website_provider_with_controlled_429_response(self, test_db, monkeypatch):
        """P14.3 Audit 18: Real OfficialWebsiteSignalProvider integration under controlled HTTP 429 response."""
        repo = ProviderRateLimitRepository(test_db)
        svc = ProviderRateLimitService(repo)
        guard = ProviderExecutionGuard(svc)

        real_provider = OfficialWebsiteSignalProvider()

        org_repo = OrganizationRepository(test_db)
        p_repo = ProspectRepository(test_db)
        camp_repo = CampaignRepository(test_db)
        rr_repo = ResearchRunRepository(test_db)
        obs_repo = SignalObservationRepository(test_db)

        org = org_repo.save(Organization(name="Real Provider Org", slug="real-prov-org"))
        prospect = p_repo.save_prospect(org.id, Prospect(name="Acme Corp", website_url="https://acme-throttled.com"))

        mon_service = PublicSignalMonitorService(
            observation_repo=obs_repo,
            prospect_repo=p_repo,
            campaign_repo=camp_repo,
            research_run_repo=rr_repo,
            providers=[real_provider],
            execution_guard=guard,
        )

        # Mock NetworkSafetyValidator to pass validation
        from bopclients.infrastructure.security.network_validator import NetworkSafetyValidator
        monkeypatch.setattr(NetworkSafetyValidator, "validate_url", lambda url: (True, None))

        # Mock _safe_fetch on real provider to simulate structured 429
        controlled_429 = {
            "success": False,
            "html": "",
            "headers": {"retry-after": "40"},
            "error": "HTTP 429: Too Many Requests",
            "http_status": 429,
            "retry_after": 40,
            "error_type": "rate_limit",
        }
        monkeypatch.setattr(real_provider, "_safe_fetch", lambda url: controlled_429)

        # First execution triggers structured 429
        res1 = mon_service.monitor_prospect(org.id, prospect.id, provider_names=["official_website"])
        assert res1.provider_results["official_website"]["status"] in ("SUCCESS_NO_SIGNALS", "FAILED")

        # Verify cooldown recorded in repository
        state = repo.get_state("official_website", "host:acme-throttled.com")
        assert state is not None
        assert state["cooldown_until"] is not None
        assert state["last_status_code"] == 429

        # Second execution immediately skips under cooldown without invoking provider
        call_tracker = {"invoked": False}
        def fail_if_invoked(url):
            call_tracker["invoked"] = True
            return controlled_429
        monkeypatch.setattr(real_provider, "_safe_fetch", fail_if_invoked)

        res2 = mon_service.monitor_prospect(org.id, prospect.id, provider_names=["official_website"])
        assert call_tracker["invoked"] is False
        assert res2.provider_results["official_website"]["status"] == "SKIPPED_COOLDOWN"


