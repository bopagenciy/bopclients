# BopClients — Product API, Authentication & Tenant Authorization Foundation (Phase P19)

## 1. Overview & Architecture

Phase P19 establishes the product-facing REST API (`/api/v1`), authentication mechanisms, and tenant authorization foundation for BopClients, enabling secure multi-tenant frontend web applications to interact with the platform.

### Key Architectural Pillars:
- **Framework**: FastAPI (ASGI) with Starlette middleware pipeline and Pydantic schemas.
- **Identity & Authentication**: Short-lived HS256 JWT access tokens (1h default lifespan) paired with cryptographically secure, SHA-256 hashed opaque session refresh tokens (`bop_sess_...`) stored in `bop_auth_sessions`.
- **Password Hashing**: Argon2id (`argon2-cffi`) as primary hashing algorithm with standard `scrypt` fallback, timing attack defense via authentic dummy verification, and strict memory concealment in domain models (`__repr__` redacting password hashes).
- **Tenant Context & Scoping**: `X-Bop-Organization-Id` request header resolving tenant context dynamically, validating membership against the user profile. Cross-tenant access attempts consistently return HTTP 404 to eliminate resource and tenant existence enumeration.
- **Role-Based Access Control (RBAC)**: Hierarchical matrix across 4 core roles (`OWNER`, `ADMIN`, `MEMBER`, `VIEWER`) strictly enforced via declarative endpoint dependencies.
- **Multilingual Localization**: Native error catalog supporting `en` (default) and `es`, resolved dynamically via `Accept-Language` headers and user profile preferences.
- **Security Baseline**: Nonce/UUID correlation IDs (`X-Request-Id`), defense-in-depth HTTP security headers (`nosniff`, `strict-origin-when-cross-origin`, `no-store, no-cache, must-revalidate`), and brute-force account lockout (5 failed attempts within 15 minutes = 15-minute lock).

---

## 2. Authentication Flow & Token Specification

### 2.1 Login (`POST /api/v1/auth/login`)
- Accepts `email` and `password`.
- Normalizes email to lowercase.
- Checks brute-force lockout status in `bop_auth_login_attempts` (5 failed attempts within 15 minutes trigger 15-minute lockout).
- If user does not exist, executes `dummy_verify()` (>1ms Argon2 computation) to eliminate timing-based user enumeration.
- Password hashing generates a cryptographically random, unique 16-byte salt per hash for both Argon2id and scrypt fallback (`hash1 != hash2` for identical inputs; hashes are NOT deterministic).
- Upon valid verification, generates:
  1. Short-lived HS256 JWT `access_token` containing `iss: "bopclients"`, `aud: "bopclients-api"`, `sub` (user ID), `email`, `session_id`, `iat`, `exp`, `jti`.
  2. High-entropy opaque 32-byte session token (`bop_sess_<token>`).
  3. Raw session token is NEVER stored in the database; only deterministic SHA-256 hash is persisted in `bop_auth_sessions`.
- Returns sanitized user profile and tokens.

### 2.2 Token Refresh & Session Model (`POST /api/v1/auth/refresh`)
- Accepts `refresh_token`.
- Looks up active session by SHA-256 token hash (`FIXED_SESSION` model).
- **Session Model**: `FIXED_SESSION`. The opaque session token remains valid for the session lifetime (default 30 days) until expiration, explicit logout, or administrative revocation.
- **Rotation Disclosure**: The session token is **NOT** rotated one-time on every refresh call (`ROTATING_REFRESH_TOKEN: False`). This fixed-session design is acceptable for the P19 foundation, but single-use refresh token rotation is documented as a remaining security hardening opportunity for future releases.
- Validates session expiration and revocation status (`revoked_at IS NULL`).
- Validates that user remains active.
- Reissues fresh HS256 JWT `access_token` and touches `last_active_at`.

### 2.3 Logout & Session Revocation (`POST /api/v1/auth/logout`)
- Accepts optional `refresh_token` in body, or extracts active `session_id` from bearer JWT context.
- Atomically revokes session by setting `revoked_at = CURRENT_TIMESTAMP` and `status = 'revoked'`.
- Session revocation immediately invalidates subsequent requests with both the access token and the refresh token (HTTP 401 `SESSION_EXPIRED_OR_REVOKED`).

### 2.4 Authentication Signing Key Configuration
- Setting: `BOP_AUTH_SIGNING_KEY` configured via environment variables.
- Minimum length: $\ge 32$ characters strictly enforced at application initialization.
- **Cryptographic Hygiene**: A 32-character string does not automatically guarantee 256 bits of entropy. In production, operators must generate keys using a cryptographically secure random source (recommended: 32+ random bytes safely encoded as hex or base64, providing genuine 256-bit entropy).
- **Zero-Storage Invariant**: Signing keys are strictly in-memory (`TokenService._signing_key`). They are never stored in the database, never returned via API, never logged, and never committed to source control.

### 2.5 Login Abuse & Brute-Force Safety
- Attempt tracking key: `sha256(normalized_email:client_ip)`.
- Client IP source: Direct peer socket IP (`request.client.host`).
- Reverse-proxy headers (`X-Forwarded-For`, `CF-Connecting-IP`, `X-Real-IP`) are intentionally not trusted blindly in this release without verified upstream proxy enforcement.
- Distributed brute-force attacks across many source IPs remain an operational tuning consideration for production edge firewalls/WAF.

---

## 3. Tenant Scoping & IDOR Defense

Every tenant-scoped request must provide:
```http
Authorization: Bearer <jwt_access_token>
X-Bop-Organization-Id: <bop_organization_id_uuid>
```

### Invariants:
1. **Context Resolution**: The `get_tenant_context` dependency extracts the authenticated user, verifies that the user is an active member of the organization specified by `X-Bop-Organization-Id`, and constructs a `TenantContext`.
2. **IDOR Hard Barrier**: If a user attempts to access resources belonging to a different tenant or if the requested resource does not exist in the tenant scope, the API returns:
   ```json
   {
     "error": {
       "code": "RESOURCE_NOT_FOUND",
       "message": "The requested resource was not found.",
       "message_key": "errors.resource_not_found",
       "request_id": "req-uuid-...",
       "details": {}
     }
   }
   ```
   HTTP 404 is returned instead of 403 or 401 on resource endpoints to prevent resource enumeration.

---

## 4. RBAC Permission Matrix

| Permission | VIEWER | MEMBER | ADMIN | OWNER |
| :--- | :---: | :---: | :---: | :---: |
| `organization.read` |  |  |  |  |
| `organization.manage` | ❌ | ❌ |  |  |
| `organization.delete` | ❌ | ❌ | ❌ |  |
| `members.read` |  |  |  |  |
| `members.manage` | ❌ | ❌ |  |  |
| `owner.transfer` | ❌ | ❌ | ❌ |  |
| `campaign.read` |  |  |  |  |
| `campaign.create` | ❌ |  |  |  |
| `campaign.update` | ❌ |  |  |  |
| `campaign.delete` | ❌ | ❌ |  |  |
| `prospect.read` |  |  |  |  |
| `prospect.create` | ❌ |  |  |  |
| `prospect.update` | ❌ |  |  |  |
| `signals.read` |  |  |  |  |
| `research.read` |  |  |  |  |
| `research.trigger` | ❌ |  |  |  |
| `monitoring.read` |  |  |  |  |
| `monitoring.manage` | ❌ | ❌ |  |  |
| `integration.read` | ❌ | ❌ |  |  |
| `integration.manage`| ❌ | ❌ |  |  |

---

## 5. API Endpoint Reference

### Operational Endpoints
- `GET /health` & `GET /health/live`: Unauthenticated liveness check.
- `GET /ready` & `GET /health/ready`: Unauthenticated readiness check verifying DB connection and schema version `20260902_009`.

### Authentication Endpoints (`/api/v1/auth`)
- `POST /api/v1/auth/login`: User login, issuance of JWT and session token.
- `POST /api/v1/auth/refresh`: Access token refresh via opaque session token.
- `POST /api/v1/auth/logout`: Revoke active session token.

### User & Preferences (`/api/v1/me`)
- `GET /api/v1/me`: Authenticated user profile and organizations.
- `PATCH /api/v1/me`: Update display name and locale preferences.
- `GET /api/v1/me/organizations`: List organizations accessible to current user.
- `GET /api/v1/me/memberships`: List user memberships with joined timestamp.

### Tenant & Organization (`/api/v1/organizations`)
- `GET /api/v1/organizations`: List user organizations.
- `GET /api/v1/organizations/{org_id}`: Get organization details (membership verified, 404 on IDOR).
- `GET /api/v1/organizations/current`: Active tenant profile.
- `PATCH /api/v1/organizations/current`: Update active tenant profile (`ADMIN`, `OWNER`).
- `GET /api/v1/organizations/current/members`: List tenant members.
- `POST /api/v1/organizations/current/members`: Invite / add member (`ADMIN`, `OWNER`).
- `PATCH /api/v1/organizations/current/members/{user_id}`: Update member role (`ADMIN`, `OWNER`).

### Campaigns (`/api/v1/campaigns`)
- `GET /api/v1/campaigns`: List tenant campaigns (paginated).
- `POST /api/v1/campaigns`: Create campaign (`MEMBER`, `ADMIN`, `OWNER`).
- `GET /api/v1/campaigns/{id}`: Get campaign details (tenant-isolated).
- `PATCH /api/v1/campaigns/{id}`: Update campaign.

### ICPs & Target Markets (`/api/v1/icps`, `/api/v1/target-markets`)
- `GET /api/v1/icps`: List ideal customer profiles (paginated).
- `POST /api/v1/icps`: Create ICP (`MEMBER`, `ADMIN`, `OWNER`).
- `GET /api/v1/icps/{id}`: Get ICP details (tenant-isolated).
- `PATCH /api/v1/icps/{id}`: Update ICP profile (`MEMBER`, `ADMIN`, `OWNER`).
- `GET /api/v1/target-markets`: List target markets for tenant (paginated).
- `POST /api/v1/target-markets`: Create target market for an ICP (`MEMBER`, `ADMIN`, `OWNER`).
- `GET /api/v1/target-markets/{id}`: Get target market details (tenant-isolated).
- `PATCH /api/v1/target-markets/{id}`: Update target market (`MEMBER`, `ADMIN`, `OWNER`).

### Prospects & Intelligence (`/api/v1/prospects`)
- `GET /api/v1/prospects`: List and filter prospects (paginated).
- `POST /api/v1/prospects`: Create prospect manually.
- `GET /api/v1/prospects/{id}`: Get aggregated prospect detail (including score, signals, schedule).
- `GET /api/v1/prospects/{id}/intelligence`: Get intelligence snapshot.
- `PATCH /api/v1/prospects/{id}`: Update prospect contact info.

### Continuous Monitoring (`/api/v1/monitoring`, `/api/v1/prospects/{id}/monitoring`)
- `GET /api/v1/monitoring/overview`: Tenant schedule metrics (total, active, paused, failing).
- `GET /api/v1/monitoring/health`: Tenant monitoring health status.
- `GET /api/v1/prospects/{id}/monitoring`: Get prospect monitoring schedule.
- `PATCH /api/v1/prospects/{id}/monitoring`: Pause or configure schedule (`ADMIN`, `OWNER`).

### Integrations (`/api/v1/integrations`)
- `GET /api/v1/integrations/destinations`: List webhook destinations (`ADMIN`, `OWNER`).
- `POST /api/v1/integrations/destinations`: Register destination (`ADMIN`, `OWNER`).
- `PATCH /api/v1/integrations/destinations/{id}`: Update destination (`ADMIN`, `OWNER`).
- `GET /api/v1/integrations/outbox`: List tenant outbox events.
- `GET /api/v1/integrations/inbox`: List tenant inbox events.
- `GET /api/v1/integrations/deliveries`: List outbox delivery attempts and errors.

---

## 6. Runbook & Local Execution

### 6.1 Running Migrations
```bash
python -m bopclients.runtime.db_migrator
```
Ensures schema version `20260902_009` is applied.

### 6.2 Starting the API Server
```bash
uvicorn bopclients.api.app:app --host 127.0.0.1 --port 8100 --reload
```

### 6.3 Interactive OpenAPI Documentation
Visit:
- Swagger UI: `http://127.0.0.1:8100/docs`
- ReDoc: `http://127.0.0.1:8100/redoc`
- OpenAPI Specification: `http://127.0.0.1:8100/openapi.json`
