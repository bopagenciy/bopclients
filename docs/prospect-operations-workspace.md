# Phase P22 - Prospect Operations Workspace & Daily Productivity

## Architecture & System Design

Phase P22 transitions BopClients into a high-throughput daily prospecting operations workspace.

### 1. Enhanced Server-Side Prospect Search & Multi-Dimensional Filtering
- **Endpoint**: GET /api/v1/prospects
- **Filtering Parameters**:
  - q / search: Multi-field case-insensitive substring search matching prospect name, website, email, phone, city, state, and industry.
  - campaign_id: Limits results to prospects associated with a specific campaign via CampaignProspectRepository.
  - priority: Filter by priority tier (urgent, high, medium, low).
  - score_min / score_max: Bounded qualification score filtering.
  - unscored: Boolean flag filtering prospects that have not yet undergone scoring.
  - has_signals: Boolean flag filtering prospects with at least one detected opportunity signal.
  - industry, city, state, country: Exact/prefix firmographic criteria matching.
- **Dynamic Sorting**:
  - Whitelisted fields: created_at, updated_at, name, industry, city, state, lead_score, priority.
  - Direction: asc or desc.
  - Input validation: Rejects unknown sort columns with HTTP 400 Canonical Error.

### 2. Batch Hydration (O(1) DB Trips)
- Eliminates N+1 query overhead by batching all prospect IDs on the current page:
  - Fetches lead qualification scores in a single bulk query.
  - Fetches priority tiers in a single bulk query.
  - Fetches campaign associations and campaign names in a single bulk query.
  - Counts detected opportunity signals in a single bulk query.
  - Fully populates ProspectResponse fields: lead_score, priority_tier, campaign_count, campaign_names, signals_count.

### 3. Bulk Operations Suite
- **Bulk Add to Campaign**:
  - Endpoints: POST /api/v1/prospects/bulk/add-to-campaign & POST /api/v1/campaigns/{campaign_id}/prospects/bulk.
  - Safe batch size: up to 100 prospects.
  - Idempotent: Skips already associated prospects without error, returns added_count and already_present_count.
- **Bulk Recalculate Score**:
  - Endpoint: POST /api/v1/prospects/bulk/recalculate-score.
  - Safe batch size: up to 50 prospects.
- **Bulk Recalculate Priority**:
  - Endpoint: POST /api/v1/prospects/bulk/recalculate-priority.
  - Safe batch size: up to 50 prospects.
- **Bulk Research Trigger**:
  - Endpoint: POST /api/v1/prospects/bulk/research.
  - Safe batch size: up to 25 prospects.
  - Idempotent: Skips active/pending runs.
- **Truthful Partial Outcome Reporting**:
  - Bulk endpoints return structured breakdowns (processed_count, scored_count/prioritized_count/triggered_count, failed_count, skipped_count).

### 4. Secure CSV Export
- **Endpoints**: GET /api/v1/prospects/export (filtered dataset) and POST /api/v1/prospects/export (selected IDs).
- **Spreadsheet Formula Injection Mitigation**:
  - Text fields starting with =, +, -, @, \t, or \r are escaped with a leading single quote.
- **HTTP Headers**:
  - Content-Disposition: attachment; filename="prospects_export_<timestamp>.csv"
  - Content-Type: text/csv; charset=utf-8

### 5. Frontend Daily Productivity Workspace
- **URL Search Parameters Synchronization**:
  - Search, campaign_id, priority, score ranges, signals, sorting, and pagination sync bidirectionally with URL params.
- **Preserved Navigation Context**:
  - Clicking prospects passes ?return_to=... encoding active filters.
  - Dossier Back button restores workspace state.
  - Campaigns page features "View in Prospects Workspace" shortcut.
- **Multi-Select & Floating Bulk Actions Toolbar**:
  - Checkbox column supports select all / clear all and individual row toggling.
  - Floating action toolbar enables bulk campaign mapping, score/priority recalculations, research triggering, and CSV export.
- **Bilingual Internationalization**:
  - 100% key parity between en.json and es.json.
- **RBAC Enforcement**:
  - VIEWER denied operational mutations; allowed export.
  - MEMBER and above granted mutation capabilities.
