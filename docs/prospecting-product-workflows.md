# BopClients — Prospecting Product Workflows & Discovery Engine Documentation

**Phase**: P21
**Architecture Status**: Production-Ready SaaS UI & API Layer
**Database Schema**: `20260902_009` (Strictly Unmodified)
**Security Posture**: BFF HttpOnly Cookies, Zero Local Token Storage, Pure RBAC Enforcement

---

## 1. Executive Summary

Phase P21 bridges BopClients' existing high-performance domain search engines (P2–P10) with the bilingual P20 web application. Authenticated users can now define Ideal Customer Profiles (ICPs), delineate Target Markets, create and manage Outbound Campaigns, execute natural language Prospect Discovery pipelines via FORGE/Overture, and inspect deep Prospect Dossiers with deterministic Lead Scoring (0–100) and Outreach Priority rankings.

---

## 2. End-to-End Prospecting Workflows

```
  ┌────────────────────────────────────────────────────────┐
  │                 1. Ideal Customer Profile              │
  │  - Firmographic parameters (industries, company sizes)  │
  │  - Decision maker roles & target geographies            │
  └─────────────────────────┬──────────────────────────────┘
                            │ (optional link)
                            ▼
  ┌────────────────────────────────────────────────────────┐
  │                 2. Target Market                       │
  │  - Regional boundaries (Country, State, City, Radius)   │
  │  - Market language preference                           │
  └─────────────────────────┬──────────────────────────────┘
                            │ (associated ICP)
                            ▼
  ┌────────────────────────────────────────────────────────┐
  │                 3. Outbound Campaign                   │
  │  - Status lifecycle (draft -> active -> paused -> ...)  │
  │  - Campaign prospects collection                       │
  └─────────────────────────┬──────────────────────────────┘
                            │ (active campaign target)
                            ▼
  ┌────────────────────────────────────────────────────────┐
  │                 4. Prospect Discovery                  │
  │  - Step 1: Natural Language Prompt -> SearchIntent     │
  │  - Step 2: SearchIntent -> Provider SearchPlan Preview │
  │  - Step 3: SearchPlan -> Execution via FORGE Engine    │
  │  - Step 4: Import & Deduplication -> Campaign Pipeline │
  └─────────────────────────┬──────────────────────────────┘
                            │ (click prospect link)
                            ▼
  ┌────────────────────────────────────────────────────────┐
  │                 5. Prospect Dossier                    │
  │  - Entity Overview & Provenance                        │
  │  - Detected Opportunity Signals                        │
  │  - Intelligence (OBSERVED / DERIVED / INFERRED)        │
  │  - Deterministic Lead Qualification Score (0-100)      │
  │  - Deterministic Outreach Priority Tier & Reasons      │
  │  - Deep-Web Research Trigger                           │
  └────────────────────────────────────────────────────────┘
```

---

## 3. Natural Language Discovery Engine & Plan Preview

The discovery pipeline follows a strict, non-destructive 3-stage flow:
1. **`POST /api/v1/discovery/intents`**:
   - Accepts a free-form natural language query (e.g., *"Distributors of industrial safety equipment with warehouses in South Florida"*).
   - Extracts structured parameters (`industries`, `locations`, `company_size_min`, `company_size_max`, `keywords`, `languages`).
   - Resolves search semantics across market languages without restricting queries to the UI locale.
2. **`POST /api/v1/discovery/plans`**:
   - Formulates concrete provider tasks (e.g. `forge_discovery`, `overture_places`) targeting specific cities, regions, and categories.
   - Calculates warning diagnostics (e.g., missing specific geographies or broad categories).
   - Allows preview and human review before network execution.
3. **`POST /api/v1/discovery/execute`**:
   - Requires an `active` campaign (campaigns in `draft` or `paused` state are rejected with `400 Bad Request`).
   - Concurrently queries provider registries.
   - Idempotently imports discovered businesses: generates new `prospects` or reuses existing prospect records across organizations.
   - Links accounts to `campaign_prospects` with relevance scoring and priority tiering.

---

## 4. Prospect Dossier, Lead Scoring & Priority Urgency

Every prospect record has an enterprise dossier view at `/[locale]/prospects/[id]`:
- **Lead Qualification Score**:
  - Educational Tooltip: *"Lead Score (0-100) measures commercial fit and service need alignment based on verified signals and ICP criteria."*
  - Calculated deterministically from ICP alignment, headcount fit, and requirement matches.
  - Interactive on-demand recalculation via `POST /api/v1/prospects/{id}/score/recalculate`.
- **Outreach Priority Tier**:
  - Educational Tooltip: *"Priority measures commercial urgency and timing based on recent intent activity, signal freshness, and research depth."*
  - Tiers: `LOW`, `MEDIUM`, `HIGH`, `URGENT`.
  - Factors: Signal freshness, active hiring or location expansion triggers, research confidence.
  - Interactive on-demand recalculation via `POST /api/v1/prospects/{id}/priority/recalculate`.
- **Structured Intelligence Rigor**:
  - **Observed**: Verified direct facts (company registry records, website domains, addresses).
  - **Derived**: Calculated attributes (headcount range estimates, territory radius match, ICP fit index).
  - **Inferred**: Probabilistic indicators (commercial need likelihood, urgency timing).

---

## 5. Security, Tenancy & Bilingual Parity

1. **Strict Multi-Tenancy**:
   - All backend queries require `X-Bop-Organization-Id` and validate active membership.
   - Cross-tenant requests to foreign campaigns or prospects return `404 RESOURCE_NOT_FOUND` (preventing tenant probing).
2. **Strict RBAC**:
   - `VIEWER`: Read-only access across all views. Mutation buttons are completely hidden in the UI (`PermissionGate`) and blocked on the API (`403 Forbidden`).
   - `MEMBER`: Operational permissions granted (`campaign.create`, `campaign.update`, `icp.manage`, `target_market.create`, `prospect.update`, `research.run`).
   - `ADMIN` / `OWNER`: Administrative permissions granted.
3. **Pure Typographic Branding**:
   - Pure CSS `BOP | CLIENTS` typography; no synthetic SVG icons or invented marks.
4. **100% Bilingual Parity**:
   - Complete key-for-key correspondence across `messages/en.json` and `messages/es.json`.
