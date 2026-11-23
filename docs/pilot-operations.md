# Synthetic pilot operations

KLD-006B5 is for an isolated pilot using synthetic records only. Stop at independent review before deployment or onboarding. The later [supervised pilot guide](supervised-pilot.md) tracks staging, account lifecycle and current readiness checks. See the [architecture decision](pilot-architecture.md) and [recovery threat model](transaction-recovery.md) for the financial controls.

## Audited investigation

1. Ask the trader for the business, reference, transaction type and approximate Nigeria time. Do not request a password, session token, or full customer record.
2. A database host administrator can grant or revoke operator access for an existing member of that business. Review and record who approved the grant in the pilot's restricted incident log. Keep the host CLI available to the local administrator only.

   ```powershell
   .venv/Scripts/python.exe -m app.operations.pilot grant-operator --database $env:KUDILEDGER_DB --business-id $businessId --email $operatorEmail
   .venv/Scripts/python.exe -m app.operations.pilot revoke-operator --database $env:KUDILEDGER_DB --business-id $businessId --email $operatorEmail
   ```

3. Sign in as the granted operator. With that bearer token in memory, use `GET /api/v1/businesses/{business_id}/operator/recovery?reference=...` to locate the attempt. This endpoint lists blocked attempts for that business and omits original payloads. The normal recovery list remains private to the creating account.
4. Review the committed record via the existing business-authorized transaction lookup or receipt, plus the protected incident evidence. Submit the confirmed decision to `POST /api/v1/businesses/{business_id}/operator/recovery/{attempt_id}/decisions`.

   | Decision | Evidence type | When to use |
   | --- | --- | --- |
   | `retain_uncertain` | `inconclusive` | Evidence is incomplete. A missing record by itself belongs here. |
   | `confirm_committed` | `ledger_match` | The server can match the original fields and exact kobo values. |
   | `release_failed` | `ledger_conflict` | The server finds a different committed entry with that business, kind and reference. The original attempt could not use that reference. |
   | `release_failed` | `prewrite_failure` | Independent evidence establishes that a legacy worker stopped before writing and cannot resume. First verify that every legacy writer has stopped. The server also checks that the reference has no committed row. |

   The body includes `decision`, `evidence_type`, `evidence_reference`, `evidence_notes`, and `confirmed: true`. Use a protected incident or evidence ID and a concise account of what was checked. Human operators are responsible for authenticating evidence held outside KudiLedger. Ask a second reviewer to confirm a legacy failure determination before release. Preserve uncertainty if the evidence is incomplete.
5. Read `GET /api/v1/businesses/{business_id}/operator/recovery/{attempt_id}/audit` and capture the returned audit ID in the incident record. The append-only database record includes the acting operator, original account, scope, evidence, decision, UTC timestamp and any matching ledger ID. It survives removal of the recovery item. A release updates only the recovery outcome. The trader explicitly confirms any later financial entry.

Reproduce the operator procedure with `.venv/Scripts/python.exe -m unittest -v tests.test_recovery_operator`. It verifies denied access, an inconclusive investigation, a confirmed release, the retained audit after journal cleanup, and protection of committed sales.

## Backup and restore drill

Use an access-controlled local directory outside the repository on a filesystem that supports hard links, such as NTFS. On Windows, review the directory ACL for the pilot service and backup operator. On Unix, use a private directory owned by the backup operator. Protect file copies with encrypted storage and keep a separate protected copy of the checksum. Apply the pilot's recorded retention schedule, purge expired copies securely, and keep at least one tested copy separated from the host. Backups contain account hashes, references and financial details.

The backup command uses the SQLite online backup API. It includes the ledger, recovery journal and operator audit in one snapshot, validates integrity and foreign keys, and returns table counts and a SHA-256 checksum. Destinations must be new files. Restore validates the supplied checksum, verifies the database, revokes sessions in the restored copy, and leaves the source database and backup intact.

Run the drill against a synthetic database that has already started on KLD-006B5:

```powershell
$pilotBackupPath = Join-Path $env:LOCALAPPDATA 'KudiLedgerPilotBackups'
New-Item -ItemType Directory -Force -Path $pilotBackupPath | Out-Null
$pilotRunId = [guid]::NewGuid().ToString()
$pilotSnapshot = Join-Path $pilotBackupPath ("snapshot-" + $pilotRunId + ".sqlite")
$pilotRestore = Join-Path $pilotBackupPath ("restore-" + $pilotRunId + ".sqlite")
$pilotResult = .venv/Scripts/python.exe -m app.operations.pilot backup $env:KUDILEDGER_DB $pilotSnapshot | ConvertFrom-Json
.venv/Scripts/python.exe -m app.operations.pilot verify $pilotSnapshot
.venv/Scripts/python.exe -m app.operations.pilot restore $pilotSnapshot $pilotRestore --sha256 $pilotResult.sha256
```

Open the restored copy in an isolated local process using a separate database path and port. Sign in again. Compare known customer balances and references and recheck one unresolved attempt and one committed attempt. Inspect an operator audit entry. Reconcile any operator grants, credential changes and financial activity that occurred after the snapshot before considering a cutover. Restore to a new file first and retain the original database and logs for review.

The automated end-to-end drill runs `.venv/Scripts/python.exe -m unittest -v tests.test_pilot_database`. It verifies NGN 114.99 of restored debt, four known references, both recovery outcomes, an audit entry and invalidation of restored sessions. It also tests online snapshot consistency and checksum or integrity failures.

## Pilot controls and gaps

| Area | Implemented | Open before an external pilot |
| --- | --- | --- |
| Account and session security | Salted scrypt, hashed expiring bearer sessions, local login throttling, membership checks and explicit operator grants. Dashboard tokens remain in memory. | Account verification and password recovery, MFA for administrators, invitation and role lifecycle, and coordinated rate limits at the edge. Provision only authorized synthetic users for the local drill. |
| Transport and frontend | Opt-in HTTPS scheme enforcement and HSTS, no-store for app and API responses, frame denial, and a CSP allowing only the dashboard's hashed inline script and CSS and same-origin API calls. | Provision and test actual TLS, certificate renewal, proxy scheme handling and secure configuration. The application check depends on the scheme supplied by a trusted server or proxy. |
| Database and backup | Atomic financial writes, immutable financial and operator audit records, checksum-verified SQLite backups and restore into new files. | Set host file ACLs and encrypted backup storage, agree retention and recovery objectives, schedule backups, and repeat restore drills on the target host. Test SQLite contention and the deployment filesystem. |
| Logging and monitoring | The operator journal records decisions separately from financial records. A shallow health endpoint is available. | Set up service and storage monitoring, alerting for repeated failures and stuck claims, sanitized operational logs and log retention. Keep Authorization headers and payloads out of logs. Prefer disabling Uvicorn access logs until query-string and customer data handling are reviewed. |
| Incident handling | Manual recovery and restore procedures can be exercised locally. | Assign operators and escalation contacts, and rehearse outage, credential compromise, rollback and recovery decisions before deployment. |

For proxy-based HTTPS, keep the backend listening on loopback, configure trusted forwarded headers only for the actual proxy IP, and set `KUDILEDGER_REQUIRE_HTTPS=1` for the application. Reject cleartext and spoofed forwarding headers at the edge. Check that HTTPS works and direct HTTP requests are rejected in the actual environment. The default `0` supports local synthetic development. Application tests do not substitute for a real TLS or proxy test.

During an incident, pause new entries if the integrity of records is in doubt, record references and Nigeria time, preserve the database and restricted logs, and use the audit procedure. Verify backups before restoration. Revoke affected sessions or operator grants and obtain independent approval before resuming writes.
