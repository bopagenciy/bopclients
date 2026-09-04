"""Tests for BopClients P15 — Tenant Fairness & Provider Capacity Allocation.

Validates:
1. Interleaved due schedule ordering eliminating tenant starvation.
2. Single-tenant work-conserving throughput.
3. Multi-tenant bounded interleaved round selection.
4. Dual-bucket atomic acquisition and tenant quota exhaustion.
5. Zero partial counter consumption upon tenant rejection.
6. Global cooldown precedence over tenant limits.
7. Worker / service level non-failure deferral under tenant capacity limit.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List
import pytest

from bopclients.domain.organization import Organization
from bopclients.domain.prospect import Prospect
from bopclients.domain.monitoring_schedule import MonitoringSchedule
from bopclients.domain.signal_observation import PublicSignalObservation
from bopclients.domain.rate_limit import (
    ProviderRateLimitPolicy,
    ProviderAcquireStatus,
    CANONICAL_GOVERNMENT_PROCUREMENT,
)
from bopclients.application.signal_provider import IPublicSignalProvider
from bopclients.application.signal_monitor_dto import (
    PublicSignalProviderCapabilities,
    PublicSignalDiscoveryResult,
)
from bopclients.application.provider_registry import PublicSignalProviderRegistry
from bopclients.infrastructure.db.connection import SQLiteConnectionAdapter
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.infrastructure.repositories.signal_observation_repository import SignalObservationRepository
from bopclients.infrastructure.repositories.monitoring_schedule_repository import MonitoringScheduleRepository
from bopclients.infrastructure.repositories.provider_rate_limit_repository import ProviderRateLimitRepository
from bopclients.application.provider_rate_limit_service import ProviderRateLimitService
from bopclients.application.provider_execution_guard import ProviderExecutionGuard
from bopclients.application.public_signal_monitor_service import PublicSignalMonitorService
from bopclients.application.continuous_monitoring_service import ContinuousMonitoringService
from bopclients.worker.monitoring_worker import MonitoringWorker, MonitoringWorkerConfig
from bopclients.runtime.db_migrator import DatabaseMigrator


@pytest.fixture
def test_db():
    """Create a fresh in-memory SQLite database migrated to 20260902_005."""
    db = SQLiteConnectionAdapter(":memory:")
    DatabaseMigrator.migrate(db)
    yield db
    db.close()


def _make_schedule(
    org_id: str,
    prospect_id: str,
    next_check_iso: str,
    provider: str = CANONICAL_GOVERNMENT_PROCUREMENT,
) -> MonitoringSchedule:
    return MonitoringSchedule(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        prospect_id=prospect_id,
        status="active",
        next_check_at=next_check_iso,
        provider_names=[provider],
        source_fingerprint=f"fp-{uuid.uuid4().hex[:6]}",
    )


class MockSignalProvider(IPublicSignalProvider):
    def __init__(self, name: str = CANONICAL_GOVERNMENT_PROCUREMENT):
        self._name = name
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

    def discover_signals(self, prospect: Prospect, context=None) -> PublicSignalDiscoveryResult:
        self.call_count += 1
        return PublicSignalDiscoveryResult(
            observations=[
                PublicSignalObservation(
                    organization_id=prospect.organization_id,
                    prospect_id=prospect.id,
                    provider=self._name,
                    signal_type="rfp_announcement",
                    source_url="https://sam.gov/opp/mock-123",
                    evidence={"rfp_title": "Mock Contract Award"},
                )
            ]
        )


class TestTenantFairnessDueSelection:
    """Validates bounded best-effort interleaved due ordering."""

    def test_interleaved_due_ordering_eliminates_starvation(self, test_db):
        """Org A has 10 schedules, Org B has 1. B must be selected in round 1."""
        org_repo = OrganizationRepository(test_db)
        prospect_repo = ProspectRepository(test_db)
        sched_repo = MonitoringScheduleRepository(test_db)

        base = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        now_iso = base.isoformat()

        org_a = org_repo.save(Organization(name="Org A", slug=f"org-a-{uuid.uuid4().hex[:6]}"))
        org_b = org_repo.save(Organization(name="Org B", slug=f"org-b-{uuid.uuid4().hex[:6]}"))

        # Insert 10 schedules for Org A (earlier next_check_at)
        for i in range(10):
            p = prospect_repo.save_prospect(org_a.id, Prospect(name=f"Prospect A-{i}"))
            s = _make_schedule(
                org_id=org_a.id,
                prospect_id=p.id,
                next_check_iso=(base - timedelta(minutes=20 - i)).isoformat(),
            )
            sched_repo.save(org_a.id, s)

        # Insert 1 schedule for Org B (slightly later next_check_at, but still due)
        p_b = prospect_repo.save_prospect(org_b.id, Prospect(name="Prospect B-0"))
        s_b = _make_schedule(
            org_id=org_b.id,
            prospect_id=p_b.id,
            next_check_iso=(base - timedelta(minutes=1)).isoformat(),
        )
        sched_repo.save(org_b.id, s_b)

        # Query top 4 due schedules
        due = sched_repo.list_due_system(now_iso=now_iso, limit=4)
        assert len(due) == 4

        # In round 1: one from each tenant who has work.
        round_1_orgs = {due[0].organization_id, due[1].organization_id}
        assert round_1_orgs == {org_a.id, org_b.id}

        # Due[0] and due[1] are round 1. Due[2] and due[3] are round 2 (both Org A).
        assert due[2].organization_id == org_a.id
        assert due[3].organization_id == org_a.id

    def test_single_tenant_work_conservation(self, test_db):
        """If only Org A has due work, all slots are granted to Org A (work-conserving)."""
        org_repo = OrganizationRepository(test_db)
        prospect_repo = ProspectRepository(test_db)
        sched_repo = MonitoringScheduleRepository(test_db)

        base = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        now_iso = base.isoformat()

        org_a = org_repo.save(Organization(name="Org A", slug=f"org-a-{uuid.uuid4().hex[:6]}"))

        for i in range(5):
            p = prospect_repo.save_prospect(org_a.id, Prospect(name=f"Prospect A-{i}"))
            s = _make_schedule(
                org_id=org_a.id,
                prospect_id=p.id,
                next_check_iso=(base - timedelta(minutes=10 - i)).isoformat(),
            )
            sched_repo.save(org_a.id, s)

        due = sched_repo.list_due_system(now_iso=now_iso, limit=5)
        assert len(due) == 5
        assert all(s.organization_id == org_a.id for s in due)

    def test_large_backlog_bounded_selection(self, test_db):
        """3 tenants with backlogs are interleaved fairly round by round."""
        org_repo = OrganizationRepository(test_db)
        prospect_repo = ProspectRepository(test_db)
        sched_repo = MonitoringScheduleRepository(test_db)

        base = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        now_iso = base.isoformat()

        org_a = org_repo.save(Organization(name="Org A", slug=f"org-a-{uuid.uuid4().hex[:6]}"))
        org_b = org_repo.save(Organization(name="Org B", slug=f"org-b-{uuid.uuid4().hex[:6]}"))
        org_c = org_repo.save(Organization(name="Org C", slug=f"org-c-{uuid.uuid4().hex[:6]}"))

        for org in [org_a, org_b, org_c]:
            for i in range(10):
                p = prospect_repo.save_prospect(org.id, Prospect(name=f"Prospect {org.name}-{i}"))
                s = _make_schedule(
                    org_id=org.id,
                    prospect_id=p.id,
                    next_check_iso=(base - timedelta(minutes=30 - i)).isoformat(),
                )
                sched_repo.save(org.id, s)

        # Limit 6 -> exactly Round 1 (3 items) and Round 2 (3 items)
        due = sched_repo.list_due_system(now_iso=now_iso, limit=6)
        assert len(due) == 6

        round_1 = {s.organization_id for s in due[:3]}
        round_2 = {s.organization_id for s in due[3:6]}

        expected_orgs = {org_a.id, org_b.id, org_c.id}
        assert round_1 == expected_orgs
        assert round_2 == expected_orgs


class TestDualBucketProviderCapacity:
    """Validates two-level dual-bucket rate limiting and zero partial consumption."""

    def test_dual_bucket_atomic_acquisition_and_tenant_exhaustion(self, test_db):
        repo = ProviderRateLimitRepository(test_db)
        now = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        org_1 = f"org-1-{uuid.uuid4().hex[:6]}"
        org_2 = f"org-2-{uuid.uuid4().hex[:6]}"
        scope_key = f"global:{CANONICAL_GOVERNMENT_PROCUREMENT}"

        policy = ProviderRateLimitPolicy(
            provider_key=CANONICAL_GOVERNMENT_PROCUREMENT,
            max_executions=10,
            max_concurrent=10,
            per_organization_max_executions=2,
            window_seconds=60,
            cooldown_on_429_seconds=30,
        )

        # Org 1 takes slot 1
        decision1 = repo.try_acquire(CANONICAL_GOVERNMENT_PROCUREMENT, scope_key, policy, now_dt=now, organization_id=org_1)
        assert decision1.acquired is True
        assert decision1.status == ProviderAcquireStatus.ACQUIRED

        # Org 1 takes slot 2
        decision2 = repo.try_acquire(CANONICAL_GOVERNMENT_PROCUREMENT, scope_key, policy, now_dt=now, organization_id=org_1)
        assert decision2.acquired is True
        assert decision2.status == ProviderAcquireStatus.ACQUIRED

        # Org 1 tries slot 3 -> Tenant capacity limited
        decision3 = repo.try_acquire(CANONICAL_GOVERNMENT_PROCUREMENT, scope_key, policy, now_dt=now, organization_id=org_1)
        assert decision3.acquired is False
        assert decision3.status == ProviderAcquireStatus.TENANT_CAPACITY_LIMITED

        # Org 2 takes slot 1 -> Allowed (global has remaining slots, org 2 has 0/2)
        decision4 = repo.try_acquire(CANONICAL_GOVERNMENT_PROCUREMENT, scope_key, policy, now_dt=now, organization_id=org_2)
        assert decision4.acquired is True
        assert decision4.status == ProviderAcquireStatus.ACQUIRED

    def test_no_partial_counter_consumption(self, test_db):
        """When tenant limit is exceeded, global counter must NOT be incremented."""
        repo = ProviderRateLimitRepository(test_db)
        now = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        org_1 = f"org-1-{uuid.uuid4().hex[:6]}"
        scope_key = f"global:{CANONICAL_GOVERNMENT_PROCUREMENT}"

        policy = ProviderRateLimitPolicy(
            provider_key=CANONICAL_GOVERNMENT_PROCUREMENT,
            max_executions=10,
            max_concurrent=10,
            per_organization_max_executions=1,
            window_seconds=60,
            cooldown_on_429_seconds=30,
        )

        # Org 1 takes slot 1
        d1 = repo.try_acquire(CANONICAL_GOVERNMENT_PROCUREMENT, scope_key, policy, now_dt=now, organization_id=org_1)
        assert d1.acquired is True

        # Check raw states
        global_state = repo.get_state(CANONICAL_GOVERNMENT_PROCUREMENT, f"global:{CANONICAL_GOVERNMENT_PROCUREMENT}")
        tenant_state = repo.get_state(CANONICAL_GOVERNMENT_PROCUREMENT, f"org:{org_1}:{CANONICAL_GOVERNMENT_PROCUREMENT}")
        assert global_state["execution_count"] == 1
        assert tenant_state["execution_count"] == 1

        # Org 1 tries slot 2 -> rejected
        d2 = repo.try_acquire(CANONICAL_GOVERNMENT_PROCUREMENT, scope_key, policy, now_dt=now, organization_id=org_1)
        assert d2.acquired is False
        assert d2.status == ProviderAcquireStatus.TENANT_CAPACITY_LIMITED

        # Global counter must remain exactly 1, NOT 2!
        global_state_after = repo.get_state(CANONICAL_GOVERNMENT_PROCUREMENT, f"global:{CANONICAL_GOVERNMENT_PROCUREMENT}")
        tenant_state_after = repo.get_state(CANONICAL_GOVERNMENT_PROCUREMENT, f"org:{org_1}:{CANONICAL_GOVERNMENT_PROCUREMENT}")
        assert global_state_after["execution_count"] == 1
        assert tenant_state_after["execution_count"] == 1

    def test_global_cooldown_has_precedence_over_tenant_capacity(self, test_db):
        """Global cooldown is evaluated first and returned if active."""
        repo = ProviderRateLimitRepository(test_db)
        now = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        org_1 = f"org-1-{uuid.uuid4().hex[:6]}"
        scope_key = f"global:{CANONICAL_GOVERNMENT_PROCUREMENT}"

        policy = ProviderRateLimitPolicy(
            provider_key=CANONICAL_GOVERNMENT_PROCUREMENT,
            max_executions=10,
            max_concurrent=10,
            per_organization_max_executions=2,
            window_seconds=60,
            cooldown_on_429_seconds=30,
        )

        # Trigger global cooldown
        repo.record_cooldown(
            provider_key=CANONICAL_GOVERNMENT_PROCUREMENT,
            scope_key=scope_key,
            status_code=429,
            cooldown_seconds=30,
            now_dt=now,
        )

        decision = repo.try_acquire(CANONICAL_GOVERNMENT_PROCUREMENT, scope_key, policy, now_dt=now, organization_id=org_1)
        assert decision.acquired is False
        assert decision.status == ProviderAcquireStatus.COOLDOWN_ACTIVE

    def test_worker_interleaved_execution_under_tenant_provider_capacity(self, test_db):
        """End-to-end worker execution with dual-bucket limits."""
        org_repo = OrganizationRepository(test_db)
        prospect_repo = ProspectRepository(test_db)
        camp_repo = CampaignRepository(test_db)
        sched_repo = MonitoringScheduleRepository(test_db)
        run_repo = ResearchRunRepository(test_db)
        obs_repo = SignalObservationRepository(test_db)
        rl_repo = ProviderRateLimitRepository(test_db)

        rl_service = ProviderRateLimitService(rl_repo)
        base = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)

        # Set custom policy with per_organization_max_executions=2
        policy = ProviderRateLimitPolicy(
            provider_key=CANONICAL_GOVERNMENT_PROCUREMENT,
            max_executions=10,
            max_concurrent=10,
            per_organization_max_executions=2,
            window_seconds=300,
            cooldown_on_429_seconds=30,
        )
        rl_service.register_policy(policy)

        # Create organizations and prospects
        org_1 = org_repo.save(Organization(name="Org One", slug=f"org-1-{uuid.uuid4().hex[:6]}"))
        org_2 = org_repo.save(Organization(name="Org Two", slug=f"org-2-{uuid.uuid4().hex[:6]}"))

        # Org 1: 4 prospects & schedules
        org_1_schedule_ids = []
        for i in range(4):
            p = prospect_repo.save_prospect(org_1.id, Prospect(name=f"Prospect 1-{i}", industry="public_sector"))
            s = _make_schedule(org_1.id, p.id, (base - timedelta(minutes=10 - i)).isoformat())
            sched_repo.save(org_1.id, s)
            org_1_schedule_ids.append(s.id)

        # Org 2: 2 prospects & schedules
        for i in range(2):
            p = prospect_repo.save_prospect(org_2.id, Prospect(name=f"Prospect 2-{i}", industry="public_sector"))
            s = _make_schedule(org_2.id, p.id, (base - timedelta(minutes=10 - i)).isoformat())
            sched_repo.save(org_2.id, s)

        mock_provider = MockSignalProvider()
        registry = PublicSignalProviderRegistry()
        registry.register(mock_provider)

        guard = ProviderExecutionGuard(rate_limit_service=rl_service)
        monitor_svc = PublicSignalMonitorService(
            observation_repo=obs_repo,
            prospect_repo=prospect_repo,
            campaign_repo=camp_repo,
            research_run_repo=run_repo,
            registry=registry,
            execution_guard=guard,
        )
        cont_svc = ContinuousMonitoringService(
            schedule_repo=sched_repo,
            prospect_repo=prospect_repo,
            campaign_repo=camp_repo,
            research_run_repo=run_repo,
            observation_repo=obs_repo,
            signal_monitor_service=monitor_svc,
        )
        worker = MonitoringWorker(
            schedule_repo=sched_repo,
            monitoring_service=cont_svc,
            config=MonitoringWorkerConfig(
                batch_size=10,
                max_items=10,
                max_run_seconds=30,
            ),
        )

        result = worker.run(now_dt=base)

        # Org 1: 2 executed, 2 skipped due to tenant capacity limit
        # Org 2: 2 executed, 0 skipped
        # Total provider executions: 4, Total tenant limited: 2
        assert result.items_claimed == 6
        assert result.provider_calls_executed == 4
        assert result.provider_tenant_capacity_limited == 2

        # Check failure_count on deferred schedules remains 0
        for sid in org_1_schedule_ids:
            sched = sched_repo.get_by_id(org_1.id, sid)
            assert sched is not None
            assert sched.failure_count == 0


class TestPriorityInteractionAndCapacityTruth:
    """Validates P15.1 capacity work-conservation truth and commercial priority interactions."""

    def test_static_per_org_capacity_not_work_conserving(self, test_db):
        """Single Org A cannot consume more than per_organization_max_executions even if global has room."""
        repo = ProviderRateLimitRepository(test_db)
        now = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        org_a = f"org-a-{uuid.uuid4().hex[:6]}"
        scope_key = f"global:{CANONICAL_GOVERNMENT_PROCUREMENT}"

        policy = ProviderRateLimitPolicy(
            provider_key=CANONICAL_GOVERNMENT_PROCUREMENT,
            max_executions=10,
            max_concurrent=10,
            per_organization_max_executions=4,
            window_seconds=60,
        )

        acquired_count = 0
        rejected_count = 0

        # Attempt 10 acquires for Org A
        for _ in range(10):
            res = repo.try_acquire(CANONICAL_GOVERNMENT_PROCUREMENT, scope_key, policy, now_dt=now, organization_id=org_a)
            if res.acquired:
                acquired_count += 1
            else:
                rejected_count += 1
                assert res.status == ProviderAcquireStatus.TENANT_CAPACITY_LIMITED

        assert acquired_count == 4
        assert rejected_count == 6

        # Global execution count is exactly 4, leaving 6 unused capacity
        global_state = repo.get_state(CANONICAL_GOVERNMENT_PROCUREMENT, scope_key)
        assert global_state["execution_count"] == 4
        unused_global = policy.max_executions - global_state["execution_count"]
        assert unused_global == 6

    def test_two_tenant_protected_opportunity(self, test_db):
        """Org A cannot monopolize Org B's capacity when both are active."""
        repo = ProviderRateLimitRepository(test_db)
        now = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        org_a = f"org-a-{uuid.uuid4().hex[:6]}"
        org_b = f"org-b-{uuid.uuid4().hex[:6]}"
        scope_key = f"global:{CANONICAL_GOVERNMENT_PROCUREMENT}"

        policy = ProviderRateLimitPolicy(
            provider_key=CANONICAL_GOVERNMENT_PROCUREMENT,
            max_executions=8,
            max_concurrent=10,
            per_organization_max_executions=4,
            window_seconds=60,
        )

        # Org A attempts 8
        a_acquired = 0
        for _ in range(8):
            res = repo.try_acquire(CANONICAL_GOVERNMENT_PROCUREMENT, scope_key, policy, now_dt=now, organization_id=org_a)
            if res.acquired:
                a_acquired += 1
        assert a_acquired == 4

        # Org B attempts 4 and gets all 4
        b_acquired = 0
        for _ in range(4):
            res = repo.try_acquire(CANONICAL_GOVERNMENT_PROCUREMENT, scope_key, policy, now_dt=now, organization_id=org_b)
            if res.acquired:
                b_acquired += 1
        assert b_acquired == 4

        # Total global executions reached exactly 8
        global_state = repo.get_state(CANONICAL_GOVERNMENT_PROCUREMENT, scope_key)
        assert global_state["execution_count"] == 8

    def test_retry_not_before_deterministic_tenant_window(self, test_db):
        """Tenant capacity rejection returns deterministic retry_not_before = tenant window start + window_seconds."""
        repo = ProviderRateLimitRepository(test_db)
        now = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        org_a = f"org-a-{uuid.uuid4().hex[:6]}"
        scope_key = f"global:{CANONICAL_GOVERNMENT_PROCUREMENT}"

        policy = ProviderRateLimitPolicy(
            provider_key=CANONICAL_GOVERNMENT_PROCUREMENT,
            max_executions=10,
            max_concurrent=10,
            per_organization_max_executions=1,
            window_seconds=60,
        )

        # Slot 1: Acquired
        res1 = repo.try_acquire(CANONICAL_GOVERNMENT_PROCUREMENT, scope_key, policy, now_dt=now, organization_id=org_a)
        assert res1.acquired is True

        # Slot 2: Rejected with TENANT_CAPACITY_LIMITED
        res2 = repo.try_acquire(CANONICAL_GOVERNMENT_PROCUREMENT, scope_key, policy, now_dt=now, organization_id=org_a)
        assert res2.acquired is False
        assert res2.status == ProviderAcquireStatus.TENANT_CAPACITY_LIMITED

        expected_deadline = (now + timedelta(seconds=60)).isoformat()
        assert res2.retry_not_before == expected_deadline
        assert res2.retry_after_seconds == 60

    def test_priority_due_cadence_interaction_same_tenant(self, test_db):
        """Commercial priority sets next_check_at cadence; earlier next_check_at wins within same tenant."""
        org_repo = OrganizationRepository(test_db)
        prospect_repo = ProspectRepository(test_db)
        sched_repo = MonitoringScheduleRepository(test_db)

        base = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        now_iso = base.isoformat()

        org = org_repo.save(Organization(name="Org Priority", slug=f"org-prio-{uuid.uuid4().hex[:6]}"))

        # P1: Low priority prospect scheduled long ago, due earlier (T - 2 hours)
        p1 = prospect_repo.save_prospect(org.id, Prospect(name="Low Prio Due Earlier"))
        s1 = _make_schedule(org.id, p1.id, (base - timedelta(hours=2)).isoformat())
        sched_repo.save(org.id, s1)

        # P2: Urgent prospect scheduled recently with short cadence, due later (T - 10 minutes)
        p2 = prospect_repo.save_prospect(org.id, Prospect(name="Urgent Prio Due Later"))
        s2 = _make_schedule(org.id, p2.id, (base - timedelta(minutes=10)).isoformat())
        sched_repo.save(org.id, s2)

        due = sched_repo.list_due_system(now_iso=now_iso, limit=2)
        assert len(due) == 2
        # Earlier next_check_at (s1) is evaluated first
        assert due[0].id == s1.id
        assert due[1].id == s2.id

    def test_cross_tenant_urgent_priority_cannot_starve_other_tenants(self, test_db):
        """Urgent schedules in Tenant A cannot monopolize Round 1 over due schedules of B and C."""
        org_repo = OrganizationRepository(test_db)
        prospect_repo = ProspectRepository(test_db)
        sched_repo = MonitoringScheduleRepository(test_db)

        base = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        now_iso = base.isoformat()

        org_a = org_repo.save(Organization(name="Org A (Urgent)", slug=f"org-a-{uuid.uuid4().hex[:6]}"))
        org_b = org_repo.save(Organization(name="Org B (Medium)", slug=f"org-b-{uuid.uuid4().hex[:6]}"))
        org_c = org_repo.save(Organization(name="Org C (Low)", slug=f"org-c-{uuid.uuid4().hex[:6]}"))

        # Org A has 10 due schedules (all urgent, next_check_at earlier than B and C)
        for i in range(10):
            p = prospect_repo.save_prospect(org_a.id, Prospect(name=f"Prospect A-Urgent-{i}"))
            s = _make_schedule(org_a.id, p.id, (base - timedelta(hours=5 - i * 0.1)).isoformat())
            sched_repo.save(org_a.id, s)

        # Org B has 1 due schedule
        pb = prospect_repo.save_prospect(org_b.id, Prospect(name="Prospect B-Medium"))
        sb = _make_schedule(org_b.id, pb.id, (base - timedelta(minutes=5)).isoformat())
        sched_repo.save(org_b.id, sb)

        # Org C has 1 due schedule
        pc = prospect_repo.save_prospect(org_c.id, Prospect(name="Prospect C-Low"))
        sc = _make_schedule(org_c.id, pc.id, (base - timedelta(minutes=2)).isoformat())
        sched_repo.save(org_c.id, sc)

        # Query top 3 due schedules (Round 1)
        due = sched_repo.list_due_system(now_iso=now_iso, limit=3)
        assert len(due) == 3

        # Round 1 must contain exactly one from each tenant: Org A, Org B, Org C
        round_1_orgs = {s.organization_id for s in due}
        assert round_1_orgs == {org_a.id, org_b.id, org_c.id}

    def test_large_backlog_sql_limit_pushdown(self, test_db):
        """Verify list_due_system applies LIMIT in SQL without materializing full backlog."""
        org_repo = OrganizationRepository(test_db)
        prospect_repo = ProspectRepository(test_db)
        sched_repo = MonitoringScheduleRepository(test_db)

        base = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        now_iso = base.isoformat()

        org_a = org_repo.save(Organization(name="Org A (Huge)", slug=f"org-a-{uuid.uuid4().hex[:6]}"))
        org_b = org_repo.save(Organization(name="Org B (Small)", slug=f"org-b-{uuid.uuid4().hex[:6]}"))

        # Org A has 100 due schedules
        for i in range(100):
            p = prospect_repo.save_prospect(org_a.id, Prospect(name=f"Prospect A-{i}"))
            s = _make_schedule(org_a.id, p.id, (base - timedelta(minutes=100 - i)).isoformat())
            sched_repo.save(org_a.id, s)

        # Org B has 2 due schedules
        for i in range(2):
            pb = prospect_repo.save_prospect(org_b.id, Prospect(name=f"Prospect B-{i}"))
            sb = _make_schedule(org_b.id, pb.id, (base - timedelta(minutes=5 - i)).isoformat())
            sched_repo.save(org_b.id, sb)

        due = sched_repo.list_due_system(now_iso=now_iso, limit=10)
        assert len(due) == 10
        # Org B is present in the top 10 results
        assert any(s.organization_id == org_b.id for s in due)

