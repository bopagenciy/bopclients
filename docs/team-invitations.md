# Secure Team Invitations & Membership Onboarding (P24 / P24.1)

## 1. Overview
Phase P24/P24.1 establishes a secure, cryptographic team invitation and onboarding system for BopClients. It enables tenant administrators to invite collaborators to their organization with assigned permissions, while strictly preserving zero-trust credential hygiene, multi-tenant isolation, and anti-enumeration safeguards.

---

## 2. Cryptographic Token Design & Delivery Architecture

### 2.1 Zero-Knowledge Token Storage & Production Non-Exposure
- **Token Generation**: Generated using a cryptographically secure pseudo-random number generator (CSPRNG) yielding 32 raw bytes (256 bits) encoded as base64url (`secrets.token_urlsafe(32)`).
- **One-Way Hashing**: The raw token is hashed immediately using SHA-256 (`token_hash = sha256(raw_token)`).
- **Zero-Storage Invariant**: Raw tokens are **never** persisted in the database. Only the hex-encoded SHA-256 digest `token_hash` is stored in `organization_invitations`.
- **Production API Exposure Policy**:
  - `DEFAULT PRODUCTION RAW TOKEN EXPOSURE: False`.
  - Normal production `POST /api/v1/organizations/current/invitations` responses **never** return `raw_token` or `invite_url` (`raw_token: None`, `invite_url: None`).
  - List endpoints (`GET /api/v1/organizations/current/invitations`) **never** expose `raw_token` or `token_hash`.
  - Raw tokens are never written to application logs, audit logs, or analytics.

### 2.2 Development & Test Token Access Mechanism
- **Configuration Gate**: `BOP_INVITATION_DEV_TOKEN_EXPOSURE=true` (or setting `container.settings.invitation_dev_token_exposure = True`).
- **Production Hard-Disable**: In production environments (`AppEnvironment.PRODUCTION`), dev token exposure is strictly forced to `False`.
- **Safe Test Access**: Automated tests and background workers can also directly receive `(invitation, raw_token)` through service-level creation (`InvitationService.create_invitation(...)`) without exposing tokens over HTTP.

### 2.3 Email Delivery State & Truthful Status
- **Email Provider Status**: `DEFERRED`. No third-party email delivery service (e.g. SendGrid, Postmark, AWS SES, SMTP) is configured in this release.
- **Truthful Delivery Status**: The API reports `delivery_status: "not_configured"`.
- **Truthful UI Wording**: The UI never claims "Invitation sent" when no mailer exists. It displays truthful phrasing: "Invitation created" / "Invitación creada", with "Created" / "Creada" timestamps.

### 2.4 Expiration & Lifecycle State Machine
- **Default TTL**: Invitations default to a 7-day expiration window (`expires_at = utcnow() + 7 days`).
- **Canonical Statuses**: `PENDING`, `ACCEPTED`, `REVOKED`, `EXPIRED`.
- **State Transitions**:
  - `PENDING` -> `ACCEPTED`: Triggered on successful atomic acceptance.
  - `PENDING` -> `REVOKED`: Triggered by an authorized tenant admin revoking the invitation.
  - `PENDING` -> `EXPIRED`: Evaluated dynamically when `utcnow() > expires_at`.
- **Duplicate Prevention**: An active `PENDING` invitation for a given email within an organization prevents creating another until revoked or expired (`409 Conflict`).
- **Existing Member Protection**: An invitation cannot be issued to an email address that already holds active membership in the organization (`409 Conflict`).

---

## 3. RBAC & Invitation Permission Matrix

BopClients enforces strict role boundaries for invitation issuance, visibility, and revocation:

| Action | OWNER | ADMIN | MEMBER | VIEWER |
| :--- | :---: | :---: | :---: | :---: |
| **List Pending Invitations** | Allowed | Allowed | Denied (403) | Denied (403) |
| **Invite ADMIN** | Allowed | Denied (403) | Denied (403) | Denied (403) |
| **Invite MEMBER / VIEWER** | Allowed | Allowed | Denied (403) | Denied (403) |
| **Invite OWNER** | Denied (422)* | Denied (422)* | Denied (403) | Denied (403) |
| **Revoke Any Invitation** | Allowed | Denied (403) | Denied (403) | Denied (403) |
| **Revoke MEMBER / VIEWER Invitation** | Allowed | Allowed | Denied (403) | Denied (403) |

\* Primary ownership transfer or direct owner invitation is strictly disallowed by domain rules.

---

## 4. Acceptance & Onboarding Workflows

### 4.1 Authenticated Acceptance (`POST /api/v1/invitations/accept`)
When an existing logged-in user navigates to `/invite/{token}`:
1. The client queries `GET /api/v1/invitations/{token}` for public metadata.
2. The user submits acceptance. The server validates that the authenticated user's email matches the invitation target email (case-insensitive).
3. **Email Mismatch Protection**: If the authenticated user is logged in under a different email address, the request is rejected with `403 Forbidden` (`INVITATION_EMAIL_MISMATCH`). The UI prompts the user to sign out and log in with the matching identity.
4. **Atomic Provisioning**: Upon successful match, an `organization_members` record is inserted with the assigned role, and the invitation status is set to `ACCEPTED`.

### 4.2 Registration & Acceptance (`POST /api/v1/invitations/register-and-accept`)
When a new collaborator arrives at `/invite/{token}`:
1. **Reusing Canonical Auth**: Reuses the pre-existing canonical `AuthService.register_user` pathway established in P19. No parallel auth system is introduced.
2. **Password Security**: Primary password hashing via Argon2id with 16-byte unique cryptographic salts. Plaintext passwords and hashes are never returned.
3. **Email Binding**: Account email is bound strictly to `invitation.email_normalized` (user cannot register an arbitrary email under someone else's token).
4. **Session Creation**: Authenticates immediately via canonical P19 `AuthService.authenticate`, returning HS256 JWT `access_token` and `bop_auth_sessions` session token.
5. **Transaction & Failure Semantics**: If member addition fails after user registration, an explicit compensation handler rolls back the created user from the database (`unauthorized partial membership possible: False`).

### 4.3 Public Invitation Verification (`GET /api/v1/invitations/{token}`)
- **Minimal Metadata**: Returns only `organization_name`, `organization_slug`, `email`, `role`, `status`, `expires_at`, `is_expired`.
- **Zero Internal ID Disclosure**: Omission of inviter user IDs (`invited_by_user_id`), organization internal UUIDs (`organization_id`), and global user UUIDs.
- **Anti-Enumeration**: Unauthenticated endpoint. Returns `404 Not Found` for invalid tokens and `410 Gone` for revoked or expired invitations.

---

## 5. Database Schema & Migration (`20260902_010`)

Migration `20260902_010` provisions table #33: `organization_invitations`.

```sql
CREATE TABLE organization_invitations (
    id VARCHAR(64) PRIMARY KEY,
    organization_id VARCHAR(64) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    role VARCHAR(32) NOT NULL,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    invited_by_user_id VARCHAR(64) NOT NULL REFERENCES users(id),
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    accepted_at TIMESTAMP WITH TIME ZONE,
    revoked_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX ix_org_invitations_token_hash ON organization_invitations(token_hash);
CREATE INDEX ix_org_invitations_org_status ON organization_invitations(organization_id, status);
CREATE INDEX ix_org_invitations_org_email ON organization_invitations(organization_id, email, status);
```

---

## 6. Frontend & User Experience

- **Settings Page (`/settings`)**:
  - Dedicated "Pending Invitations" section accessible to Owners and Admins.
  - "Invite Member" modal with truthful "Create Invitation" action.
  - Displays truthful delivery status and "Created" timestamp.
  - Development token link modal shown only when dev token exposure is enabled.
  - Secure revocation dialog with confirmation modal.
- **Acceptance Landing Page (`/invite/{token}`)**:
  - Clear invitation preview displaying organization name, role, and invited email.
  - Scenario 1: Authenticated user with matching email -> single-click acceptance.
  - Scenario 2: Authenticated user with email mismatch -> clear warning and sign-out prompt.
  - Scenario 3: Unauthenticated user -> in-place account registration and immediate onboarding via canonical auth.
- **Full Localization**: Complete 100% key parity between English (`en.json`) and Spanish (`es.json`) across all settings and invitation flows.
