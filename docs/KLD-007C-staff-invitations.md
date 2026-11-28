# KLD-007C staff invitations and branch assignments

This slice stages staff membership and branch grants. Current financial, receipt, recovery, discovery and reporting endpoints retain the owner rules from [slice 1](KLD-007C-authorization.md). Staff acceptance writes an organization MEMBER and branch-role records only. Existing independent business ownership is preserved. There is no staff UI, ledger authorization switch, subscription check or payment processing.

## Explicit migration

Take a verified backup of the quiesced synthetic database. Apply and reconcile the [version-one mapping](KLD-007B-legacy-migration.md) first. Then run the following from the repository with pinned dependencies, substituting the synthetic copy's path.

```powershell
python -m app.db.staff_migration C:/synthetic/legacy.sqlite --dry-run
python -m app.db.staff_migration C:/synthetic/legacy.sqlite
```

Version two adds staff invitations, their branch grants and an append-only audit table. Composite foreign keys bind each branch selection to the same organization as its invitation. SQLite DDL and the version marker commit together under an immediate transaction. Dry-run rolls back, and repeat apply preserves the existing schema and metadata. Startup never applies this migration. The version-one mapping and reconciliation tools target v1 snapshots; do not use them to repair a database containing staff grants.

## Capture-only API

For a synthetic loopback demo use existing mail capture configuration. API issuance, acceptance and revocation are disabled when capture mode is off or SMTP. Staff invitations allow only normalized `.test` recipients. Capture files are private, outside the repository, and contain short-lived credentials. Keep them out of logs, screenshots, Git and review artifacts.

| Endpoint | Request and authorization |
| --- | --- |
| `POST /api/v1/organizations/{organization_id}/staff-invitations` | Owner bearer and JSON with `email` and `branches`, each with `branch_id` and `role` (`MANAGER`, `CASHIER` or `ACCOUNTANT`). Requires both live owner grants. Returns only the invitation ID. |
| `POST /api/v1/auth/staff-invitations/accept` | Put the token from the captured `#staff-invite` fragment in the JSON `token` field. An existing recipient must use their own active bearer and omit `password`. A new recipient supplies a new synthetic password and no bearer. The one-time link proves control of the addressed inbox in the eventual workflow; local capture simulates that control. |
| `DELETE /api/v1/organizations/{organization_id}/staff-invitations/{invitation_id}` | Owner bearer. Revokes an unaccepted invitation within the requested organization. |

Tokens have 256 bits of entropy, expire after 24 hours, and are stored only as SHA-256 digests. Invitation issuance, acceptance and revocation are rate-limited. Acceptance rechecks both issuer grants, organization/branch pairs, roles, recipient and duplicate assignments inside one SQLite writer transaction. Credential creation, organization and branch grants, acceptance and audit commit together. An existing pending invitation blocks a second invite for the same scoped email. A pending or accepted staff role cannot replace existing owner permissions or overwrite assignments through this API.

## Rollback and activation boundaries

Use a compatible build with capture turned off to halt the workflow and retain auditable history. An older build cannot grant staff financial access, but its restore command does not know to revoke new invitation links. Use the updated restore tooling, which revokes unaccepted staff links and preserves accepted grants and audit records alongside the existing session and account-link controls. A restore is subject to the existing stop-writes and reconciliation procedure. Never replace a financial database just to remove staff metadata.

The capture directory simulates email delivery and must be controlled by the tester. Production delivery, audited role changes and revocation, last-owner protection, complete mapped-only authorization, privacy retention, and an explicit product-owner activation decision remain open. DigitalOcean is paused and real trader onboarding remains NO-GO.
