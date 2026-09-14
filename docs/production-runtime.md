# BOPCLIENTS PRODUCTION RUNTIME OPERATIONS RUNBOOK

---

## 1. Executive Summary

This document provides complete instructions for operating, configuring, verifying, and troubleshooting the BopClients Continuous Monitoring Worker in production environments.

BopClients runs as a **run-once, stateless monitoring worker process** designed to execute on an external scheduler trigger (such as cron, Cloud Run Jobs, or Kubernetes CronJobs).

---

## 2. Environment Variables & Runtime Settings

Configuration is managed strictly via environment variables parsed by `bopclients.runtime.settings.RuntimeSettings`.

| Variable | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `BOPCLIENTS_ENV` | Yes | `development` | Runtime environment (`development`, `test`, `staging`, `production`). |
| `DATABASE_URL` | Yes | `:memory:` | Database URI connection string. |
| `LOG_LEVEL` | No | `INFO` | Stdlib logging severity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `ENABLED_PUBLIC_SIGNAL_PROVIDERS` | Yes | `official_website` | Comma-separated list of enabled signal providers. |
| `SAM_GOV_API_KEY` | Optional | `""` | API key required if `government_procurement` provider is enabled. |
| `GEMINI_API_KEY` | Optional | `""` | API key required if `gemini` provider is enabled. |
| `PUBLIC_NEWS_BACKEND_URL` | Optional | `""` | Endpoint URL required if `public_news` provider is enabled. |
| `MONITORING_WORKER_BATCH_SIZE` | No | `25` | Number of schedule items fetched per SQL query batch. |
| `MONITORING_WORKER_MAX_ITEMS` | No | `100` | Maximum total due items processed per run. |
| `MONITORING_WORKER_MAX_SECONDS` | No | `600` | Monotonic clock duration limit per run in seconds. |
| `MONITORING_LEASE_DURATION_SECONDS` | No | `300` | Lease claim duration in seconds (5 minutes). |
| `MONITORING_LEASE_RENEW_BEFORE_SECONDS` | No | `90` | Lease threshold for mid-execution heartbeat renewal. |

---

## 3. Database Migration & Schema Versioning

Database migrations are managed explicitly via `bopclients.runtime.db_cli` and tracked in `bopclients_schema_version`.

### Inspect Schema Migration Status
```bash
python -m bopclients.runtime.db_cli status --json
```

### Apply Pending Migrations
```bash
python -m bopclients.runtime.db_cli migrate
```

> **IMPORTANT**: The worker process **never automatically migrates the database schema** at startup in production. Database migrations must be run as a pre-deployment step.

---

## 4. Environment Readiness Check

Before launching the monitoring worker, verify environment readiness:
```bash
python -m bopclients.runtime.readiness_cli --json
```

### Readiness Status Definitions
- **`READY`**: Database reachable, schema version matches expected version (`20260902_001`), core worker operable, all enabled providers configured.
- **`DEGRADED`**: Core worker operable, but one or more optional enabled providers (e.g. `government_procurement` without API key) are unconfigured. The worker will run with available providers and skip unconfigured ones.
- **`NOT_READY`**: Database unreachable, schema version mismatch, or critical setting invalid. **Worker startup will abort with exit code 1**.

---

## 5. Worker Execution Deployment Contract

### Command Line Execution
```bash
python -m bopclients.worker.monitoring_worker_cli \
  --once \
  --batch-size 25 \
  --max-items 100 \
  --max-seconds 600
```

### Dry Run Execution
```bash
python -m bopclients.worker.monitoring_worker_cli --dry-run
```

### Docker Container Run
```bash
docker run --rm \
  --env-file .env \
  bopclients-worker:latest \
  python -m bopclients.worker.monitoring_worker_cli --once
```

---

## 6. Recommended External Scheduler Frequency

The monitoring worker executes on a **run-once** model. It should be triggered by an external scheduler:
- **Recommended Schedule**: Every 5 to 15 minutes.
- **Overlapping Executions**: Safe. Atomic SQL lease claims (`claim_due_work`) and dynamic lease tokens ensure that overlapping worker processes will safely skip already-claimed schedules without race conditions.

---

## 7. Logging & Observability

Standard structured logs are emitted to `stdout`/`stderr`.
Log fields include `timestamp`, `log_level`, `worker_run_id`, `schedule_id`, `organization_id`, `prospect_id`, `status`, and duration metrics. Secrets and raw lease tokens are **never logged**.

---

## 8. Failure Modes & Lease Loss Recovery

- **Handled Item Failures**: Network timeouts or provider HTTP errors update `schedule.failure_count` and compute deterministic backoff next check times (`exit 0`).
- **Mid-Execution Lease Loss**: If Worker B reclaims a lease while Worker A is scanning a provider, Worker A detects `LEASE_OWNERSHIP_LOST`, aborts further scans, skips updating the schedule, updates orphan `ResearchRun` to `failed`, and returns `status = "SKIPPED"` (`exit 0`).
- **Fatal Infrastructure Failures**: Database connection losses abort the worker process with `exit 1`.

---

## 9. Rollback & Backup Guidance

- **Code Rollback**: Redeploy the previous container image. Schedules remain safely stored in the database.
- **Database Backup**: Always take a database snapshot prior to running `db_cli migrate`.

---

## 10. Operation Safety & Boundaries

- **Auto-Executable Operations**: `monitor_public_signals` ONLY.
- **Prohibited Operations**: Cero autonomous outreach, cero email/WhatsApp/SMS messaging, cero automatic Gemini research.

---

## 11. Worker Crash Recovery

When a worker process experiences an abrupt termination (such as an OS crash, container SIGKILL, or OOM kill) mid-execution:

- **Automatic Reconciliation**: On worker startup, `ResearchRunRecoveryService` scans for orphan `ResearchRun` entities in `status = 'running'` started prior to the stale threshold (`RESEARCH_RUN_STALE_AFTER_SECONDS`, default 900s / 15m).
- **Lease-Aware Attempt Correlation**: The recovery service inspects the matching `monitoring_schedules` row. If an active non-expired lease exists **for a newer attempt** (`current_execution_attempt_id != candidate.execution_attempt_id`), candidate Attempt A is safely reconciled to `failed` (`WORKER_EXECUTION_LOST`) while newer Attempt B continues executing untouched.
- **No Schedule Penalty**: Reconciling an orphan run **does NOT increment `schedule.failure_count`**, apply backoff, or alter schedule priority/`next_check_at`. The schedule remains due for normal re-attempt.
- **Idempotent Provider Deduplication**: Re-execution of provider scans during worker retry may re-invoke external API calls, but persisted `SignalObservation` entities are deduplicated by `semantic_event_key`.
- **Side-Effect Boundary**: There is no distributed exactly-once guarantee for external HTTP provider calls; in-flight external API calls prior to a crash cannot be cancelled externally.

---

## 12. Distributed Rate Limiting, Provider Budgets & Backpressure (P14)

### Provider Call Granularity & Unit of Measurement
- **RATE LIMIT UNIT: `PROVIDER_EXECUTION`**, not individual raw HTTP TCP requests.
- Each acquired token represents one complete provider execution attempt.
- For `official_website`, a single provider execution safely fetches 1 homepage and up to 5 same-site candidate subpages ($1 \le N \le 6$ bounded HTTP requests).
- Redirect hops ($M \le 3$) and hidden transport behaviors are internal to the HTTP boundary and are not separately metered.
- Therefore, P14 provides distributed protection on provider execution rate, **NOT exact outbound HTTP request accounting**.
- For `government_procurement` (SAM.gov Opportunities v2), each execution issues exactly 1 HTTP GET request.
- For `gemini` (manual execution only), each execution issues 1 REST API call.

### Canonical Provider Keys
The system enforces strict, canonical provider keys across all domain policies, repositories, guards, and workers:
- `official_website`: Prospect website and subpage scanning.
- `government_procurement`: SAM.gov Opportunities Public API v2.
- `public_news`: Curated corporate news and press releases.
- `gemini`: LLM-assisted prospect research (manual-only, never autonomous).

### Database-Coordinated Concurrency & Windows
- Multi-worker deployments coordinate provider invocations via PostgreSQL tables `provider_rate_limit_state` and `provider_rate_limit_leases` (using `SELECT ... FOR UPDATE` row locks).
- In SQLite development / single-worker environments, transactions serialize slot reservations without additional infrastructure.
- **Execution-Level Metrics**: Fixed window progress is tracked via `execution_count` (persisted column) against `policy.max_executions`.
- **Natural Lease Expiration**: In-flight provider slots are guarded by concurrency leases (`expires_at = now + lease_duration`). If a worker crashes mid-request, subsequent workers naturally clean up expired leases (`cleanup_expired_leases`) and acquire slots without deadlock.
- **Stale Token Protection**: Concurrency leases are released by explicit `lease_token` (UUID). Stale or mismatched tokens cannot release active leases owned by other workers. Lease tokens are never exposed in operational logs or telemetry.

### Scoping Strategy & Multi-Tenant Capacity
- **Per-Host Scoping**: Web scraping (`official_website`) is scoped per domain (`host:{netloc}`). Saturated rate limits on one target prospect do not throttle or impede scans on other domains.
- **Global Provider Scoping**: Third-party APIs (`government_procurement`, `gemini`, `public_news`) share global capacity across all tenants (`global:{provider_key}`).
- **Fairness & Shared Capacity Warning**: Global scopes provide **GLOBAL MULTI-TENANT SHARED CAPACITY**, not fair queueing or round-robin tenant scheduling. A high-activity tenant can consume the shared request quota within a window, causing backpressure deferrals (`SKIPPED_RATE_LIMITED`) on other tenants until the window resets (noisy-tenant starvation limitation).

### Application-Side Execution Safety Defaults
Default window limits:
- `official_website`: 30 provider executions / 60s
- `government_procurement`: 10 provider executions / 60s
- `gemini`: 15 provider executions / 60s
- `public_news`: disabled
These are **APPLICATION-SIDE EXECUTION SAFETY DEFAULTS** designed to protect upstream infrastructure and ensure stability, NOT provider-published HTTP quotas.

### Structured Dynamic Cooldown & Retry-After
- HTTP 429 and 503 responses are captured structurally via `ProviderThrottleFeedback` (`http_status`, `retry_after`, `error_type`) emitted directly by provider adapters.
- Free-form human warning strings are **NEVER parsed or regex-matched** for cooldown decision control flow.
- Bounded `Retry-After` parsing supports both decimal seconds and RFC 7231 / 1123 HTTP dates, capped between a minimum floor and maximum ceiling (default 3600s).
- Cooldown deadlines are committed immediately to the database, propagating instant backpressure across all active workers.
- HTTP 403 Forbidden and network timeouts do NOT set cooldowns, preventing improper lockout on access denied errors.

### Backpressure Deferral without Penalty
- When all enabled providers for a schedule are throttled (`RATE_LIMITED`, `CONCURRENCY_LIMITED`, or `COOLDOWN_ACTIVE`), execution status is set to `SKIPPED_BACKPRESSURE`.
- **Failure Count Preservation**: `failure_count` is **not incremented**, preventing premature schedule suspension.
- **Non-blocking Rescheduling**: `next_check_at` is deferred to `retry_not_before`, eliminating hot-looping or `time.sleep` blocking in workers.
- The associated `ResearchRun` completes cleanly with `skipped_backpressure` metadata.

### Worker Run Budgets
- Workers support `max_provider_calls_per_run` budget limits with hard pre-call guards (`ProviderCallBudget`).
- Call budgets are verified **before** invoking provider network calls. In multi-provider schedules, if the budget is reached mid-schedule, remaining providers are skipped cleanly with `SKIPPED_BUDGET_EXHAUSTED` and never make network calls.
- When the worker-level budget is reached, workers exit cleanly with `PROVIDER_BUDGET_EXHAUSTED` and report structured observability metrics (`provider_calls_attempted`, `provider_calls_executed`, `provider_rate_limited`, `provider_concurrency_limited`, `provider_cooldown_skips`, `provider_budget_skips`).

---

## 13. Tenant Fairness, Provider Capacity Allocation & Worker Scheduling Policy (P15 / P15.1)

### Bounded Best-Effort Tenant Interleaving
- **Interleaved Scheduler Ordering**: Worker schedule selection (`list_due_system`) partitions due active schedules by `organization_id` using SQL window functions (`ROW_NUMBER() OVER (PARTITION BY organization_id ORDER BY next_check_at ASC, prospect_id ASC, id ASC) AS tenant_round`).
- Global schedule ordering is prioritized by `tenant_round ASC, next_check_at ASC, organization_id ASC, prospect_id ASC, id ASC`.
- **Query Limit Pushdown**: The SQL query applies `LIMIT` directly at the database engine level (`LIMIT ?`), preventing wasteful materialization of entire backlog tables into application memory.
- **Index Support & Engine Work**: Existing indexes (`idx_schedules_org_due`, `idx_schedules_lease`) assist due-row filtering; the database engine may still perform WindowAgg/sort for tenant ranking.
- **Elimination of Monopolistic Starvation**: If Organization A has 10,000 due schedules and Organization B has 2 due schedules, Organization B is selected in Round 1 and Round 2 alongside Organization A, eliminating deep-backlog starvation.
- **Scheduler Work-Conservation**: For schedule selection, the scheduler is strictly **work-conserving**. If only Organization A has due runnable work, the batch is fully utilized by Organization A up to `batch_size` / `max_items`.

### Static Tenant Provider Capacity Truth (NOT Work-Conserving)
- **Static Per-Org Cap**: For shared global providers (e.g. `government_procurement`), policy defines `per_organization_max_executions` alongside `max_executions`.
- **Not Work-Conserving**: Provider capacity allocation is **NOT work-conserving**. If only Organization A is active and exhausts its 4 executions within a window, the remaining 6 global executions remain idle until window reset. This is an explicit, intentional product safety tradeoff to prevent a single tenant from exhausting external provider allowances.
- **No Shared Overflow Allocator**: Unused capacity does not dynamically spill over to active tenants in P15.
- **Deterministic Lock Ordering**: When locking both `global:<provider>` and `org:<uuid>:<provider>`, scope keys are sorted lexicographically (`scopes_to_lock.sort()`) prior to acquiring PostgreSQL row locks (`SELECT ... FOR UPDATE`), preventing AB-BA deadlocks for this dual-bucket lock path under the tested locking protocol.
- **Zero Partial Counter Consumption**: Slot acquisition evaluates both global and tenant capacity atomically. If tenant capacity is exhausted, global counters are NOT incremented and `TENANT_CAPACITY_LIMITED` is returned. If global capacity is exhausted, tenant counters are NOT incremented and `RATE_LIMITED` is returned.
- **Deterministic Retry-Not-Before**: Tenant capacity rejection deterministically returns `retry_not_before = tenant_window_start + window_seconds`.

### Commercial Priority Interaction
- **P15 is Organization-Level Fairness**: Commercial priority is NOT replaced or directly re-ranked inside the fair scheduler SQL query.
- **Upstream Cadence Governance**: Commercial priority (P6 / P9) influences monitoring cadence (`recommended_interval_days`) and sets `next_check_at`. Higher-priority prospects run more frequently and become due earlier.
- **Same-Tenant Selection**: Within the same organization, due schedules are ordered by `next_check_at ASC, prospect_id ASC, id ASC`. Whichever schedule has an earlier `next_check_at` is evaluated first.
- **Cross-Tenant Priority Isolation**: An urgent schedule in Organization A does not push Organization A's secondary items ahead of Organization B's or C's first-round candidates. Round 1 always selects one due schedule from each tenant who has runnable work.

### Operational Backpressure & Failure Count Isolation
- When an organization hits its allocated provider capacity, the provider call returns `TENANT_CAPACITY_LIMITED` (`SKIPPED_TENANT_CAPACITY_LIMITED`).
- **No Commercial Failure**: Schedule `failure_count` is **not incremented**.
- **Non-blocking Rescheduling**: `schedule.next_check_at` is deferred to `retry_not_before`, allowing other organizations with available capacity to execute without worker sleep or busy-wait loops.
- **Run-Budget Precedence**: Worker run-level budgets (`ProviderCallBudget`) are evaluated prior to database acquisition attempts.
- **Observability**: Metrics track `provider_tenant_capacity_limited` independently from `provider_rate_limited`.

### Fairness Guarantees & Constraints
- P15 provides **BOUNDED BEST-EFFORT TENANT FAIRNESS**, NOT strict mathematical fair queueing, pricing-tier weighted shares, or latency SLAs.
- There is no distributed queue, broker, or external Redis quota service. Coordination relies strictly on atomic transactional PostgreSQL tables (`provider_rate_limit_state` and `provider_rate_limit_leases`).
- **Remaining Operational Risks**:
  1. Bounded best-effort fairness, not strict mathematical fairness SLA.
  2. Scheduler fairness is work-conserving; provider per-org capacity is a static cap that may leave global capacity unused.
  3. No shared overflow allocator or dynamic tier weighting.
  4. Concurrent worker timing races can produce temporary round imbalances.
  5. Sequential item processing per worker process (no internal parallel execution threads per worker).
  6. Coordination applies only across worker instances sharing the same PostgreSQL database.
  7. Rate limit enforcement operates at provider-execution granularity, not raw HTTP request granularity.
  8. External HTTP requests in-flight cannot be cancelled mid-request.

---

## 14. Production Scheduler, Job Dispatch & Deployment Operations (P16)

### Run-Once Scheduler Contract
`ProductionScheduler` operates on a deterministic **run-once tick contract** rather than an internal infinite sleep loop:
- External process supervisors (such as Kubernetes CronJobs, systemd timers, Cloud Run Jobs, or AWS EventBridge scheduled tasks) invoke one tick periodically.
- Each tick acquires the distributed scheduler lease, reconciles stale runs, optionally launches a single `MonitoringWorker.run()`, persists execution outcomes to `scheduler_runs`, releases the lease, and terminates with an explicit exit code.
- This model cleanly aligns with modern cloud container architectures, prevents unmonitored zombie background loops, and facilitates transparent logging and monitoring.

### Distributed Scheduler Dispatch Lease
- Coordination is enforced via PostgreSQL table `scheduler_dispatch_state` using `SELECT ... FOR UPDATE` row locks keyed by `scheduler_key` (canonical key: `monitoring_worker`).
- In SQLite development / single-worker environments, transactions serialize dispatch attempts without distributed guarantees.
- **Amplification Prevention**: The scheduler lease prevents overlapping dispatch invocations from multiple replicas or rapid cron triggers from launching redundant worker processes simultaneously.
- **Separation of Concerns**:
  - The scheduler lease coordinates **PROCESS DISPATCH**.
  - Monitoring schedule claims (`claim_due_work`) in `monitoring_schedules` remain the final, authoritative correctness boundary for individual prospect schedule execution.
- **Ownership Token Protection**: The lease token is a cryptographically random UUID generated per tick. Lease tokens are **never written to logs or telemetry**. Stale tokens cannot renew or release leases owned by newer dispatchers.

### State vs History Architecture (ACQUIRED_DISPATCH_ONLY Model)
- **`scheduler_dispatch_state`**: Single-row-per-key tracking current lease ownership (`lease_token`, `lease_expires_at`, `current_run_id`), latest execution timestamps, and last terminal status.
- **`scheduler_runs`**: Append-only operational audit trail recording dispatches that acquired the lease and ran (`id`, `scheduler_key`, `started_at`, `completed_at`, `status`, `worker_run_id`, `worker_stopped_reason`, items attempted/claimed, success/failure/backpressure counts, error codes, and messages).
- **Run History Policy (`ACQUIRED_DISPATCH_ONLY`)**:
  - `scheduler_runs` records ONLY ticks where the distributed lease was successfully acquired (`COMPLETED`, `FAILED`, `OWNERSHIP_LOST`).
  - Safe skips (`SKIPPED_LEASE_HELD`, `SKIPPED_DISABLED`, `DATABASE_NOT_READY`) do NOT insert rows into `scheduler_runs`, keeping audit logs lean and eliminating unbounded growth from high-frequency cron ticks.

### Autonomous Heartbeat & Thread-Safe Concurrency
- `SchedulerHeartbeat` runs on an **autonomous background thread** (`BACKGROUND_THREAD` architecture) rather than relying solely on loop boundaries.
- **Continuous Lease Protection**: Even if `MonitoringWorker.run()` is blocked in slow upstream provider I/O (e.g. multi-second HTTP requests or web scrapes), the daemon thread continuously monitors expiration and renews the lease in PostgreSQL / SQLite before `renew_before_seconds` expires.
- **Thread Safety & Database Connection Isolation**:
  - **PostgreSQL**: Concurrent queries on a single connection are prohibited by `psycopg`. The heartbeat thread uses a dedicated, thread-isolated database connection opened via `db_factory`.
  - **SQLite File Mode**: The heartbeat thread uses its own dedicated SQLite connection (separate from the main scheduler connection) pointing to the same persistent `.db`/`.sqlite` database file with WAL journal mode (`PRAGMA journal_mode=WAL`).
  - **SQLite `:memory:` Mode**: In-memory SQLite is a test-only, single-process environment without distributed coordination. Because separate `:memory:` connections open independent blank databases, in-memory tests safely fall back to sharing the single connection guarded by `_write_lock` and `check_same_thread=False`. Production deployments require PostgreSQL or persistent SQLite file mode.
  - **Thread Shutdown & Join Contract**: The heartbeat thread checks `_stop_event` immediately before and after every renewal query. Upon scheduler completion or context manager exit, `stop()` sets `_stop_event`, cleanly joins the thread (`thread.is_alive() == False`), and closes dedicated connections exactly once without connection leakage. No renewals occur post-stop.
- **Ownership Loss Detection & Graceful Halting**:
  - If the lease is stolen or expired and reclaimed by another dispatcher during a blocked worker operation, the background thread detects ownership loss immediately.
  - In-flight HTTP requests are allowed to complete cleanly without hard aborts or corrupted state.
  - `heartbeat.should_stop_callback()` signals cooperative shutdown, preventing the worker from claiming any subsequent schedules.
  - The stale owner never clears the competing owner's lease on shutdown and records final status as `OWNERSHIP_LOST`.
  - Zero token exposure: Lease tokens are never revealed in logs, exceptions, or audit metadata.

### Stale Scheduler Run Recovery
- On every scheduler tick, `reconcile_stale_runs` evaluates orphan records in `scheduler_runs` with `status = 'RUNNING'` started before `scheduler_recovery_stale_after_seconds` (default: 900s / 15m).
- **Lease Correlation Guard**: If `scheduler_dispatch_state` indicates that an active, non-expired lease is currently held by that exact run (`current_run_id == candidate.id`), the run is **skipped and protected**.
- If the lease has expired or belongs to a different dispatcher, the stale run is safely terminalized to `FAILED` with error code `SCHEDULER_EXECUTION_LOST`.
- Tenant schedules are never penalized by scheduler recovery passes (`failure_count` remains untouched).

### Operational Exit Code Matrix

| CLI Exit Code | Scheduler Status | Condition / Context |
| :---: | :--- | :--- |
| **0** | `COMPLETED` | Worker finished processing items, or returned `NO_DUE_WORK` / backpressure. Normal execution. |
| **0** | `SKIPPED_LEASE_HELD` | Another scheduler tick currently owns the dispatch lease. Overlapping execution safely skipped. |
| **0** | `SKIPPED_DISABLED` | Scheduler is disabled in configuration (`PRODUCTION_SCHEDULER_ENABLED=false`) and `--force` was not provided. |
| **0** | Check Passed | `scheduler_cli --check` completed successfully with `READY` or `DEGRADED` status. |
| **1** | `FAILED` | Fatal database/schema error, unhandled worker exception, or check failure (`NOT_READY`). |
| **130** | Interrupted | Process received termination signal (`SIGINT`, `SIGTERM`, `KeyboardInterrupt`). Best-effort lease release performed. |

### Recommended Scheduler Cadence
- **Recommended Schedule**: Every **2 to 5 minutes**.
- **Explanation**: A prospect's `next_check_at` dictates *when* actual work should take place. The scheduler frequency only dictates *polling latency*—how soon after becoming due a schedule will be picked up. Cadence of 2–5 minutes offers responsive detection while keeping resource usage minimal.

### Signal Handling & Graceful Shutdown
- The CLI captures POSIX `SIGINT`, `SIGTERM`, and Windows `KeyboardInterrupt`.
- Upon receipt of a termination signal, the runner triggers `worker.request_stop()` so the worker finishes its current in-flight item boundary cleanly before exiting.
- If the scheduler process owns the active lease, it performs a best-effort release of the lease token upon shutdown so subsequent ticks are not unnecessarily blocked until lease expiration.

### Operator Runbook

#### 1. Inspect Database Schema & Run Migrations
```bash
# Check current schema version
python -m bopclients.runtime.db_cli status --json

# Apply migrations up to 20260902_006
python -m bopclients.runtime.db_cli migrate
```

#### 2. Run Environment Readiness & Scheduler Validation
```bash
# Full environment readiness check
python -m bopclients.runtime.readiness_cli --json

# Scheduler pre-flight check (read-only, 0 mutations)
python -m bopclients.runtime.scheduler_cli --check

# Dry-run scheduling inspection (read-only, 0 mutations)
python -m bopclients.runtime.scheduler_cli --dry-run
```

#### 3. Inspect Scheduler Lease via SQL (Safe Projection)
```sql
-- Safe operator inspection: NEVER project lease_token or internal ownership secrets
SELECT
    scheduler_key,
    lease_expires_at,
    current_run_id,
    last_started_at,
    last_completed_at,
    last_status,
    updated_at
FROM scheduler_dispatch_state;
```

#### 4. Execute Production Scheduler Tick
```bash
# Order of execution: operator migration -> readiness verification -> scheduler tick
# Note: The scheduler tick NEVER automatically migrates the database schema.

# Single production scheduler tick (standard invocation)
python -m bopclients.runtime.scheduler_cli

# Single scheduler tick with JSON output
python -m bopclients.runtime.scheduler_cli --json

# Single scheduler tick bypassing disabled flag (strictly enforces lease)
python -m bopclients.runtime.scheduler_cli --force
```

### Generic Process Supervisor Patterns

#### Option A: Kubernetes CronJob
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: bopclients-scheduler
spec:
  schedule: "*/2 * * * *"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: scheduler
              image: bopclients-worker:latest
              command: ["python", "-m", "bopclients.runtime.scheduler_cli"]
              envFrom:
                - secretRef:
                    name: bopclients-secrets
```

#### Option B: systemd Timer (Linux Host)
`/etc/systemd/system/bopclients-scheduler.service`:
```ini
[Unit]
Description=BopClients Production Scheduler Tick
After=network.target

[Service]
Type=oneshot
User=bopuser
WorkingDirectory=/opt/dataforge
ExecStart=/opt/dataforge/.venv/bin/python -m bopclients.runtime.scheduler_cli
EnvironmentFile=/etc/bopclients.env
```

`/etc/systemd/system/bopclients-scheduler.timer`:
```ini
[Unit]
Description=Run BopClients Scheduler every 2 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=2min
Persistent=true

[Install]
WantedBy=timers.target
```

### Remaining Operational Risks
1. **Accidental Overlap vs Correctness Boundary**: The scheduler lease prevents accidental deployment amplification and overlapping runs, but schedule claims in `monitoring_schedules` remain the final correctness boundary.
2. **No Distributed Queue / Broker**: Dispatches occur synchronously per tick; there is no Celery/RabbitMQ/Redis queue buffering jobs.
3. **Single Worker Process per Tick**: By default, each tick invokes a single worker instance (`max_parallel_dispatches = 1`).
4. **Sequential Processing per Worker**: Each worker executes candidate items sequentially; internal processing is single-threaded.
5. **Database-Scoped Coordination**: Distributed scheduler coordination applies only across instances sharing the same PostgreSQL database. Different databases are not coordinated.
6. **Append-Only History Growth**: `scheduler_runs` grows append-only; an operational retention or archival policy must be implemented in future phases.
7. **No Outbound Exactly-Once Guarantee**: External HTTP provider requests are not transactional and cannot be cancelled mid-flight if a crash occurs during a provider scan.
8. **Serverless Limitations**: Workers running against large backlogs may exceed short execution limits (e.g. AWS Lambda 15-minute ceiling); containerized jobs or VMs are required.
9. **No Production Cloud Deployment**: P16 establishes deployable runtime contracts, but live production deployment to cloud infrastructure has not been performed.
