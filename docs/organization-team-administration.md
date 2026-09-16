# Organization & Team Administration Foundation (P23)

## 1. Overview
The P23 release introduces tenant-scoped Organization & Team Member administration in BopClients. It establishes role-based access control (RBAC), multi-tenant isolation, last-owner invariants, truthful member listings, and safe self-management policies without schema migrations.

---

## 2. Role Policy & Member Management Permissions

BopClients enforces four canonical member roles: `OWNER`, `ADMIN`, `MEMBER`, and `VIEWER`.

| Action | OWNER | ADMIN | MEMBER | VIEWER |
| :--- | :---: | :---: | :---: | :---: |
| **List Organization Members** | Allowed | Allowed | Allowed | Allowed |
| **Update Member Role (MEMBER / VIEWER)** | Allowed | Allowed | Denied (403) | Denied (403) |
| **Update Member Role (OWNER / ADMIN)** | Allowed | Denied (403) | Denied (403) | Denied (403) |
| **Escalate Role to OWNER or ADMIN** | Allowed | Denied (403) | Denied (403) | Denied (403) |
| **Remove MEMBER / VIEWER** | Allowed | Allowed | Denied (403) | Denied (403) |
| **Remove OWNER or ADMIN** | Allowed* | Denied (403)** | Denied (403) | Denied (403) |
| **Update Organization Profile (Name)** | Allowed | Allowed | Denied (403) | Denied (403) |

\* Subject to Last-Owner Protection.
\** An ADMIN may remove themselves (self-removal) to leave an organization.

---

## 3. Last-Owner Protection Invariant

An organization must never lose its sole Owner:
- **Demotion Guard**: Any attempt to demote an `OWNER` to another role when only one Owner exists in the organization is rejected with HTTP `409 Conflict` (`code: LAST_OWNER_PROTECTION`, `message_key: errors.last_owner_protection`).
- **Removal Guard**: Any attempt to remove an `OWNER` when only one Owner exists is rejected with HTTP `409 Conflict`.
- **Multi-Owner Policy**: If an organization has two or more Owners, demoting or removing one Owner is permitted, preserving ownership continuity.

---

## 4. Removal Semantics

- **Tenant Membership Removal**: Invoking `DELETE /api/v1/organizations/current/members/{user_id}` deletes strictly the relationship row in the `organization_members` table.
- **Global User Safety**: The global user account in the `users` table is never deleted. The user retains their account, credentials, and memberships in any other organizations.
- **Self-Management**:
  - An `ADMIN` can remove themselves from an organization (leaves tenant).
  - An `OWNER` cannot remove themselves if they are the last Owner. If another Owner exists, self-removal is permitted.

---

## 5. Multi-Tenant Isolation

- **Scoped Queries**: All member queries and mutations enforce `organization_id` tenancy checks (`org_repo.get_member(tenant.organization_id, user_id)`).
- **Anti-Enumeration (404 Not Found)**: Attempting to query, update, or remove a member using a `user_id` that does not belong to the active tenant returns HTTP `404 Not Found` (`RESOURCE_NOT_FOUND`). No information about existence or membership in another tenant is revealed.
- **Immutable Global Identity**: `bop_organization_id` is strictly immutable. Attempts to alter it via API update payloads or repository persistence trigger validation/security errors.

---

## 6. Invitation Deferral

- **Add Existing User by Raw Email**: DEFERRED to prevent cross-tenant user enumeration attacks.
- **Team Invitations**: DEFERRED to a dedicated future phase requiring a cryptographic invitation token lifecycle (invitation table, secure hashing, expiration, email delivery provider, and acceptance confirmation flow).
- **Current Membership Provisioning**: Done via authorized tenant provisioning workflows or direct administrative assignment where identity is already established.

---

## 7. Known Limitations

- Self-service email invitation workflows and public sign-up onboarding remain deferred to a dedicated invitation/mailer milestone.
- Organization deletion and primary ownership transfer remain restricted platform-level operations.
