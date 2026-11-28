# KLD-007C slice 3 staff role management

The owner-only API manages staff metadata after an explicit migration. Financial access and organization discovery retain the previous compatibility policy. A request uses the current session identity and requires both organization ownership and legacy ownership on the mapped default branch. Permissions come from the database. Staff changes are restricted to organization MEMBER accounts and reject accounts with any legacy OWNER grant in the organization. This slice exposes no path to remove or demote an owner or create a legacy owner. Manual database ownership changes remain subject to the [ownership-drift procedure](KLD-007B-legacy-migration.md#ownership-drift-and-approval).

## API

Paths are relative to `/api/v1/organizations/{organization_id}/staff`. All require an owner bearer. Writes are rate-limited and return HTTP 204 on success.

| Method and path | Operation |
| --- | --- |
| GET collection | List staff and current assignments. A member with no assigned branch has null branch and role fields. The response is private and marked no-store. |
| POST `/{user_id}/branches` | Add a branch assignment using JSON `branch_id` and `role`. The account must already be a member via an accepted staff invitation. |
| PATCH `/{user_id}/branches/{branch_id}` | Change the current assignment using JSON `role`. Roles are MANAGER, CASHIER and ACCOUNTANT. |
| DELETE `/{user_id}/branches/{branch_id}` | Revoke that assignment and cancel pending invitations containing that branch for the same member and organization. |
| POST `/{user_id}/branches/{branch_id}/reassign` | Move an assignment to the destination `branch_id` and `role` in the JSON body. Revocation, new assignment, pending-link cancellation and audit commit together. |
| DELETE `/{user_id}` | Revoke staff membership, all of its assignments and pending invitations in that organization. |

Each write rechecks authority and scope inside the SQLite writer transaction. Success audit records include actor, organization, affected user, branch where applicable, action, previous/new role where applicable and UTC time. Reassignment produces paired revocation and grant records. A known authenticated member denied management authority within their organization generates a redacted denial with the attempted action. Unknown, foreign, unauthenticated and malformed attempts use existing redacted HTTP outcome logging, without adding unverified target identifiers to tenant audit. Rejected input cannot create speculative grants.

Revocation takes effect on new policy checks, including from an existing session, and leaves unrelated memberships intact. Cancelling pending links prevents pre-revocation invitations from restoring the grant. Issuing a new invitation after revocation requires a current owner action. The staff list authorizes and reads in one snapshot. An in-flight snapshot can reflect authorization from before a concurrent revocation committed. Some legacy read handlers still authorize before opening their ledger snapshot. Resolve those races and validate eventual staff endpoints before activating access.

## Migration and rollback

After the explicit [v1 mapping](KLD-007B-legacy-migration.md) and [v2 invitation migration](KLD-007C-staff-invitations.md), take a verified backup of an isolated, quiesced synthetic database. Run:

```powershell
python -m app.db.staff_permissions_migration C:/synthetic/staff.sqlite --dry-run
python -m app.db.staff_permissions_migration C:/synthetic/staff.sqlite
```

Version three adds only an append-only audit table and guards against updates, deletes and replacement. DDL and version recording commit atomically. Dry-run and failures roll back. Reapplying is idempotent, and application startup never migrates. Older schema tooling is for its documented version only. After use, retain permissions and audit rows during rollback and follow the existing verified backup and financial reconciliation procedure. Old builds lack these management endpoints and should never be used to circumvent live access policy.

Staff financial routes, mapped-only activation, billing, subscriptions, production email delivery and deployment remain disabled. Future activation still requires complete branch mappings, atomic provisioning, an owner-change design with transactional last-owner protection if introduced, end-to-end read and revocation review, audit retention and explicit product-owner approval. DigitalOcean remains paused and real trader onboarding remains NO-GO.
