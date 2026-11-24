# KLD-007B legacy SQLite migration

This milestone adds metadata for organizations, branches, organization memberships and branch assignments. It keeps every existing ledger and identity table as-is. Each legacy business keeps its ID as its default branch ID, receives a separate organization ID, and maps its existing owners to that organization. An account owning two legacy businesses remains an owner of two distinct organizations. Branch assignments start empty. No runtime route uses the new tables for authorization, and startup does not run the migration.

## Synthetic rehearsal

Use a disposable copy of a fully initialized legacy database. Stop writers during an approved rehearsal or rollout. Back up using SQLite's verified snapshot tool. Run from the repository root with the pinned dependencies and substitute synthetic paths outside the repository.

```powershell
python -m app.operations.pilot backup C:/synthetic/legacy.sqlite C:/synthetic/before.sqlite
python -m app.db.migrations C:/synthetic/legacy.sqlite --dry-run
python -m app.db.migrations C:/synthetic/legacy.sqlite
python -m app.db.migrations C:/synthetic/legacy.sqlite
python -m app.operations.pilot backup C:/synthetic/legacy.sqlite C:/synthetic/after.sqlite
```

The migration uses one SQLite writer transaction for versioning, additive DDL, mapping, and validation. Dry-run rolls everything back. An unchanged database returns zero new mappings on a second apply. If legacy provisioning creates a business while compatibility mode is active, run the migration again explicitly before relying on the mapping. Existing mappings are validated and reused. Resolve ownerless businesses or mapping conflicts before proceeding. Never run the version-one tool as a repair tool on a future activated SaaS database.

Use the backup digest with the existing restore procedure and a new destination. Verify legacy IDs, exact balances, scoped receipts, original references, recovery status and both audit streams against the pre-migration rehearsal. Restore deliberately invalidates sessions and pending account links. [Backup and restore drill](pilot-operations.md#backup-and-restore-drill)

```powershell
python -m unittest -v tests.test_legacy_migration
```

The tests build synthetic pre-migration snapshots and compare existing table contents and schema definitions, including financial constraints and triggers, before and after migration. They also inject a failure after the backfill, test organization/branch foreign keys, and restore a migrated snapshot before exercising legacy receipt and recovery routes.

## Rollback

Before any future application reads or writes the metadata, the legacy build can use the expanded database because its ledger and account schema is unchanged. A failed migration rolls back in place. A restore requires a verified copy and owner approval. Freeze writes and reconcile every financial and recovery effect created after the snapshot before replacing a database. DigitalOcean provisioning stays paused and real trader onboarding remains NO-GO.
