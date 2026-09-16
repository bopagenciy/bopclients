# Account Recovery & Email Verification (Phase P26)

## 1. Overview
Phase P26 establishes a cryptographically secure, enterprise-grade account recovery and email verification architecture for BopClients. Built atop the P19 authentication system and P25 transactional email foundation, it provides self-service password recovery, email ownership verification, and automatic verification upon invitation onboarding while strictly adhering to zero-trust security invariants.

---

## 2. Security Model & Invariants

### 2.1 Enumeration & Timing Attack Mitigation
- **Neutral Response Guarantee**: The `POST /api/v1/auth/password-reset/request` endpoint unconditionally returns HTTP 200 with an identical payload (`success: true, message: "If the email is registered in BopClients, a password recovery link has been sent."`), regardless of whether the submitted email exists in the database.
- **Constant-Timing Resistance**: In the event of a non-existent email, a dummy cryptographic hash calculation is executed to neutralize timing discrepancies that could otherwise be exploited for user enumeration.
- **Zero Existence Leaks**: The system logs and API responses never confirm or deny user existence to unauthenticated callers.

### 2.2 Token Generation & Zero-Storage Storage Policy
- **Cryptographic Randomness**: Tokens are generated using `secrets.token_urlsafe(32)` (providing 256 bits of high entropy from OS CSPRNG).
- **One-Way Digest Invariant**: Raw tokens are hashed immediately with SHA-256 (`hashlib.sha256(raw_token.encode('utf-8')).hexdigest()`).
- **Zero Plaintext Persistence**: Raw tokens are **never** persisted in PostgreSQL or SQLite. Only the SHA-256 digest is stored in `auth_tokens.token_hash`.
- **Zero Plaintext Logging**: Raw tokens are strictly excluded from server log outputs, audit trails, and API responses. The raw token exists exclusively within the transitively dispatched transactional email URL.

### 2.3 Single-Use Replay Protection & Expiration Policies
- **Strict Expiration Windows**:
  - **Password Reset**: Configurable via `PASSWORD_RESET_TOKEN_EXPIRE_MINUTES` (default: 60 minutes).
  - **Email Verification**: Configurable via `EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS` (default: 24 hours).
- **Single-Use Consumption**: Upon confirmation, the token record is stamped with `consumed_at = utcnow()`.
- **Replay Invalidation**: Any subsequent confirmation attempt using a previously consumed token is rejected with HTTP 400 (`INVALID_TOKEN`).
- **Prior Token Revocation**: Issuing a new token for a given user and token type automatically revokes all prior unconsumed tokens for that user and type (`revoke_active_tokens_for_user`).

### 2.4 Password Update & Session Invalidation
- **Argon2id Hashing**: New passwords are validated (minimum 8 characters) and hashed using Argon2id with memory, time, and parallelism parameters defined in `PasswordHasher`.
- **Atomic Session Revocation**: Confirming a password reset immediately revokes all active refresh tokens and sessions for the user (`session_repo.revoke_all_user_sessions(user_id)`), terminating compromised or active sessions across all devices.

---

## 3. Email Verification Policy & Invitation Onboarding

### 3.1 Unverified User Lifecycle
- Users registered via normal self-service onboarding begin with `email_verified_at: None` (`is_verified: False`).
- The application layout presents an unverified banner (`UnverifiedEmailBanner`) alerting users to check their inbox, with an authenticated "Resend Verification Email" action.

### 3.2 Invitation Acceptance Policy (Automatic Verification)
- **Ownership Rationale**: When a prospective collaborator accepts an invitation via `POST /api/v1/invitations/register-and-accept`, they have proven control over the target inbox by clicking the unique, cryptographically signed invitation URL sent to that exact address.
- **Atomic Verification**: The registration pipeline sets `email_verified_at = utcnow()` (`is_verified = True`) automatically upon invitation registration, eliminating redundant verification friction for invited team members.

---

## 4. API Endpoints & Contracts

### 4.1 Password Recovery Request
- **Endpoint**: `POST /api/v1/auth/password-reset/request`
- **Authentication**: Public
- **Request Body**:
  ```json
  {
    "email": "user@example.com",
    "locale": "es"
  }
  ```
- **Response**: `200 OK`
  ```json
  {
    "success": true,
    "message": "If the email is registered in BopClients, a password recovery link has been sent."
  }
  ```

### 4.2 Password Recovery Confirmation
- **Endpoint**: `POST /api/v1/auth/password-reset/confirm`
- **Authentication**: Public
- **Request Body**:
  ```json
  {
    "token": "dGVzdC1yYXctdG9rZW4tdXJsc2FmZS0zMg",
    "new_password": "NewSecurePassword123!"
  }
  ```
- **Response**: `200 OK`
  ```json
  {
    "success": true,
    "message": "Password has been successfully updated. You may now sign in."
  }
  ```
- **Error Codes**:
  - `400 Bad Request` (`INVALID_TOKEN`): Token expired, invalid, or already consumed.
  - `422 Unprocessable Content` (`WEAK_PASSWORD`): Password fails length or complexity rules.

### 4.3 Email Verification Confirmation
- **Endpoint**: `POST /api/v1/auth/email-verification/confirm`
- **Authentication**: Public
- **Request Body**:
  ```json
  {
    "token": "dGVzdC12ZXJpZnktdG9rZW4tdXJsc2FmZQ"
  }
  ```
- **Response**: `200 OK`
  ```json
  {
    "success": true,
    "message": "Email address has been successfully verified."
  }
  ```

### 4.4 Email Verification Resend
- **Endpoint**: `POST /api/v1/auth/email-verification/resend`
- **Authentication**: Required (`Bearer` Access Token or BFF session)
- **Request Body**:
  ```json
  {
    "locale": "es"
  }
  ```
- **Response**: `200 OK`
  ```json
  {
    "success": true,
    "message": "Verification email has been sent."
  }
  ```

---

## 5. Database Schema & Migration (`20260902_011`)

The dedicated migration `20260902_011` introduces the `auth_tokens` table and updates `users`:

### 5.1 `auth_tokens` Table Schema
```sql
CREATE TABLE IF NOT EXISTS auth_tokens (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_type VARCHAR(30) NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    expires_at VARCHAR(50) NOT NULL,
    consumed_at VARCHAR(50) NULL,
    created_at VARCHAR(50) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auth_tokens_token_hash ON auth_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_type ON auth_tokens(user_id, token_type);
```

### 5.2 `users` Table Enhancement
```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at VARCHAR(50) NULL;
```

---

## 6. Email Templates & Localization

- **Supported Locales**: English (`en`) and Spanish (`es`).
- **Templates**:
  - `render_password_reset_email(recipient_name, reset_url, locale)`: Responsive HTML email and plain-text fallback with security notices and expiry guidance.
  - `render_email_verification_email(recipient_name, verification_url, locale)`: Responsive HTML email and plain-text fallback with direct action link.
- **Email Dispatcher**: Integrated with `ITransactionalEmailSender` (`ResendTransactionalEmailSender` in production, `InMemoryTransactionalEmailSender` in test).

---

## 7. Frontend Pages & Components

| Route / Component | Description |
| :--- | :--- |
| `/[locale]/forgot-password` | Self-service email submission form with enumeration protection. |
| `/[locale]/reset-password/[token]` | Password update form with 8-character client/server validation. |
| `/[locale]/verify-email/[token]` | Direct token verification landing page with auto-confirmation. |
| `UnverifiedEmailBanner` | In-app notification for unverified accounts with resend action. |
| `/[locale]/login` | Updated with a "Forgot your password?" recovery shortcut link. |
