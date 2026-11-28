# KLD-007C slice 4 authorization and activation readiness

**Staff activation is NO-GO.** This slice hardens the current owner-only application. It adds no staff financial route, production mode switch, schema migration, or owner-removal operation.

## Protected reads and revocation

| Endpoint group | Authorization and data boundary |
| --- | --- |
| Customer list and balances, repayment list, statement, debt adjustments, sale reversals, expense list and summary | One explicit SQLite read transaction through the shared authenticated branch-read context. Lower-level reads use the same connection. |
| Sale, repayment and expense lookup and receipts | Same branch-read context, with existing business and object predicates. |
| Daily financial reports | Authorization, period aggregates and current debt share one snapshot. UTC storage, Lagos date bounds and kobo calculations follow the existing definitions. |
| Recovery list, operator recovery list and operator audit | Existing database snapshots resolve the active actor, business, initiating user or operator grant and then read data. Recovery check is a state transition and retains its writer transaction. |
| Legacy business, organization and branch discovery, organization staff list | Existing explicit read transactions, with dual effective ownership for mapped owner access. |

A snapshot starts when SQLite first reads within the transaction. A committed revocation blocks newly started authorization checks. An in-flight read whose snapshot predates revocation may finish with authorized **pre-commit** data. It cannot combine old authorization with data committed after revocation. The application materializes response data before leaving the snapshot. It cannot recall a response already being sent. Financial writes retain their immediate transaction and recheck authorization after acquiring the writer slot. A write serialized before revocation may commit; a queued write that is serialized after revocation is denied.

## Mapping and ownership reconciliation

Take a verified SQLite backup of a quiesced database and run the read-only verifier on the standalone snapshot:

```powershell
python -m app.operations.tenant_readiness C:/synthetic/readiness-snapshot.sqlite
```

Require `passed: true` and zero issues. A nonzero exit blocks activation. The tool emits counts for missing, duplicate or conflicting mappings, incorrect default counts, misplaced legacy owner grants, drift in either owner set, organizations with no effective owner, orphaned/cross-organization assignments and SQLite integrity errors. It cannot infer whether an otherwise internally consistent mapping reflects intended historical ownership. Compare the private mapping inventory against approved provisioning and migration records before operator sign-off. The verifier changes neither its input nor the source database. [Synthetic report](KLD-007C-synthetic-activation-readiness.json)

For a discrepancy, hold activation, freeze the affected ownership or assignment changes, and retain the verified snapshot. Record scoped evidence privately. An operator must establish the intended organization, branch and owner from prior records. Require security review and explicit product-owner approval of the exact correction, with a verified backup and audit trail. Use an independently reviewed correction procedure after approval, then regenerate the snapshot, reconciliation and financial evidence. Never infer grants or silently rewrite financial ownership, references or balances. The [ownership drift runbook](KLD-007B-legacy-migration.md#ownership-drift-and-approval) remains applicable.

An effective owner has both OWNER grants, including the legacy grant on the mapped default branch. Branch capability resolution also checks this intersection. This API exposes no owner removal or demotion, and mapped provisioning creates the first effective owner atomically. Direct SQL, older host tooling and database administrators can still remove the last effective owner. The report detects that state, and authorization fails closed for that organization. Protect database privileges and require a separately reviewed, transactional last-owner guard before adding any owner mutation.

## Controlled rollout and rollback

The application still pins `LegacyScope.COMPATIBILITY`. The internal `MAPPED_ONLY` policy has no runtime toggle. Synthetic tests deliberately select it and verify denial of unmapped businesses and partial schemas. That policy provisions owner credentials, both owner grants, organization and default branch in one write transaction through registration or invitation consumption. A failed mapping rolls back the entire operation, including invitation consumption. Compatibility registration still creates legacy-only records. The original v1 backfill rejects a v2 or v3 database. If unmapped businesses exist on those versions, hold activation until an approved additive reconciliation path is available.

Before a future policy switch, verify every mapping and owner, apply approved versions of the existing explicit migrations, and route all provisioning via the compatible owner transaction. Inventory all database writers, including low-level/demo tooling and any older instances. Mixed-version writers can create unmapped businesses or bypass new authorization, so freeze writes, retire incompatible instances, rehearse restore, and verify a fresh redacted report and CI before requesting approval. Keep compatible snapshots and a release rollback plan. Rolling back to an older application after staff permissions have operative effect is unsafe. Pause the feature and roll forward or restore only through the approved financial reconciliation procedure with all intervening writes accounted for.

Activation requires explicit product-owner approval, tested staff-specific ledger endpoints and end-to-end role coverage, verified mapping and migration evidence, authorization and mixed-version rehearsal, and the outstanding physical-device, infrastructure, and operational gates. DigitalOcean remains paused. Billing and live staff financial access remain disabled. Real trader onboarding remains NO-GO.
