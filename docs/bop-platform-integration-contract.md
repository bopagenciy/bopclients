# Bop Platform Integration Contract & Universal Tenant Identity

**Version:** 1.2.0
**Status:** Canonical Foundation Specification
**Scope:** Universal contract for Bop applications (`bopclients`, `bopcrm`, `boperp`, `bopsocial`, `bopchatbot`, `bopassistant`, and future ecosystem applications).

---

## 1. Canonical `bop_organization_id` & Database Invariant

In the Bop multi-tenant ecosystem, business tenants span multiple autonomous services. To enable loose coupling and reliable event-driven collaboration without centralized runtime coordination:
- Every tenant organization has a single, immutable, globally unique identifier: `bop_organization_id`.
- The format is strictly a canonical RFC 4122 UUID v4 formatted in lowercase string representation:
  `^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`
- **Database Persistence Invariant:** `bop_organization_id` is enforced at the database schema level as **`VARCHAR(36) NOT NULL UNIQUE`**. Inserting an organization without a `bop_organization_id` raises an integrity violation (`NOT NULL constraint failed` in SQLite; `NotNullViolation` in PostgreSQL).
- `bop_organization_id` is immutable once created. Application and repository APIs reject any mutation attempt.

---

## 2. Local `organization_id` vs. Global `bop_organization_id`

Each Bop application maintains autonomy over its internal data model and persistence:
- **Local `organization.id` (Internal Relational Partition Key):**
  - Used for internal relational integrity, local foreign keys, internal query optimization, and local multi-tenant scoping.
  - In `bopclients`, `organizations.id` remains the primary key and foreign key target for local tables (`prospects`, `campaigns`, `rate_limit_policies`, etc.).
  - Local IDs must **never** leak into external integration event contracts.
- **Global `bop_organization_id` (Interoperability Identity Layer):**
  - Maintained as a unique, non-null column on the `organizations` table.
  - Used exclusively at integration boundaries, public webhooks, API federation, and in the `bop_organization_id` envelope header of all integration events.
  - Backfilled with random UUID v4 values on existing tenants during migration (`20260902_007`), remaining stable and permanent across rerun migrations.

```text
+-----------------------------------------------------------------------------------+
| Bop Ecosystem Interoperability Layer                                              |
| Canonical Tenant Identity: bop_organization_id (UUID v4, NOT NULL, UNIQUE)       |
+------------------------------------+----------------------------------------------+
                                     |
             +-----------------------+-----------------------+
             |                                               |
             v                                               v
+-----------------------------+               +-----------------------------+
| BopClients Service Boundary |               | BopCRM Service Boundary     |
| organizations:              |               | accounts / organizations:   |
| - id (local PK/FKs)         |               | - id (local PK/FKs)         |
| - bop_organization_id (UQ)  |               | - bop_organization_id (UQ)  |
+-----------------------------+               +-----------------------------+
```

---

## 3. Canonical Application Identifiers & Wire Extensibility

All participating Bop applications are identified by a canonical identifier.

| Application ID | Official Service Name | Core Domain Responsibility | Local Registry Status |
|---|---|---|---|
| `bopclients` | BopClients | Prospect discovery, research, AI qualification, outbound targeting | Registered (`LOCAL_APPLICATION_ID`) |
| `bopcrm` | BopCRM | Account management, pipeline stages, deals, customer relations | Registered |
| `boperp` | BopERP | Invoicing, accounting, inventory, order processing | Registered |
| `bopsocial` | BopSocial | Social listening, outbound marketing, audience engagement | Registered |
| `bopchatbot` | BopChatbot | Conversational inbound capture, chat routing | Registered |
| `bopassistant` | BopAssistant | Autonomous executive assistance, internal productivity | Registered |

### Extensibility & Wire Syntax
To allow future Bop applications (e.g. `bopinventory`, `bopsupport`, `bopanalytics`) to join the platform without requiring retroactive updates or breaking historical event deserialization:
- Wire format accepts any application identifier matching the syntax pattern: `^[a-z][a-z0-9_-]{1,31}$`.
- Deserialization and validation accept any syntactically valid identifier.
- Local producer checks enforce known application identity when originating events.

---

## 4. Universal Entity References (`BopEntityRef`)

Domain entities are referenced across services via typed, immutable pointers (`BopEntityRef`) that explicitly carry universal tenant identity and treat entity IDs as opaque identifiers.

### Structure
```json
{
  "bop_organization_id": "e81e33d4-b49e-4c5e-8be1-fdbbca01e6a2",
  "application_id": "bopclients",
  "entity_type": "prospect",
  "entity_id": "crm-lead-001"
}
```

### Validation & Semantic Invariants:
1. `bop_organization_id`: Canonical lowercase UUID v4 string.
2. `application_id`: Wire-compatible Bop application identifier (`^[a-z][a-z0-9_-]{1,31}$`).
3. `entity_type`: Lowercase string containing letters, digits, and underscores (`^[a-z0-9_]{1,64}$`).
4. `entity_id`: **Treated as OPAQUE string** (bounded 1 to 128 characters).
   - **NOT** assumed to be UUID.
   - **NOT** assumed to be integer.
   - **NOT** normalized, stripped, or lowercased in ways that alter identity.
   - Valid examples: `"12345"`, `"crm-lead-001"`, `"01JABCDEF123"`, `"550e8400-e29b-41d4-a716-446655440000"`.
5. **Cross-Tenant Uniqueness:** Identical `entity_id` values (e.g. `"123"`) across different tenants remain globally distinct because `bop_organization_id` is an intrinsic attribute of `BopEntityRef`.

---

## 5. Canonical Integration Event Envelope (`BopIntegrationEvent`)

All cross-application events strictly adhere to the canonical envelope specification.

```json
{
  "event_id": "c30f40d9-7603-4908-9df8-2b8109bfdb87",
  "event_type": "prospect.qualified",
  "event_version": 1,
  "occurred_at": "2026-09-14T10:00:00.000000Z",
  "producer_app": "bopclients",
  "bop_organization_id": "e81e33d4-b49e-4c5e-8be1-fdbbca01e6a2",
  "subject": {
    "bop_organization_id": "e81e33d4-b49e-4c5e-8be1-fdbbca01e6a2",
    "application_id": "bopclients",
    "entity_type": "prospect",
    "entity_id": "crm-lead-001"
  },
  "correlation_id": "18f0a3e8-e219-4820-9944-ef291f09c7eb",
  "causation_id": null,
  "payload": {
    "prospect_id": "crm-lead-001",
    "lead_score": 88,
    "priority": "HIGH",
    "qualification_summary": "Active RFP procurement verified"
  },
  "metadata": {}
}
```

### Canonical Envelope Fields:
- `event_id` (string, UUID v4): Unique identifier for this discrete event instance.
- `event_type` (string): Dotted category and action string (`^[a-z0-9_]+(\.[a-z0-9_]+)+$`).
- `event_version` (integer): Monotonically increasing positive integer ($\ge 1$).
- `occurred_at` (string, ISO-8601 UTC): Datetime string with explicit timezone offset (`Z` or `+00:00`).
- `producer_app` (string): Registered Bop application that generated the event (canonical name; `source_app` provided as alias).
- `bop_organization_id` (string, UUID v4): The tenant context owning this event.
- `subject` (`BopEntityRef`): Universal entity reference (canonical name; `entity_ref` provided as alias).
- `correlation_id` (string, UUID v4): End-to-end workflow tracing identifier.
- `causation_id` (string or null): **Nullable**. For root events, `causation_id = null`. For derived events, `causation_id` equals the parent `event_id`.
- `payload` (object): Version-governed dictionary.
- `metadata` (object): Optional routing or transport metadata.

### Cross-Tenant Envelope Invariant:
```text
event.bop_organization_id == event.subject.bop_organization_id
```
Any event where the envelope tenant does not match the subject entity's tenant raises **`CrossTenantIntegrationEvent`** and is immediately rejected.

---

## 6. Event Registry & Consumer Decoupling

The platform registry (`BopEventRegistry`) defines:
1. `event_type`
2. `event_version`
3. Owner / producer application
4. Payload validator

**No Consumer Coupling:** Core event contracts **do not hard-code consumer application lists**. Subscriptions and message routing belong strictly to the transport configuration layer, not to core domain event definitions.

---

## 7. Initial Payload Contracts (v1)

### 1. `prospect.discovered` (v1)
- Whitelisted keys: `{"prospect_id", "display_name", "source_provider", "campaign_id", "website", "source_external_id"}`
- Required: `prospect_id`, `display_name`, `source_provider`
- Optional: `campaign_id`, `website`, `source_external_id`

### 2. `prospect.qualified` (v1)
- Whitelisted keys: `{"prospect_id", "lead_score", "priority", "qualification_summary", "qualification_reason"}`
- Required: `prospect_id`, `lead_score` (numeric), `priority`, at least one of `qualification_summary` or `qualification_reason`

### 3. `buying_intent.detected` (v1)
- Whitelisted keys: `{"prospect_id", "signal_id", "signal_type", "confidence", "source", "observed_at", "evidence_reference"}`
- Required: `prospect_id` (must match `subject.entity_id`), `signal_id` (opaque local ID), `signal_type`, `confidence` (float 0.0 - 1.0), `source`, `observed_at` (UTC-aware ISO-8601)
- Optional: `evidence_reference`
- **Canonical Taxonomy Inheritance:** `buying_intent.detected` inherits directly from BopClients core classification (`bopclients.domain.signal.SIGNAL_TAXONOMY_MAP`). It may ONLY be emitted for signals classified as `BUYING_INTENT`.
  - **Eligible Verified BUYING_INTENT Signals:** `vendor_search`, `public_request_for_proposal`
  - **Strict Rejection of COMPANY_ACTIVITY:** Signals such as `hiring_marketing`, `hiring_sales`, `opened_new_location`, `new_funding`, `website_relaunch`, `new_service_launch`, `active_ads`, `recent_news`, `location_expansion`, `leadership_change`, `technology_change`, `recent_website_change`, `new_contact_found`, `new_signal_detected` are classified as `COMPANY_ACTIVITY` and strictly prohibited from emitting `buying_intent.detected`.
  - **Strict Rejection of NEED Signals:** Signals such as `website_slow`, `no_chatbot`, `no_booking`, `no_analytics`, `no_ssl`, `old_website` are classified as `NEED` (opportunity indicators) and strictly prohibited from emitting `buying_intent.detected`.
  - **No Duplicated Taxonomy in Integration Layer:** The integration layer delegates classification checks directly to `is_canonical_buying_intent_signal()` without maintaining an independent type whitelist.

### 4. `prospect.ready_for_crm` (v1)
- Whitelisted keys: `{"prospect_id", "lead_score", "priority", "recommended_action", "human_review_required"}`
- Required: `prospect_id`, `lead_score` (numeric), `priority`, `recommended_action`, `human_review_required` (boolean)
- **PII Minimization (`PRIMARY_CONTACT IN READY_FOR_CRM V1: False`):** Contact personal information (`primary_contact`, `email`, `name`) is strictly prohibited in v1. Contact synchronization will occur through a dedicated subsequent contact-sync contract.

---

## 8. Transactional Outbox Pattern & Atomicity Proof

To eliminate dual-write risks, domain mutations and outbox records are staged within the **same atomic database transaction**.

```python
with db.transaction():
    # 1. Mutate local domain entity
    org_repo.save(organization)

    # 2. Append event to outbox within the same transaction
    event = BopEventRegistry.build_event(
        event_type="organization.onboarded",
        bop_organization_id=organization.bop_organization_id,
        subject=BopEntityRef(bop_organization_id=organization.bop_organization_id, application_id="bopclients", entity_type="organization", entity_id=organization.id),
        payload={"name": organization.name},
        correlation_id=correlation_id,
    )
    outbox_repo.append(event)
```

### Atomicity Invariants:
- If transaction rolls back, neither the business state mutation nor the outbox record is persisted.
- If transaction commits, both are committed together.
- `IntegrationOutboxRepository.append()` delegates commit to the active transaction manager when inside a transaction block.

---

## 9. Outbox & Inbox Schemas

### Outbox Schema (`bop_integration_outbox`):
- `id` (VARCHAR(36) PRIMARY KEY)
- `event_id` (VARCHAR(36) NOT NULL UNIQUE)
- `bop_organization_id` (VARCHAR(36) NOT NULL)
- `event_type` (VARCHAR(100) NOT NULL)
- `event_version` (INTEGER NOT NULL DEFAULT 1)
- `producer_app` (VARCHAR(50) NOT NULL)
- `subject_bop_org_id` (VARCHAR(36) NOT NULL)
- `subject_application_id` (VARCHAR(50) NOT NULL)
- `subject_entity_type` (VARCHAR(50) NOT NULL)
- `subject_entity_id` (VARCHAR(128) NOT NULL)
- `correlation_id` (VARCHAR(36) NOT NULL)
- `causation_id` (VARCHAR(128) NULL)
- `envelope_json` (TEXT NOT NULL) - *Immutable canonical envelope*
- `status` (VARCHAR(20) NOT NULL DEFAULT 'PENDING')
- `attempt_count` (INTEGER NOT NULL DEFAULT 0)
- `available_at` (VARCHAR(50) NOT NULL)
- `created_at` (VARCHAR(50) NOT NULL)
- `published_at` (VARCHAR(50) NULL)
- `last_error_code` (VARCHAR(50) NULL)
- `last_error_message` (VARCHAR(500) NULL)

### Inbox Schema (`bop_integration_inbox`):
- `id` (VARCHAR(36) PRIMARY KEY)
- `event_id` (VARCHAR(36) NOT NULL UNIQUE)
- `producer_app` (VARCHAR(50) NOT NULL)
- `bop_organization_id` (VARCHAR(36) NOT NULL)
- `event_type` (VARCHAR(100) NOT NULL)
- `event_version` (INTEGER NOT NULL DEFAULT 1)
- `envelope_json` (TEXT NOT NULL) - *Immutable canonical envelope payload*
- `received_at` (VARCHAR(50) NOT NULL)
- `processed_at` (VARCHAR(50) NULL)
- `status` (VARCHAR(20) NOT NULL DEFAULT 'RECEIVED')
- `last_error_code` (VARCHAR(50) NULL)
- `last_error_message` (VARCHAR(500) NULL)

---

## 10. Database Foreign Key & Tenant Provisioning Boundary Decision

- **Decision:** Outbox and inbox tables **do not** declare relational database-level foreign keys to `organizations.bop_organization_id`.
- **Architectural Rationale & Provisioning Contracts:**
  1. *Outbox Local-Tenant Integrity Invariant:* Local outbound events produced by `bopclients` (`LOCAL_APPLICATION_ID`) **must** belong to an existing, locally provisioned tenant. Before appending to `bop_integration_outbox`, the repository asserts that `bop_organization_id` resolves to an existing record in the local `organizations` table. Attempting to stage an event for an unknown or unprovisioned local tenant raises `UnknownLocalTenantIntegrationError` and writes 0 outbox rows.
  2. *Inbox Asynchronous Decoupling:* Inbound integration events (e.g. from BopCRM, BopERP) may arrive before local tenant provisioning has completed in BopClients. The inbox durably persists event envelopes (`status = 'RECEIVED'`) without a database FK constraint. Business handling and domain routing are deferred until the local tenant is provisioned or routed by future policy.
  3. *Lifecycle Decoupling:* Administrative tenant archiving or local soft-deletions do not cascade-delete or lock audit event histories in the outbox/inbox tables.
  4. *Multi-Tenant Logical Scoping:* Tenant boundaries are enforced via strict query scoping (`WHERE bop_organization_id = :id`) and application-level domain validation.


---

## 11. Delivery Guarantee Semantics

```text
+-------------------------------------------------------------+
| EXACTLY-ONCE DELIVERY: NOT PROVIDED                         |
|                                                             |
| PLATFORM TARGET: AT-LEAST-ONCE DELIVERY                     |
|                + IDEMPOTENT CONSUMERS                       |
+-------------------------------------------------------------+
```

- **Outbox `PUBLISHED`:** Signifies transport layer receipt acknowledgement; does not guarantee downstream consumer completion.
- **Inbox Idempotency:** Duplicate delivery of already `PROCESSED` events returns existing records without state regression. Redelivery of `FAILED` events returns the existing failed record for deterministic worker retry.

---

## 12. Security & Secret Scanner

- The event envelope and payload must never contain authentication secrets, database credentials, API keys, or raw OAuth tokens.
- `BopIntegrationEvent` executes an automated key scanner rejecting credential keys (`api_key`, `access_token`, `password`, `secret`, `private_key`, `credentials`, `auth_header`, `bearer`) while allowing legitimate non-secret domain metadata (`token_count`, `secretary_name`, `authentication_method`).
- Secret scanner exceptions never log or expose secret values.

---

## 13. Timestamp UTC Contract

- All timestamps are stored and serialized as canonical ISO-8601 UTC strings (`YYYY-MM-DDTHH:MM:SS.ffffff+00:00` or `...Z`).
- Timezone-naive timestamps are strictly rejected during event instantiation.
- Storage in SQLite and PostgreSQL uses bounded `VARCHAR(50)` text fields preserving exact timezone offsets without implicit local time conversion.

---

## 14. Remaining Platform Scope (Honest Architecture Status)

- **Message Broker:** Not yet connected (outbox and inbox persist to database tables; no external message broker attached in P17/P17.1).
- **External Publisher Daemon:** Not yet implemented (polling worker that pushes `PENDING` outbox records to network transports is deferred).
- **Consumer Business Handlers:** Application-specific consumer routing logic is not yet implemented.
- **Global Tenant Provisioning:** Cross-app tenant provisioning (e.g. creating an organization in BopCRM and auto-provisioning `bop_organization_id` in BopClients) remains to be implemented.
