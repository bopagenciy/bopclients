# Transactional Email Delivery Foundation (P25)

## 1. Overview
Phase P25 establishes the transactional email delivery foundation for BopClients. It replaces placeholder invitation delivery states with a provider-agnostic transactional email architecture, featuring first-party bilingual templates (EN/ES), truthful delivery reporting, cryptographic token rotation on resend, and strict secret hygiene.

---

## 2. Architecture & Domain Contracts

### 2.1 Provider-Neutral Abstraction
The system defines a clean hexagonal abstraction between domain services and email transport providers:

- **Interface**: `ITransactionalEmailSender` (`bopclients/application/interfaces/email_sender.py`)
  - `send(message: TransactionalEmailMessage) -> EmailDeliveryResult`
- **Domain Value Objects** (`bopclients/domain/email.py`):
  - `EmailCategory`: Categorization (`TEAM_INVITATION`).
  - `EmailDeliveryStatus`: Truthful status outcomes (`SENT`, `FAILED`, `NOT_CONFIGURED`).
  - `TransactionalEmailMessage`: Immutable message containing `to`, `from_email`, `subject`, `html_body`, `text_body`, `category`, and `metadata`.
  - `EmailDeliveryResult`: Immutable result containing `status`, `message_id`, `error`, and `timestamp`.

### 2.2 Implemented Providers
1. **`ResendEmailSender`** (`bopclients/infrastructure/email/resend_sender.py`):
   - Transmits emails via the Resend REST API (`https://api.resend.com/emails`).
   - Uses `httpx.Client` with connection pooling, strict timeouts, and error handling.
   - Sanitizes error messages to guarantee API keys are never leaked into logs or error envelopes.
2. **`InMemoryEmailSender`** (`bopclients/infrastructure/email/in_memory_sender.py`):
   - Stores dispatched messages in memory for automated integration testing and local offline development.
   - Exposes `get_sent_messages()`, `get_last_message()`, and `clear()`.
3. **`NullEmailSender`** (`bopclients/infrastructure/email/null_sender.py`):
   - Default fallback when no provider or credentials are configured.
   - Truthfully reports `status=EmailDeliveryStatus.NOT_CONFIGURED` without raising unhandled exceptions.

---

## 3. Configuration & Secret Hygiene

Transactional email behavior is governed by `RuntimeSettings` (`bopclients/runtime/settings.py`):

| Environment Variable | Setting | Default | Description |
| :--- | :--- | :--- | :--- |
| `BOP_EMAIL_PROVIDER` | `email_provider` | `"none"` | Provider selection: `"resend"`, `"in_memory"`, or `"none"` |
| `BOP_EMAIL_FROM` | `email_from` | `"BopClients <invites@bopclients.com>"` | Default sender address |
| `BOP_EMAIL_API_KEY` | `email_api_key` | `""` | Third-party provider API key (e.g. Resend `re_...`) |
| `BOP_APP_URL` | `app_url` | `"http://localhost:3000"` | Canonical base URL for invitation links |

### Secret Hygiene Rules
- `email_api_key` is strictly excluded from `RuntimeSettings.safe_summary()`.
- API keys are never printed in application logs or returned in REST API envelopes.
- Provider errors are sanitized before being attached to `EmailDeliveryResult`.

---

## 4. Bilingual Email Templates

Bilingual templates are defined in `bopclients/application/email_templates.py`:

- **Locales Supported**: English (`en`) and Spanish (`es`).
- **Responsive Layout**: Designed for mobile and desktop mail clients with table-based markup, dark-mode styling, gold branding highlights, and distinct CTA buttons.
- **Plain-Text Fallback**: Multi-part email delivery includes fully formatted text fallback for terminal mail clients and accessibility tools.
- **XSS & Injection Protection**: All dynamic attributes (`organization_name`, `inviter_name`, `role`, `invite_url`) are HTML-escaped with `html.escape()`.

---

## 5. Token Rotation Invariant on Resend

When a tenant administrator requests to resend a pending team invitation:

- **Endpoint**: `POST /api/v1/organizations/current/invitations/{invitation_id}/resend`
- **Token Rotation Invariant**:
  1. A new 32-byte cryptographically secure raw token is generated (`secrets.token_urlsafe(32)`).
  2. The SHA-256 hash of the new token (`token_hash = sha256(new_raw_token)`) replaces the old hash in `organization_invitations`.
  3. The invitation expiration (`expires_at`) is reset to 7 days from the current timestamp.
  4. The previous token is **immediately invalidated**. Any attempt to inspect or accept using the old token fails (`404 Not Found`).
  5. A fresh invitation email is rendered and dispatched with the newly generated token link.
- **RBAC & Isolation Rules**:
  - `OWNER` can resend invitations for any role (`admin`, `member`, `viewer`).
  - `ADMIN` can resend invitations for `member` and `viewer`.
  - `ADMIN` cannot resend invitations for `admin` or `owner` (`403 Forbidden`).
  - `MEMBER` and `VIEWER` cannot resend invitations (`403 Forbidden`).
  - Cross-tenant isolation prevents accessing or resending invitations across organizations (`404 Not Found`).
  - Accepted invitations cannot be resent (`409 Conflict`).
  - Revoked invitations cannot be resent (`410 Gone`).

---

## 6. Frontend Integration

The Settings UI (`apps/web/app/[locale]/(app)/settings/page.tsx`) provides complete visibility and control over team invitation delivery:

- **Delivery Status Badges**:
  - `sent`: Emerald badge indicating successful email transmission.
  - `failed`: Rose badge indicating provider delivery error (with sanitized tooltip).
  - `not_configured`: Neutral outline badge indicating simulated / offline environment.
- **Resend Action**: Interactive resend button per pending invitation that triggers token rotation, updates local status, and notifies the user upon success.
- **Locale Propagation**: Invitation creation and resend propagate the active UI locale (`en` or `es`) so the recipient receives an appropriately localized email.

---

## 7. Database Migration Policy

- **Migrations Added in P25**: **0** (Zero).
- Current database schema version remains strictly at `20260902_010`.
