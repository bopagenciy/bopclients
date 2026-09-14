# Bop Platform Integration Outbox Dispatcher & Transport Delivery Runtime

**Version:** 1.0.0 (Phase P18)
**Status:** Operational Specification & Architecture Guide
**Scope:** Outbound delivery execution layer for canonical Bop Platform integration events.

---

## 1. Architectural Architecture & Core Invariants

Phase P18 introduces the outbound delivery execution layer, connecting the canonical transactional outbox (`bop_integration_outbox` from P17) to external HTTP webhooks and target application endpoints without tight runtime coupling.

```text
+---------------------------------------------------------------------------------------+
| Local BopClients Transaction Boundary                                                |
|                                                                                       |
|  [Business Operations] ---> [bop_integration_outbox (status='PENDING')]               |
+------------------------------------------+--------------------------------------------+
                                           |
                                           v
+---------------------------------------------------------------------------------------+
| Phase 1: Routing Expansion (IntegrationOutboxDispatcher)                             |
|                                                                                       |
|  Query subscriptions: bop_integration_subscriptions + bop_integration_destinations    |
|  - Zero Subscriptions: Outbox -> FAILED (last_error_code='NO_SUBSCRIBED_DESTINATIONS')|
|  - Matched Subscriptions: Fan-out into bop_integration_deliveries (1 per destination) |
+------------------------------------------+--------------------------------------------+
                                           |
                                           v
+---------------------------------------------------------------------------------------+
| Phase 2: Distributed Claiming & Transport Execution                                  |
|                                                                                       |
|  - Concurrency Lock: SELECT ... FOR UPDATE SKIP LOCKED (Postgres) / atomic lease (SQL)|
|  - Delivery Status: PENDING / RETRY_PENDING -> CLAIMED (claim_token, lease_expires_at)|
|  - Transport: HttpWebhookTransport POST (immutable envelope_json, headers, HMAC)      |
|  - Attempt History: bop_integration_delivery_attempts logged for every execution       |
|  - State Transition:                                                                  |
|      * 2xx -> DELIVERED (if all deliveries DELIVERED, outbox -> PUBLISHED)            |
|      * 429/5xx -> RETRY_PENDING (bounded exponential backoff or Retry-After)           |
|      * 4xx / max attempts exceeded -> DEAD_LETTER (outbox -> FAILED)                  |
+---------------------------------------------------------------------------------------+
```

### Core Invariants
1. **At-Least-Once Delivery:** The system guarantees at-least-once delivery to all active subscriptions. Exactly-once delivery across network boundaries is impossible; downstream consumers must remain idempotent.
2. **Event vs. Delivery Separation:** The outbox event remains the immutable source of truth. Delivery attempts, retries, worker tokens, and status transitions occur per-destination in `bop_integration_deliveries`.
3. **Envelope Immutability:** `envelope_json` is never mutated, modified, or rewritten.
4. **Zero-Subscription Fail-Closed Policy:** Events with no registered subscriptions are marked `FAILED` with error code `NO_SUBSCRIBED_DESTINATIONS`. They are never silently marked `PUBLISHED`.
5. **Multi-Tenant Isolation:** Destinations and subscriptions are strictly partitioned by `bop_organization_id`. Cross-tenant subscriptions are rejected at repository and routing layers.
6. **No External Broker Requirement:** Delivery execution is managed via database-backed claiming and transactional guarantees. No Kafka, RabbitMQ, or Celery required.

---

## 2. Database Schema (Migration `20260902_008`)

Phase P18 adds tables 27–30 to the canonical schema:

### 1. `bop_integration_destinations`
- `id` (VARCHAR(36) PRIMARY KEY)
- `bop_organization_id` (VARCHAR(36) NOT NULL)
- `target_app_id` (VARCHAR(50) NOT NULL)
- `destination_name` (VARCHAR(100) NOT NULL)
- `transport_type` (VARCHAR(20) NOT NULL DEFAULT 'HTTP')
- `endpoint_url` (VARCHAR(500) NOT NULL)
- `secret_key_ref` (VARCHAR(100) NULL)
- `headers_template_json` (TEXT NULL)
- `is_active` (BOOLEAN NOT NULL DEFAULT true)
- `created_at` (VARCHAR(50) NOT NULL)
- `updated_at` (VARCHAR(50) NOT NULL)

### 2. `bop_integration_subscriptions`
- `id` (VARCHAR(36) PRIMARY KEY)
- `bop_organization_id` (VARCHAR(36) NOT NULL)
- `destination_id` (VARCHAR(36) NOT NULL FK -> destinations)
- `event_type` (VARCHAR(100) NOT NULL)
- `is_active` (BOOLEAN NOT NULL DEFAULT true)
- `created_at` (VARCHAR(50) NOT NULL)

### 3. `bop_integration_deliveries`
- `id` (VARCHAR(36) PRIMARY KEY)
- `event_id` (VARCHAR(36) NOT NULL)
- `destination_id` (VARCHAR(36) NOT NULL FK -> destinations)
- `bop_organization_id` (VARCHAR(36) NOT NULL)
- `status` (VARCHAR(20) NOT NULL DEFAULT 'PENDING')
- `attempt_count` (INTEGER NOT NULL DEFAULT 0)
- `max_attempts` (INTEGER NOT NULL DEFAULT 5)
- `next_attempt_at` (VARCHAR(50) NOT NULL)
- `claim_token` (VARCHAR(64) NULL)
- `claim_expires_at` (VARCHAR(50) NULL)
- `delivered_at` (VARCHAR(50) NULL)
- `last_error_code` (VARCHAR(50) NULL)
- `last_error_message` (VARCHAR(500) NULL)
- `created_at` (VARCHAR(50) NOT NULL)
- `updated_at` (VARCHAR(50) NOT NULL)
- *UNIQUE constraint on `(event_id, destination_id)`*

### 4. `bop_integration_delivery_attempts`
- `id` (VARCHAR(36) PRIMARY KEY)
- `delivery_id` (VARCHAR(36) NOT NULL FK -> deliveries)
- `attempt_number` (INTEGER NOT NULL)
- `started_at` (VARCHAR(50) NOT NULL)
- `finished_at` (VARCHAR(50) NOT NULL)
- `status` (VARCHAR(20) NOT NULL)
- `status_code` (INTEGER NULL)
- `error_code` (VARCHAR(50) NULL)
- `error_message` (VARCHAR(500) NULL)
- `response_body_sample` (VARCHAR(1000) NULL)

---

## 3. Distributed Claiming & Concurrency Safety

To enable multiple publisher worker instances to scale horizontally without duplicate deliveries:
- **PostgreSQL Claim Query:**
  ```sql
  SELECT id FROM bop_integration_deliveries
  WHERE (
      (status IN ('PENDING', 'RETRY_PENDING') AND next_attempt_at <= :now AND (claim_expires_at IS NULL OR claim_expires_at <= :now))
      OR (status = 'CLAIMED' AND claim_expires_at IS NOT NULL AND claim_expires_at <= :now)
  )
  ORDER BY next_attempt_at ASC, created_at ASC
  LIMIT :batch_size
  FOR UPDATE SKIP LOCKED;
  ```
- **Stale Owner Guard:**
  When a worker attempts to update status upon completion or failure, the SQL requires `WHERE id = :id AND claim_token = :token`. If a worker's lease expired and the item was reclaimed by another worker, the stale worker's write is rejected (affecting 0 rows).

---

## 4. Operator Runbook & CLI Usage

### Running Publisher Worker Once
```powershell
# Run a single batch cycle
python -m bopclients.runtime.integration_publisher_cli --run-once

# Run with custom batch size and output structured JSON
python -m bopclients.runtime.integration_publisher_cli --run-once --batch-size 50 --json

# Run restricted to a specific tenant
python -m bopclients.runtime.integration_publisher_cli --run-once --tenant 29f36965-6da0-4a44-a3f9-0000b902324b
```

### Inspecting Delivery Dead Letters via SQL
```sql
SELECT d.id, d.event_id, dest.destination_name, d.attempt_count, d.last_error_code, d.last_error_message
FROM bop_integration_deliveries d
JOIN bop_integration_destinations dest ON d.destination_id = dest.id
WHERE d.status = 'DEAD_LETTER'
ORDER BY d.updated_at DESC
LIMIT 20;
```

### Inspecting Delivery Attempt Audit Log
```sql
SELECT attempt_number, started_at, finished_at, status, status_code, error_code, response_body_sample
FROM bop_integration_delivery_attempts
WHERE delivery_id = :delivery_id
ORDER BY attempt_number ASC;
```

---

## 5. Configuration Settings Reference

| Setting Key | Environment Variable | Default | Description |
|---|---|---|---|
| `integration_publisher_enabled` | `INTEGRATION_PUBLISHER_ENABLED` | `false` | Enable/disable integration publishing worker |
| `integration_batch_size` | `INTEGRATION_BATCH_SIZE` | `25` | Maximum delivery rows processed per batch sweep |
| `integration_claim_lease_seconds`| `INTEGRATION_CLAIM_LEASE_SECONDS`| `60` | Claim lock duration before considered stale |
| `integration_max_runtime_seconds`| `INTEGRATION_MAX_RUNTIME_SECONDS`| `300` | Bounded maximum execution time per batch |
| `integration_http_connect_timeout`| `INTEGRATION_HTTP_CONNECT_TIMEOUT`| `5.0` | HTTP connect timeout in seconds |
| `integration_http_read_timeout` | `INTEGRATION_HTTP_READ_TIMEOUT` | `10.0` | HTTP read/response timeout in seconds |
| `integration_max_attempts` | `INTEGRATION_MAX_ATTEMPTS` | `5` | Maximum delivery attempts before DEAD_LETTER |
| `integration_allow_insecure_http`| `INTEGRATION_ALLOW_INSECURE_HTTP`| `false` | Dev/test only flag to permit unencrypted HTTP |

---

## 6. Security Architecture & SSRF Hardening (P18.1)

### Credential Safety
- **No Raw Secrets in Database:** Database columns store only indirect credential references (e.g. `credential_reference = "BOP_DESTINATION_ACME_SECRET"`). Neither `secret_token`, raw HMAC keys, nor Bearer tokens are persisted to any database table or log file.
- **Secret Resolver Abstraction:** At runtime, `IntegrationSecretResolver` resolves the credential reference directly from the process environment (`EnvIntegrationSecretResolver`) or test fixture (`FakeIntegrationSecretResolver`).
- **Headers Sanitization:** Persisted custom headers (`headers_template_json`) reject sensitive headers such as `Authorization`, `Proxy-Authorization`, `Cookie`, `Set-Cookie`, `X-Api-Key`, and other authentication variants.
- **URL Credential Stripping:** URLs containing embedded credentials (`https://user:password@host/`) are strictly rejected.

### SSRF Protection Policy
- **Protocol Allowlist:** `https://` is required by default. Insecure `http://` is strictly prohibited in production and requires explicit dev-only configuration (`INTEGRATION_ALLOW_INSECURE_HTTP=true`).
- **Private IP & Host Blacklist:** Requests to `localhost`, `127.0.0.0/8`, `::1`, `0.0.0.0/8`, RFC 1918 private IPv4 addresses (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), RFC 4193 unique local IPv6 addresses, link-local addresses (`169.254.0.0/16`), and cloud metadata IP (`169.254.169.254`) are validated and rejected prior to connection.
- **Redirects Disabled:** HTTP transport enforces `follow_redirects=False` to prevent redirect-based SSRF circumvention.
- **TLS Verification:** TLS certificate verification is permanently enabled (`verify=True`).

### Replay-Resistant HMAC Signatures
- **Deterministic Signature:** For destinations configuring a `secret_key_ref`, outbound requests carry headers:
  - `X-Bop-Timestamp`: Unix epoch timestamp string.
  - `X-Bop-Signature-256`: `sha256=<hex>` computed over `<timestamp>.<raw_envelope_json>` using the resolved HMAC secret.

### Response Data Minimization & Body Sanitization
- **Body Snippet Sanitization:** `response_body_sample` is limited to 500 characters and stripped of API keys, bearer tokens, passwords, and cookies.
- **Response Headers:** `Set-Cookie` and authorization headers are never logged or stored.
- **Retry-After Parsing:** Supports both RFC integer seconds and HTTP-date formats, safely bounded between 1 second and 1 hour.

---

## 7. Socket-Level Binding, Credential Sanitization & Audit Preservation (P18.2)

### SSRF DNS Rebinding / TOCTOU Elimination
- **Socket Connection-Time IP Validation:** Preflight DNS validation alone is vulnerable to DNS rebinding (TOCTOU) attacks where an external attacker configures a fast-flux DNS server returning a public IP during preflight and a loopback/private IP (`127.0.0.1`, `169.254.169.254`) during HTTP connection.
- **`SafeSyncBackend` Enforcement:** BopClients implements a custom `httpcore` synchronous network backend (`SafeSyncBackend`). During socket connection (`connect_tcp`), DNS resolution is executed immediately before connection, all returned candidate addresses are inspected against the SSRF policy, and the socket connects directly to the validated IP address while preserving the original `server_hostname` for TLS SNI and certificate validation.

### Header Template Value Validation & CRLF Injection Prevention
- Persisted destination headers (`headers_template_json`) validate both header names and values.
- Rejects header values containing credential-like patterns (`Bearer `, `Basic `, `api_key=`, `secret=`, `password=`, `access_token=`).
- Rejects CR/LF characters (`\r`, `\n`) in both header keys and values to protect against HTTP header injection.

### Delivery & Attempt Audit Preservation (Foreign Key Restrict)
- The foreign key from `bop_integration_deliveries.destination_id` to `bop_integration_destinations(id)` is defined as `ON DELETE RESTRICT` (instead of `CASCADE`).
- Historical delivery and delivery attempt audit records can never be accidentally purged by deleting a destination. Deactivating a destination (`is_active = false`) preserves the complete audit trail while stopping future routing.

### Worker Diagnostic ID vs Unpredictable Claim Token
- CLI `--worker-id` serves solely as an operator-controllable diagnostic instance label.
- Distributed claim tokens (`claim_token`) are generated internally as unpredictable UUID v4 strings, eliminating external claim token injection or collision.

### Inactive Destination Dispatch Semantics
- Inactive or deleted destinations encountered during delivery dispatch transition immediately to `DEAD_LETTER` with `last_error_code="DESTINATION_INACTIVE"` without executing any network calls and with `attempt_count = 0` retained intact.

### URL Query Parameter Sanitization
- All error and exception reporting (`sanitize_error_message`) redacts credential query parameters in URLs (e.g. `?api_key=***`, `&token=***`, `?password=***`).

---

## 8. Secret-Reference Isolation & Pre-Commit Hardening (P18.3)

### Secret Reference Namespace Isolation
- Destination `secret_key_ref` is strictly isolated to prevent destinations from referencing arbitrary environment variables (e.g. `DATABASE_URL`, `OPENAI_API_KEY`, `AWS_SECRET_ACCESS_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `POSTGRES_PASSWORD`).
- Canonical Pattern: `^BOP_INTEGRATION_SECRET_[A-Z0-9_]{1,80}$`
- Dual-boundary validation:
  1. Validated at destination creation boundary in `IntegrationDestination.create()`.
  2. Independently validated at resolution boundary in `EnvIntegrationSecretResolver.resolve()` and `FakeIntegrationSecretResolver.resolve()` (defense in depth).
- Non-namespaced references raise `SecretReferenceSecurityError`.

### Resolution Failure Semantics & Zero Transient Retry
- When a secret reference is missing or its environment value is empty/whitespace-only:
  - `EnvIntegrationSecretResolver.resolve()` raises `IntegrationSecretResolutionError`.
  - Delivery transitions immediately to `DEAD_LETTER` with `last_error_code="SECRET_RESOLUTION_FAILED"`.
  - Failure is permanent and configuration-level: does NOT retry transiently and does not consume retry attempts.

### Secret Rotation at Execution Time
- Secret values are resolved at execution time on every delivery attempt.
- Rotating an integration secret requires updating the host environment variable (`BOP_INTEGRATION_SECRET_<NAME>`) or secrets manager and restarting/reloading the process.
- No database update, schema change, or migration is required to rotate secrets.

### `target_app_id` Routing Metadata Isolation
- `target_app_id` on `bop_integration_destinations` serves strictly as routing and diagnostic metadata for dispatch and filtering.
- It NEVER mutates or overrides `BopIntegrationEvent.source_app_id` (always `bopclients`).
- It NEVER modifies `BopEntityRef.application_id`.
- Outbound `envelope_json` remains 100% byte-for-byte identical to the transactional outbox canonical event payload.

### HTTP Transport Proxy Policy (`trust_env=False`)
- `HttpWebhookTransport` explicitly configures `trust_env=False` on both `httpx.HTTPTransport(verify=True, trust_env=False)` and `httpx.Client(..., trust_env=False)`.
- Prevents ambient proxy environment variables (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`) from routing outbound webhook traffic through unvalidated external proxies, which would circumvent socket-level IP validation in `SafeSyncBackend`.

### `SafeSyncBackend` & `HTTPTransport._pool` Dependency Audit
- **Installed versions:** `httpx 0.28.1`, `httpcore 1.0.9`.
- **Implementation Note:** `httpx.HTTPTransport` does not accept a custom `network_backend` argument in its public constructor. To bind `SafeSyncBackend` to `httpx.Client`, `HttpWebhookTransport` constructs an `httpcore.ConnectionPool(network_backend=SafeSyncBackend(...))` and assigns it to `transport._pool`.
- **Maintenance Guidance:** This accesses a private attribute (`_pool`) of `httpx.HTTPTransport`. Dependencies `httpx` and `httpcore` must remain pinned to avoid breaking changes in future minor releases. If `httpx` refactors its internal pool attribute, `HttpWebhookTransport` must be adapted accordingly.

### Claim Token Leak Prevention
- Distributed worker claim tokens (`claim_token`) are strictly internal concurrency controls.
- Removed completely from `safe_summary()`, CLI stdout, and JSON summaries to prevent token exposure in logs or operator tooling.
