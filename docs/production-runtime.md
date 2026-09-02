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
