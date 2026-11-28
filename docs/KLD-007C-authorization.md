# KLD-007C authorization coverage and rollout

Baseline `c414213bf087235f05e952c9263b5fdcd9b9d4fb` passed the [combined main release gate](https://github.com/AgbajiAlexander/kudiledger_AI/actions/runs/46141595502/job/140968777468). The 007B migration remains an explicit operator command. The owner-approved solo-development process requires green CI, AI-assisted technical review and a separate product-owner merge decision. AI assistance is not independent human approval.

## Endpoint coverage

All paths below use the existing FastAPI prefix `/api/v1` unless marked otherwise. During compatibility, effective ownership of a mapped organization requires both its current organization OWNER membership and a current legacy OWNER membership on its mapped default branch. Either removal revokes discovery and legacy access on the next request, including with an existing session, and leaves ownership of unrelated organizations intact. A fully authorized owner can discover all branches in that organization. The role policy is exercised in synthetic fixtures without exposing staff access. No endpoint accepts a client role.

| Route or route group | Authorization in first slice | Activation decision and coverage |
| --- | --- | --- |
| `/health`, `/app`, OpenAPI and documentation routes | Public infrastructure or static shell | No financial data |
| Login, password reset and completion, invite completion | Existing identity, rate limits and single-use credentials | Existing owner provisioning only; no staff invites |
| Logout | Active session; revokes submitted bearer | Session tests |
| `/auth/businesses` | Same legacy owner policy as business endpoints | Deny revoked mapped owners; unchanged response shape |
| `/auth/organizations`, `/organizations/{org}/branches` | Effective ownership requires both owner records on the mapped default branch | Revocation of either grant denies disclosure; no staff discovery |
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

The application pins `LegacyScope.COMPATIBILITY`. An unmigrated database, or a business without a mapping after legacy provisioning, can use its verified legacy OWNER membership. An unmapped business is excluded from organization discovery. A partly present version-one schema fails closed in both policy modes. Version-one metadata is read-only to the application.

The resolver requires each caller to select its legacy scope explicitly. `LegacyScope.MAPPED_ONLY` is tested as the future activation boundary and rejects unmapped businesses even when a legacy OWNER grant exists. It continues to require both grants on mapped default branches and never authorizes a non-default branch through a legacy URL. This mode is an internal policy, with no deployment toggle or staff activation in this slice. Before activation, verify complete mappings, make provisioning atomic with mapping creation, reconcile ownership drift, and switch all relevant entry points to the mapped-only policy. Read-only legacy handlers that authorize before taking their ledger snapshot also require a revocation-race review before staff activation.
