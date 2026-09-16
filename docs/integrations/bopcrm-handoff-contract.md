# Bop CRM Cross-Application Integration Contract

**Phase**: P27 — Bop CRM Handoff & Cross-App Integration Foundation
**Event Type**: `prospect.ready_for_crm`
**Schema Version**: `2`
**Producer**: `bopclients`
**Consumer**: `bopcrm` (and subscribed third-party CRM adapters)
**Security Boundary**: Tenant-Isolated via Canonical `bop_organization_id`

---

## 1. Overview & Architecture

BopClients acts as an upstream discovery, verification, and qualification engine. When an authorized user (OWNER, ADMIN, or MEMBER) initiates a handoff from the Prospect Dossier view (`/prospects/[prospectId]`) or in bulk, BopClients publishes a canonical `prospect.ready_for_crm` event into its transactional outbox.

The event is delivered asynchronously to registered external destinations via signed HTTPS webhooks. This architecture ensures:
1. **Zero Database Coupling**: Neither application shares database connections, ORM models, or internal tables.
2. **Transactional Outbox Guarantee**: Outbox insertion and local domain operations execute in the same atomic transaction.
3. **Deterministic Idempotency**: Repeated handoff requests for the same prospect produce an identical canonical `event_id`, preventing duplicate lead creation on the receiving end.
4. **Tenant Isolation**: Handshakes and deliveries strictly enforce tenant segregation via `bop_organization_id`.

---

## 2. Canonical Integration Envelope

The webhook payload adheres to the canonical Bop Platform event envelope:

```json
{
  "event_id": "8f3957bd-ea2e-4b47-9759-865fa500e572",
  "event_type": "prospect.ready_for_crm",
  "event_version": 2,
  "occurred_at": "2026-09-16T18:00:00.000000+00:00",
  "producer_app": "bopclients",
  "bop_organization_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "subject": {
    "bop_organization_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "application_id": "bopclients",
    "entity_type": "prospect",
    "entity_id": "prsp_987654321"
  },
  "correlation_id": "0194e824-3481-79b8-bb65-021b72a6a61d",
  "causation_id": null,
  "payload": {
    "prospect_id": "prsp_987654321",
    "company_name": "Solaris Energy Corp",
    "website": "https://solaris-energy.example.com",
    "industry": "Clean Energy",
    "location": "Denver, CO, USA",
    "lead_score": 88,
    "priority": "HIGH",
    "campaign_id": "cmp_123456789",
    "signal_summary": null,
    "source": "discovery",
    "prospect_url": "https://app.bopclients.com/prospects/prsp_987654321",
    "handoff_requested_by": "usr_alpha_admin",
    "handoff_requested_at": "2026-09-16T18:00:00.000000+00:00",
    "recommended_action": "handoff_to_crm",
    "human_review_required": false
  },
  "metadata": {}
}
```

---

## 3. Payload Field Specification

| Field | Type | Required | Description |
|---|---|---|---|
| `prospect_id` | String (UUID) | Yes | Unique identifier of the prospect in BopClients. |
| `company_name` | String | Yes | Name of the target organization or company. |
| `website` | String / Null | No | Company website URL or domain. |
| `industry` | String / Null | No | Primary industry classification. |
| `location` | String / Null | No | Formatted location string (`City, State, Country`). |
| `lead_score` | Number (0-100) | No | Calculated fit and qualification score. |
| `priority` | String | No | Priority urgency tier (`URGENT`, `HIGH`, `MEDIUM`, `LOW`). |
| `campaign_id` | String / Null | No | Associated BopClients prospecting campaign identifier. |
| `signal_summary` | Object / Null | No | Aggregated buying intent or trigger signal indicators. |
| `source` | String | No | Extraction provenance source (e.g., `discovery`, `manual`). |
| `prospect_url` | String | No | Direct URL link back to the prospect dossier in BopClients. |
| `handoff_requested_by` | String | No | User identifier of the actor who approved/triggered the handoff. |
| `handoff_requested_at` | String (ISO-8601) | No | UTC timestamp when handoff was requested. |
| `recommended_action` | String | No | Action suggestion (default: `handoff_to_crm`). |
| `human_review_required` | Boolean | No | Indicates whether additional human review gate is requested. |

---

## 4. Transport & Delivery Semantics

### Protocol
- **Transport**: HTTPS POST Webhook.
- **Request Headers**:
  - `Content-Type: application/json`
  - `X-Bop-Event-Id`: The event UUID.
  - `X-Bop-Event-Type`: `prospect.ready_for_crm`
  - `X-Bop-Event-Version`: `2`
  - `X-Bop-Organization-Id`: Tenant platform UUID.
  - `X-Bop-Timestamp`: ISO-8601 dispatch timestamp.
  - `X-Bop-Signature`: `sha256=<hmac_hex>` (when secret key reference is configured).

### Retry Policy
- **Max Attempts**: 5.
- **Backoff Strategy**: Exponential retry backoff (`delay = 30s * 2^(attempt - 1)`).
- **Transient Failures (5xx, timeouts)**: Delivery rescheduled with `RETRY_PENDING`.
- **Permanent Rejections (4xx except 429)**: Marked terminal `DEAD_LETTER`.
- **Publisher Completion**: When all registered destination deliveries succeed, parent outbox event transitions to `PUBLISHED`.

---

## 5. Receiver Implementation Requirements (Bop CRM)

1. **Idempotency**:
   - The receiver **must** record the `event_id` and guarantee that repeated deliveries of the same `event_id` do not create duplicate leads.
   - Response: Return HTTP `200 OK` or `202 Accepted` for already-processed event IDs.

2. **Tenant Verification**:
   - The receiver **must** verify that `bop_organization_id` matches the target tenant in Bop CRM before ingesting the lead.

3. **Signature Verification (Optional but Recommended)**:
   - When a shared secret is configured, the receiver validates the `X-Bop-Signature` header by computing `HMAC-SHA256(secret, raw_request_body)`.
