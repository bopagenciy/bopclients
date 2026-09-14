# BopClients Web Application Foundation

This document describes the architecture, visual identity, security baseline, and internationalization framework of the BopClients product web application (`apps/web/`).

---

## 1. Architecture Overview

- **Framework**: Next.js 14 (`14.2.35` pinned) + React 18 (`18.3.1`) + TypeScript (`5.7.3`) + Tailwind CSS (`3.4.17`)
- **Location**: `apps/web/`
- **Pattern**: Backend-for-Frontend (BFF) Architecture
- **Backend API**: FastAPI at `/api/v1` (`http://127.0.0.1:8100`)
- **Database Schema**: `20260902_009` (Strictly unchanged from P19 baseline)

```
[ Browser Client ]
       │
       │ HttpOnly Cookies (bop_access_token, bop_session_token, bop_active_org)
       │ + Same-Origin CSRF Verification
       ▼
[ Next.js BFF (apps/web) ]
  ├── /api/auth/login, logout, refresh, session, switch-org
  └── /api/proxy/[...path] (Authorized header injection)
       │
       │ Bearer <access_token> + X-Bop-Organization-Id: <bop_org_id>
       │ (Client-supplied auth/org headers stripped)
       ▼
[ FastAPI Backend (bopclients/api) ]
```

---

## 2. Security Baseline & BFF Architecture

1. **Zero Browser Storage of Credentials**:
   - Neither JWT access tokens, refresh tokens, nor API secrets are EVER stored in `localStorage` or `sessionStorage`.
   - All stateful authentication relies on server-managed cookies:
     - `bop_access_token`: `HttpOnly: true`, `SameSite: 'lax'`, `Secure: production` (short-lived JWT)
     - `bop_session_token`: `HttpOnly: true`, `SameSite: 'lax'`, `Secure: production`, 30-day lifetime
     - `bop_active_org`: `HttpOnly: true`, `SameSite: 'lax'` (canonical global tenant identity)
2. **CSRF Mitigation**:
   - All mutating requests (`POST`, `PUT`, `PATCH`, `DELETE`) pass through `validateCsrfRequest(request)`.
   - Compares request `Origin` or `Referer` against allowed frontend host origins (`NEXT_PUBLIC_APP_URL` or standard localhost origins).
   - Cross-origin mutations are rejected immediately with HTTP 403 `CSRF_REJECTED`.
3. **Trusted Header Injection & Client Header Stripping**:
   - The BFF proxy interceptor strictly removes client-provided `Authorization` and `X-Bop-Organization-Id` headers.
   - Authoritative values are extracted solely from the encrypted/HttpOnly server-side cookies before being forwarded to the FastAPI backend.
4. **Active Organization Membership Validation**:
   - Organization switching via `/api/auth/switch-org` queries `GET /api/v1/me` to verify the user holds an active membership in the target tenant before updating the `bop_active_org` cookie.
5. **Server-Side Session Revocation**:
   - Logout calls backend `POST /api/v1/auth/logout` to revoke the database session record and clears all authentication cookies.
6. **Automatic Token Rotation**:
   - The BFF proxy interceptor detects expired access tokens (`401 Unauthorized`) and automatically rotates tokens using the session token via `POST /api/v1/auth/refresh`.

---

## 3. Brand Identity & Visual System

1. **Strict Brand Asset Policy**:
   - Official BopClients logo file found in repository: `False`.
   - **Zero Fabrication**: No invented geometric icons, nodes, substitute logos, or synthetic graphics are bundled.
   - Typographic fallback: strictly rendered text `BOP | CLIENTS` using semibold tracking and a provisional gold vertical bar (`#C5A059`).
   - Standard drop-in path: `apps/web/public/brand/bop-clients-logo.svg`.
   - When dropped into place, `BrandLogo.tsx` automatically switches from the typographic fallback to the SVG asset.
2. **Provisional Gold & Color Palette**:
   - Background: `#FAFAFA`
   - Surface: `#FFFFFF`
   - Subtle Surface: `#F4F4F5`
   - Foreground: `#18181B`
   - Foreground Muted: `#71717A`
   - Border: `#E4E4E7`
   - Brand Gold (Provisional): `#C5A059` (Hover: `#B38F46`, Subtle: `#FDF8EC`)
   - Brand Dark: `#111827`
   - Brand Primary / Slate: `#0F172A`
   - Status Success: `#16A34A`
   - Status Warning: `#CA8A04`
   - Status Danger: `#DC2626`
   - Status Info: `#2563EB`

---

## 4. Truthful Data Architecture

All dashboard and operational views strictly enforce the Truthful Data Policy:
1. **No Synthetic Metrics**:
   - Simulated trends (e.g. `+12.5%`), hardcoded SLA percentages (`99.9%`), fake signal counts, and mock activity feeds are prohibited.
2. **Authoritative Backend Data**:
   - Metrics are derived strictly from P19 aggregate queries (`/api/v1/campaigns`, `/api/v1/prospects`, `/api/v1/icps`, `/api/v1/target-markets`).
   - If no data exists, components render truthful empty states (`EmptyState.tsx`) rather than placeholder numbers.
3. **True Monitoring & Integrations**:
   - Monitoring views render live worker and system telemetry from `GET /api/v1/monitoring/overview` and `GET /api/v1/monitoring/health`.
   - Integrations exclusively display real destinations configured in `GET /api/v1/integrations/destinations`.
4. **Prospect Signals**:
   - Signal modals dynamically query `GET /api/v1/prospects/{id}/signals` instead of displaying hardcoded mock signals.

---

## 5. Bilingual Architecture (i18n)

- **Catalogs**:
  - `apps/web/messages/en.json` (English - Primary)
  - `apps/web/messages/es.json` (Spanish - Native)
- **Parity**: 100% semantic and structural key parity across all domains.
- **URL Routing**: `/[locale]/...` (`/en/dashboard`, `/es/dashboard`, etc.)
- **Error Contract Integration**:
  - Backend errors from `/api/v1` containing canonical P19 format (`error.message_key`) are dynamically translated via the active locale dictionary with fallback to backend English message.
- **Language Boundary**:
  - Changing the UI language to Spanish does NOT alter the autonomous research pipeline or prospect entity discovery. Discovery runs across original web sources and documents in their native languages.

---

## 6. RBAC & Permissions Alignment

Matches the backend RBAC matrix defined in `bopclients.domain.auth.policy`:

| Permission | Role Allowed |
| :--- | :--- |
| `campaign.create`, `campaign.update` | `OWNER`, `ADMIN`, `MEMBER` |
| `campaign.delete` | `OWNER`, `ADMIN` |
| `icp.manage` | `OWNER`, `ADMIN`, `MEMBER` |
| `target_market.create` | `OWNER`, `ADMIN`, `MEMBER` |
| `prospect.update` | `OWNER`, `ADMIN`, `MEMBER` |
| `research.run` | `OWNER`, `ADMIN`, `MEMBER` |
| `integration.manage` | `OWNER`, `ADMIN` |
| `members.manage` | `OWNER`, `ADMIN` |
| `organization.update` | `OWNER`, `ADMIN` |
| `organization.delete` | `OWNER` |
| Read-only access | All roles (`OWNER`, `ADMIN`, `MEMBER`, `VIEWER`) |

Frontend permission enforcement is implemented via `PermissionGate` and `hasPermission(role, permission)` utility functions in `lib/permissions/index.ts`.

---

## 7. Quality Assurance & Verification

- **Typecheck**: `npm run typecheck` (`tsc --noEmit`)
- **Linting**: `npm run lint` (ESLint 8 + `eslint-config-next`)
- **Unit & Component Testing**: `npm test` (Vitest + React Testing Library)
- **End-to-End Testing**: `npm run test:e2e` (Playwright on port 3100 via system Microsoft Edge)
- **Production Build**: `npm run build` (Static export & SSR validation for 29 routes)

### Known Accessibility Considerations
- Modal dialogs implement active focus transfer upon mounting and focus restoration upon unmounting (`Modal.tsx`). Complete keyboard tab-cycling loop within the modal dialog remains an acknowledged polish item for future accessibility hardening.
