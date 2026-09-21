"""Phase P30.1: Durable Research Execution Foundation Tests.

Verifies end-to-end wiring of ProspectResearchOrchestrator to the BopClients runtime,
atomic claim semantics, status transitions, intelligence persistence, bulk operations,
single run endpoint, multi-tenant isolation, CLI runner, and zero paid provider safety.
"""

import uuid
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from bopclients.domain.organization import Organization, OrganizationMember
from bopclients.domain.enums import MemberRole
from bopclients.domain.prospect import Prospect
from bopclients.domain.campaign import Campaign
from bopclients.domain.research_run import ResearchRun
from bopclients.domain.prospect_intelligence import ProspectIntelligence
from bopclients.domain.exceptions import TenantAccessError
from bopclients.application.providers.deterministic_research_provider import DeterministicResearchProvider
from bopclients.application.providers.gemini_research_provider import GeminiProspectResearchProvider
from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.container import build_runtime_container, build_research_worker
from bopclients.runtime.research_worker_cli import main as cli_main
from bopclients.api.app import create_bopclients_api_app


@pytest.fixture
def p30_ctx():
    """Isolated test environment with two organizations, prospects, and configured container."""
    db = create_database_connection(":memory:")
    DatabaseMigrator.migrate(db)

    settings = RuntimeSettings(
        database_url="sqlite:///:memory:",
        auth_signing_key="p30-research-execution-test-secret-key-32!",
        auth_token_expire_seconds=3600,
    )
    container = build_runtime_container(settings=settings, db=db)
    app = create_bopclients_api_app(container=container, settings=settings)
    client = TestClient(app)

    # 1. Organization A
    org_a = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name="Tenant Alpha",
        slug="tenant-alpha",
    )
    container.org_repo.save(org_a)

    # 2. Organization B
    org_b = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name="Tenant Beta",
        slug="tenant-beta",
    )
    container.org_repo.save(org_b)

    # 3. Users
    user_a = container.auth_service.register_user(
        email="admin@alpha.com",
        name="Admin Alpha",
        password="Password123!",
        locale="en",
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=user_a.id,
            role=MemberRole.ADMIN,
        )
    )

    user_b = container.auth_service.register_user(
        email="admin@beta.com",
        name="Admin Beta",
        password="Password123!",
        locale="en",
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_b.id,
            user_id=user_b.id,
            role=MemberRole.ADMIN,
        )
    )

    # 4. Prospects
    prospect_a = Prospect(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        name="Apex Robotics Inc",
        website_url="https://apexrobotics.example.com",
        city="Detroit",
        state="MI",
        country="USA",
        industry="Robotics",
        source="discovery",
    )
    container.prospect_repo.save_prospect(org_a.id, prospect_a)

    prospect_b = Prospect(
        id=str(uuid.uuid4()),
        organization_id=org_b.id,
        name="Beta Logistics Corp",
        website_url="https://betalogistics.example.com",
        city="Chicago",
        state="IL",
        country="USA",
        industry="Logistics",
        source="discovery",
    )
    container.prospect_repo.save_prospect(org_b.id, prospect_b)

    # Campaign for Org A
    campaign_a = Campaign(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        name="Q3 Automation Push",
    )
    container.campaign_repo.save(org_a.id, campaign_a)

    def login(email: str, bop_org_id: str):
        res = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "Password123!"},
            headers={"X-Bop-Organization-Id": bop_org_id},
        )
        token = res.json()["access_token"]
        return {"Authorization": f"Bearer {token}", "X-Bop-Organization-Id": bop_org_id}

    return {
        "db": db,
        "container": container,
        "client": client,
        "org_a": org_a,
        "org_b": org_b,
        "prospect_a": prospect_a,
        "prospect_b": prospect_b,
        "campaign_a": campaign_a,
        "headers_a": login("admin@alpha.com", org_a.bop_organization_id),
        "headers_b": login("admin@beta.com", org_b.bop_organization_id),
    }


class TestResearchExecutionFoundationP30:
    """Complete test suite verifying Phase P30.1 specifications."""

    def test_01_container_wires_deterministic_provider_by_default(self, p30_ctx):
        """1. Container wires DeterministicResearchProvider by default."""
        container = p30_ctx["container"]
        assert container.research_worker is not None
        assert container.prospect_research_service is not None
        assert container.prospect_research_orchestrator is not None

        orchestrator = container.prospect_research_orchestrator
        assert isinstance(orchestrator.research_provider, DeterministicResearchProvider)

        # Worker convenience builder
        worker = build_research_worker(container.settings, container.db)
        assert worker is not None
        assert worker.research_service is not None

    def test_02_post_research_returns_202_and_pending_run(self, p30_ctx):
        """2. POST /api/v1/prospects/{id}/research returns 202 and pending ResearchRun."""
        client = p30_ctx["client"]
        org_a = p30_ctx["org_a"]
        prospect_a = p30_ctx["prospect_a"]
        campaign_a = p30_ctx["campaign_a"]
        headers = p30_ctx["headers_a"]

        resp = client.post(
            f"/api/v1/prospects/{prospect_a.id}/research",
            json={"campaign_id": campaign_a.id, "run_type": "deep_research"},
            headers=headers,
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["id"] is not None
        assert body["prospect_id"] == prospect_a.id
        assert body["campaign_id"] == campaign_a.id
        assert body["status"] in ("pending", "completed")  # Background task might complete fast in TestClient
        assert body["organization_id"] == org_a.id

    def test_03_atomic_claim_run(self, p30_ctx):
        """3. Worker claims pending run atomically (pending -> running, records execution_attempt_id)."""
        container = p30_ctx["container"]
        org_a = p30_ctx["org_a"]
        prospect_a = p30_ctx["prospect_a"]

        now = datetime.now(timezone.utc).isoformat()
        run = ResearchRun(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            prospect_id=prospect_a.id,
            run_type="deep_research",
            status="pending",
            created_at=now,
            updated_at=now,
        )
        container.research_run_repo.save(org_a.id, run)

        claimed = container.research_run_repo.claim_run(org_a.id, run.id, worker_id="worker-test-1")
        assert claimed is not None
        assert claimed.status == "running"
        assert claimed.execution_attempt_id == "worker-test-1"
        assert claimed.started_at is not None

    def test_04_concurrent_workers_claim_once(self, p30_ctx):
        """4. Two concurrent workers trying to claim same run: exactly one succeeds, one gets None."""
        container = p30_ctx["container"]
        org_a = p30_ctx["org_a"]
        prospect_a = p30_ctx["prospect_a"]

        now = datetime.now(timezone.utc).isoformat()
        run = ResearchRun(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            prospect_id=prospect_a.id,
            run_type="deep_research",
            status="pending",
            created_at=now,
            updated_at=now,
        )
        container.research_run_repo.save(org_a.id, run)

        claim1 = container.research_run_repo.claim_run(org_a.id, run.id, worker_id="worker-alpha")
        claim2 = container.research_run_repo.claim_run(org_a.id, run.id, worker_id="worker-beta")

        # Exactly one succeeds
        assert (claim1 is not None and claim2 is None) or (claim1 is None and claim2 is not None)
        successful_claim = claim1 or claim2
        assert successful_claim.status == "running"

    def test_05_and_06_worker_executes_orchestrator_and_persists_intel(self, p30_ctx):
        """5 & 6. Worker executes ProspectResearchOrchestrator and persists ProspectIntelligence."""
        container = p30_ctx["container"]
        org_a = p30_ctx["org_a"]
        prospect_a = p30_ctx["prospect_a"]

        now = datetime.now(timezone.utc).isoformat()
        run = ResearchRun(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            prospect_id=prospect_a.id,
            run_type="deep_research",
            status="pending",
            created_at=now,
            updated_at=now,
        )
        container.research_run_repo.save(org_a.id, run)

        result = container.research_worker.claim_and_execute_run(
            org_id=org_a.id,
            run_id=run.id,
            worker_id="test-worker-unit",
        )
        assert result is not None
        assert result.prospect_id == prospect_a.id

        # Check run status updated in DB
        completed_run = container.research_run_repo.get_by_id(org_a.id, run.id)
        assert completed_run is not None
        assert completed_run.status == "completed"
        assert completed_run.completed_at is not None
        assert completed_run.error_message is None

        # Check intelligence record was persisted
        intel = container.intel_repo.get_latest(org_a.id, prospect_a.id, provider="deterministic")
        assert intel is not None
        assert intel.organization_id == org_a.id
        assert intel.prospect_id == prospect_a.id

    def test_07_failed_run_updates_status_to_failed(self, p30_ctx):
        """7. Failed run (e.g., orchestrator exception) updates status to failed and records error_message."""
        container = p30_ctx["container"]
        org_a = p30_ctx["org_a"]
        prospect_a = p30_ctx["prospect_a"]

        now = datetime.now(timezone.utc).isoformat()
        run = ResearchRun(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            prospect_id=prospect_a.id,
            run_type="deep_research",
            status="pending",
            created_at=now,
            updated_at=now,
        )
        container.research_run_repo.save(org_a.id, run)

        # Mock research_prospect to throw an unexpected error
        with patch.object(
            container.prospect_research_service,
            "research_prospect",
            side_effect=RuntimeError("Simulated LLM pipeline failure"),
        ):
            with pytest.raises(RuntimeError):
                container.research_worker.claim_and_execute_run(
                    org_id=org_a.id,
                    run_id=run.id,
                )

        failed_run = container.research_run_repo.get_by_id(org_a.id, run.id)
        assert failed_run is not None
        assert failed_run.status == "failed"
        assert "Simulated LLM pipeline failure" in (failed_run.error_message or "")

    def test_08_sparse_prospect_without_signals_produces_truthful_intel(self, p30_ctx):
        """8. Prospect with NO signals produces truthful ProspectIntelligence without crashing."""
        container = p30_ctx["container"]
        org_a = p30_ctx["org_a"]

        # Prospect with no signals or enrichments
        sparse_prospect = Prospect(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            name="Ghost Tech Corp",
            website_url="https://ghosttech.example.com",
            city="Nowhere",
            country="USA",
        )
        container.prospect_repo.save_prospect(org_a.id, sparse_prospect)

        now = datetime.now(timezone.utc).isoformat()
        run = ResearchRun(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            prospect_id=sparse_prospect.id,
            run_type="deep_research",
            status="pending",
            created_at=now,
            updated_at=now,
        )
        container.research_run_repo.save(org_a.id, run)

        result = container.research_worker.claim_and_execute_run(
            org_id=org_a.id,
            run_id=run.id,
        )
        assert result is not None
        assert len(result.claims) == 0
        assert len(result.commercial_opportunities) == 0

        intel = container.intel_repo.get_latest(org_a.id, sparse_prospect.id, provider="deterministic")
        assert intel is not None
        assert intel.confidence <= 0.5
        assert intel.data.get("claims") == []
        assert intel.data.get("commercial_opportunities") == []

    def test_09_bulk_research_executes_runs(self, p30_ctx):
        """9. Bulk research (/bulk/research) queues runs and worker processes them."""
        client = p30_ctx["client"]
        container = p30_ctx["container"]
        org_a = p30_ctx["org_a"]
        headers = p30_ctx["headers_a"]

        # Create two additional prospects
        p1 = Prospect(id=str(uuid.uuid4()), organization_id=org_a.id, name="Bulk One", city="NYC")
        p2 = Prospect(id=str(uuid.uuid4()), organization_id=org_a.id, name="Bulk Two", city="LA")
        container.prospect_repo.save_prospect(org_a.id, p1)
        container.prospect_repo.save_prospect(org_a.id, p2)

        resp = client.post(
            "/api/v1/prospects/bulk/research",
            json={"prospect_ids": [p1.id, p2.id], "run_type": "quick_scan"},
            headers=headers,
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["requested"] == 2
        assert body["queued"] == 2

        # In TestClient, BackgroundTasks run synchronously before response returns.
        # Check that both runs are now completed in the database.
        runs_p1 = container.research_run_repo.list_by_organization(org_a.id, prospect_id=p1.id)
        runs_p2 = container.research_run_repo.list_by_organization(org_a.id, prospect_id=p2.id)
        assert len(runs_p1) >= 1
        assert runs_p1[0].status == "completed"
        assert len(runs_p2) >= 1
        assert runs_p2[0].status == "completed"

    def test_10_get_single_research_run(self, p30_ctx):
        """10. GET /api/v1/research-runs/{run_id} returns run with correct status, prospect_id, campaign_id."""
        client = p30_ctx["client"]
        container = p30_ctx["container"]
        org_a = p30_ctx["org_a"]
        prospect_a = p30_ctx["prospect_a"]
        campaign_a = p30_ctx["campaign_a"]
        headers = p30_ctx["headers_a"]

        now = datetime.now(timezone.utc).isoformat()
        run = ResearchRun(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            prospect_id=prospect_a.id,
            campaign_id=campaign_a.id,
            run_type="deep_research",
            status="pending",
            created_at=now,
            updated_at=now,
        )
        container.research_run_repo.save(org_a.id, run)

        resp = client.get(f"/api/v1/research-runs/{run.id}", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == run.id
        assert data["prospect_id"] == prospect_a.id
        assert data["campaign_id"] == campaign_a.id
        assert data["status"] == "pending"

    def test_11_multi_tenant_isolation(self, p30_ctx):
        """11. Multi-tenant isolation: Tenant B cannot see or claim Tenant A's research run."""
        client = p30_ctx["client"]
        container = p30_ctx["container"]
        org_a = p30_ctx["org_a"]
        org_b = p30_ctx["org_b"]
        prospect_a = p30_ctx["prospect_a"]
        headers_b = p30_ctx["headers_b"]

        now = datetime.now(timezone.utc).isoformat()
        run_a = ResearchRun(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            prospect_id=prospect_a.id,
            run_type="deep_research",
            status="pending",
            created_at=now,
            updated_at=now,
        )
        container.research_run_repo.save(org_a.id, run_a)

        # 1. Tenant B GET returns 404
        resp = client.get(f"/api/v1/research-runs/{run_a.id}", headers=headers_b)
        assert resp.status_code == 404

        # 2. Tenant B list_pending_runs does not include Org A's run
        b_pending = container.research_run_repo.list_pending_runs(org_b.id)
        assert not any(r.id == run_a.id for r in b_pending)

        # 3. Tenant B claim_run returns None or raises TenantAccessError
        b_claimed = container.research_run_repo.claim_run(org_b.id, run_a.id)
        assert b_claimed is None

    def test_12_worker_cli_run_once(self, p30_ctx):
        """12. Worker CLI --run-once processes pending runs and exits cleanly."""
        container = p30_ctx["container"]
        org_a = p30_ctx["org_a"]
        prospect_a = p30_ctx["prospect_a"]

        now = datetime.now(timezone.utc).isoformat()
        run = ResearchRun(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            prospect_id=prospect_a.id,
            run_type="deep_research",
            status="pending",
            created_at=now,
            updated_at=now,
        )
        container.research_run_repo.save(org_a.id, run)

        exit_code = cli_main(["--run-once", "--tenant", org_a.id, "--json"], container=container)
        assert exit_code == 0

        updated = container.research_run_repo.get_by_id(org_a.id, run.id)
        assert updated is not None
        assert updated.status == "completed"

    def test_13_worker_recovers_stale_running_runs(self, p30_ctx):
        """13. Worker recovers stale running runs via ResearchRunRecoveryService."""
        container = p30_ctx["container"]
        org_a = p30_ctx["org_a"]
        prospect_a = p30_ctx["prospect_a"]

        stale_time = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        stale_run = ResearchRun(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            prospect_id=prospect_a.id,
            run_type="deep_research",
            status="running",
            started_at=stale_time,
            created_at=stale_time,
            updated_at=stale_time,
        )
        container.research_run_repo.save(org_a.id, stale_run)

        # Execute run_once with recover_stale=True
        summary = container.research_worker.run_once(org_id=org_a.id, recover_stale=True)
        assert summary.worker_id is not None

        recovered_run = container.research_run_repo.get_by_id(org_a.id, stale_run.id)
        assert recovered_run is not None
        # Should be recovered to failed
        assert recovered_run.status == "failed"
        assert "stale" in (recovered_run.error_message or "").lower()

    def test_14_idempotency_does_not_create_duplicate_run(self, p30_ctx):
        """14. Idempotency: triggering research on prospect with active run does not create duplicate run."""
        client = p30_ctx["client"]
        container = p30_ctx["container"]
        org_a = p30_ctx["org_a"]
        prospect_a = p30_ctx["prospect_a"]
        headers = p30_ctx["headers_a"]

        # Pre-seed a pending run directly in DB
        now = datetime.now(timezone.utc).isoformat()
        initial_run = ResearchRun(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            prospect_id=prospect_a.id,
            run_type="deep_research",
            status="pending",
            created_at=now,
            updated_at=now,
        )
        container.research_run_repo.save(org_a.id, initial_run)

        # Trigger research via API
        resp = client.post(
            f"/api/v1/prospects/{prospect_a.id}/research",
            json={"run_type": "deep_research"},
            headers=headers,
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["id"] == initial_run.id

        # Total runs for this prospect must still be 1
        all_runs = container.research_run_repo.list_by_organization(org_a.id, prospect_id=prospect_a.id)
        assert len(all_runs) == 1

    def test_15_zero_paid_provider_calls_during_entire_execution(self, p30_ctx):
        """15. Zero Gemini / zero paid provider calls during entire test execution."""
        container = p30_ctx["container"]
        org_a = p30_ctx["org_a"]
        prospect_a = p30_ctx["prospect_a"]

        # Ensure GeminiProspectResearchProvider is never invoked
        with patch.object(
            GeminiProspectResearchProvider,
            "generate_ai_research",
            side_effect=AssertionError("Paid provider Gemini was invoked unexpectedly!"),
        ):
            now = datetime.now(timezone.utc).isoformat()
            run = ResearchRun(
                id=str(uuid.uuid4()),
                organization_id=org_a.id,
                prospect_id=prospect_a.id,
                run_type="deep_research",
                status="pending",
                created_at=now,
                updated_at=now,
            )
            container.research_run_repo.save(org_a.id, run)

            result = container.research_worker.claim_and_execute_run(
                org_id=org_a.id,
                run_id=run.id,
                provider="deterministic",
            )
            assert result is not None
            assert result.prospect_id == prospect_a.id

    def test_16_execution_attempt_fencing_prevents_stale_worker_overwrite(self, p30_ctx):
        """16. Stale worker cannot overwrite terminal state or persist misleading intelligence."""
        container = p30_ctx["container"]
        org_a = p30_ctx["org_a"]
        prospect_a = p30_ctx["prospect_a"]

        now = datetime.now(timezone.utc).isoformat()
        run = ResearchRun(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            prospect_id=prospect_a.id,
            run_type="deep_research",
            status="pending",
            created_at=now,
            updated_at=now,
        )
        container.research_run_repo.save(org_a.id, run)

        # Worker A claims the run
        attempt_a = "worker-attempt-A-12345"
        claimed = container.research_run_repo.claim_run(
            org_id=org_a.id,
            run_id=run.id,
            execution_attempt_id=attempt_a,
            started_at_iso=now,
        )
        assert claimed is not None
        assert claimed.status == "running"
        assert claimed.execution_attempt_id == attempt_a

        # Worker A becomes stale; Recovery marks the run as failed
        recovered = container.research_run_repo.mark_stale_run_failed(
            org_id=org_a.id,
            run_id=run.id,
            error_message="WORKER_EXECUTION_LOST: timeout exceeded",
            completed_at_iso=datetime.now(timezone.utc).isoformat(),
        )
        assert recovered is True

        db_run = container.research_run_repo.get_by_id(org_a.id, run.id)
        assert db_run.status == "failed"
        assert "WORKER_EXECUTION_LOST" in db_run.error_message

        # Worker A resumes and attempts to complete the run
        from bopclients.domain.exceptions import DiscoveryExecutionError

        with pytest.raises(DiscoveryExecutionError):
            container.prospect_research_orchestrator.research_prospect(
                org_id=org_a.id,
                prospect_id=prospect_a.id,
                run_id=run.id,
            )

        # 1. Terminal state must NOT be overwritten (remains failed)
        after_run = container.research_run_repo.get_by_id(org_a.id, run.id)
        assert after_run.status == "failed"
        assert "WORKER_EXECUTION_LOST" in after_run.error_message

        # 2. No misleading intelligence must be persisted
        intel = container.intel_repo.get_latest(org_a.id, prospect_a.id, provider="deterministic")
        assert intel is None

    def test_17_worker_continuous_mode(self, p30_ctx):
        """17. ResearchWorker continuous polling mode processes runs and terminates cleanly."""
        container = p30_ctx["container"]
        org_a = p30_ctx["org_a"]
        prospect_a = p30_ctx["prospect_a"]

        now = datetime.now(timezone.utc).isoformat()
        run = ResearchRun(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            prospect_id=prospect_a.id,
            run_type="deep_research",
            status="pending",
            created_at=now,
            updated_at=now,
        )
        container.research_run_repo.save(org_a.id, run)

        total = container.research_worker.run_continuous(
            batch_size=5,
            poll_interval=0.01,
            org_id=org_a.id,
            max_iterations=2,
        )
        assert total == 1

        db_run = container.research_run_repo.get_by_id(org_a.id, run.id)
        assert db_run.status == "completed"

    def test_18_live_postgres_concurrency_and_fencing(self):
        """18. Live PostgreSQL concurrency: exactly one claim succeeds; terminal state protected."""
        import os
        import threading
        from bopclients.infrastructure.db.connection import create_database_connection
        from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
        from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
        from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository

        pg_url = os.environ.get(
            "BOPCLIENTS_TEST_POSTGRES_URL",
            "postgresql://postgres:postgres@localhost:5433/bopclients_test",
        ).strip()

        try:
            test_conn = create_database_connection(pg_url)
            test_conn.fetch_dicts("SELECT 1")
            test_conn.close()
        except Exception:
            pytest.skip(f"Live PostgreSQL test database not accessible at {pg_url}")

        db_main = create_database_connection(pg_url)
        org_repo = OrganizationRepository(db_main)
        prospect_repo = ProspectRepository(db_main)
        run_repo_main = ResearchRunRepository(db_main)

        org_id = str(uuid.uuid4())
        org = Organization(id=org_id, bop_organization_id=str(uuid.uuid4()), name="PG Tenant", slug=f"pg-tenant-{uuid.uuid4().hex[:8]}")
        org_repo.save(org)

        prospect_id = str(uuid.uuid4())
        prospect = Prospect(id=prospect_id, organization_id=org_id, name="PG Prospect", city="Austin")
        prospect_repo.save_prospect(org_id, prospect)

        now = datetime.now(timezone.utc).isoformat()
        run_id = str(uuid.uuid4())
        run = ResearchRun(
            id=run_id,
            organization_id=org_id,
            prospect_id=prospect_id,
            run_type="deep_research",
            status="pending",
            created_at=now,
            updated_at=now,
        )
        run_repo_main.save(org_id, run)

        # Concurrency Test: Two independent connections compete to claim the same pending run
        results = {}

        def worker_task(worker_name: str):
            conn = create_database_connection(pg_url)
            repo = ResearchRunRepository(conn)
            try:
                claimed = repo.claim_run(
                    org_id=org_id,
                    run_id=run_id,
                    worker_id=worker_name,
                )
                results[worker_name] = claimed
            finally:
                conn.close()

        t1 = threading.Thread(target=worker_task, args=("worker-pg-1",))
        t2 = threading.Thread(target=worker_task, args=("worker-pg-2",))

        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        c1 = results.get("worker-pg-1")
        c2 = results.get("worker-pg-2")

        successful_claims = sum(1 for c in (c1, c2) if c is not None)
        rejected_claims = sum(1 for c in (c1, c2) if c is None)

        assert successful_claims == 1, f"Expected exactly 1 successful claim on Postgres, got {successful_claims}"
        assert rejected_claims == 1, f"Expected exactly 1 rejected claim on Postgres, got {rejected_claims}"

        # Fencing Test on PostgreSQL: Stale execution attempt cannot overwrite failed terminal state
        stale_attempt_id = "stale-attempt-999"
        # Mark failed by recovery
        run_repo_main.mark_stale_run_failed(
            org_id=org_id,
            run_id=run_id,
            error_message="WORKER_LOST_PG",
            completed_at_iso=datetime.now(timezone.utc).isoformat(),
        )
        # Attempt to update with stale attempt ID / status='completed'
        overwritten = run_repo_main.update_status(
            org_id=org_id,
            run_id=run_id,
            status="completed",
            execution_attempt_id=stale_attempt_id,
            expected_status="running",
        )
        assert overwritten is None, "Stale worker was able to overwrite terminal status on Postgres!"

        final_run = run_repo_main.get_by_id(org_id, run_id)
        assert final_run.status == "failed"
        assert final_run.error_message == "WORKER_LOST_PG"
        db_main.close()
