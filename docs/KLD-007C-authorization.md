# KLD-007C authorization coverage and rollout

Baseline `c414213bf087235f05e952c9263b5fdcd9b9d4fb` passed the [combined main release gate](https://github.com/AgbajiAlexander/kudiledger_AI/actions/runs/46141595502/job/140968777468). The 007B migration remains an explicit operator command. The owner-approved solo-development process requires green CI, AI-assisted technical review and a separate product-owner merge decision. AI assistance is not independent human approval.

## Endpoint coverage

All paths below use the existing FastAPI prefix `/api/v1` unless marked otherwise. Phase 1 allows only verified legacy owners on legacy branch paths. A mapped default branch additionally requires a current organization OWNER membership. New discovery allows an organization owner to list that organization's branches. The role policy is exercised in synthetic fixtures without exposing staff access. No endpoint accepts a client role.

| Route or route group | Authorization in first slice | Activation decision and coverage |
| --- | --- | --- |
| `/health`, `/app`, OpenAPI and documentation routes | Public infrastructure or static shell | No financial data |
| Login, password reset and completion, invite completion | Existing identity, rate limits and single-use credentials | Existing owner provisioning only; no staff invites |
| Logout | Active session; revokes submitted bearer | Session tests |
| `/auth/businesses` | Same legacy owner policy as business endpoints | Deny revoked mapped owners; unchanged response shape |
| `/auth/organizations`, `/organizations/{org}/branches` | Active organization owner; database-derived organization and branches | No cross-organization disclosure; no staff discovery |
| Business customer create, sale create, repayment create, expense create | Legacy owner; resolve inside writer transaction | Future manager/cashier ordinary writes only on assigned branch; deny legacy staff |
| Business debt adjustment and sale reversal create | Legacy owner; resolve inside writer transaction | Retain owner-only and confirmed financial rules |
| Business customer list, balance, repayment list, adjustments list, statement; expense list and summary; reversal list; daily report; transaction lookup; receipts | Legacy owner; object queries stay branch-scoped | Separate role capabilities before any staff API exposure; receipt, lookup, and Lagos report regression |
| Recovery list; prepare, submit, check, acknowledge and delete | Legacy owner and initiating user; mutations authorize in writer transaction | Preserve payload, reference uniqueness and idempotency; test revocation after prepare |
| Operator recovery list, audit and decisions | Legacy owner and explicit legacy operator grant; existing decision transaction | Future separate case-scoped support authority; no implicit operator access |
| Host operator grant/revoke CLI | Trusted host operator, existing business membership | No permission-changing HTTP endpoint in this slice; review host controls before activation |

## Small PRs and activation gates

1. **Resolver and discovery.** Explicit known capabilities, live session lookup, deny unknown roles or missing/mismatched associations, owner-only legacy compatibility and read-only discovery, no schema change. Preserve old databases and fail closed on invalid tenant associations. Review exact baseline API/financial/recovery behavior and the synthetic security matrix.
2. **Staff invitation and assignment infrastructure.** Add scoped expiring single-use invitations and assignments with live issuer authorization and branch constraints, behind inactive staff access. Test replay, cross-tenant substitutions, duplicate acceptance, credentials, and rollback of pending invites. Keep schema additive.
3. **Role grants, revocation and audit.** Build transactional role changes and append-only audit. Reject removal/demotion of the last active owner inside the same write transaction, including competing requests. Test immediate revocation, read/write races and support separation. Owner mutation is absent in the first slice.
4. **Controlled compatibility and activation.** Inventory every financial and permission-changing route against the matrix, close read snapshot/revocation and new provisioning gaps, test legacy and explicit staff paths, concurrent writes and recovery, then seek explicit activation approval. Older builds are suitable only while metadata remains inactive and no grants have operative effect.

Each PR runs the full release gate and synthetic authorization, receipts, Lagos reporting, recovery and account lifecycle regressions. Staff access, branch-switching UI, consolidated reporting, entitlements and payment processing remain gated. DigitalOcean is paused and real trader onboarding is NO-GO.

An unmigrated database, or a business newly provisioned by the legacy owner flow without a mapping, still uses the legacy owner row. A partly present version-one schema fails closed. Version-one metadata is read-only to the application. Before activation, require complete coverage of migrated branch mappings and prevent a missing mapping from falling back to legacy authorization. Read-only legacy handlers that authorize before taking their ledger snapshot also require a revocation-race review before staff activation.
