# KudiLedger AI project status

## Current checkpoint

- `main` at `9142d46` contains KLD-001 through KLD-006A4B. The FastAPI application, SQLite ledger, trader dashboard and authenticated transaction lookup are already implemented. The 173-test baseline passed after allowing the test runner to access Windows temporary directories.
- KLD-006B0 stabilization merged into `main` at `86ecd96`.
- KLD-006B1 Africa/Lagos reporting merged into `main` at `9547e35`.
- KLD-006B2 secure transaction receipts merged into `main` at `9eb219a`.
- KLD-006B3 mobile trader experience merged into `main` at `4fef013`.
- KLD-006B4 persistent transaction recovery merged into `main` at `4bda1f7`.
- KLD-006B5 pilot safety merged into `main` at `48860c1`.
- KLD-006C0 deployment readiness merged into `main` at `c1aa57c`.
- KLD-006C1 release candidate merged into `main` at `c3344c6`. The merged release gate passed.
- KLD-006C2 is prepared on `feature/KLD-006C2-pilot-commissioning` for independent review and owner acceptance. [Verification and manifest](docs/commissioning-manifest.md) · [Synthetic acceptance](docs/commissioning-acceptance.md) · [Pilot decision](docs/commissioning-plan.md)

## KLD-006C1 release validation

- CI runs the full synthetic suite, local TLS and browser checks, systemd verification and package and private-file checks. The exact commit must pass the `release-gate` job before release.
- Failed deliveries leave working links usable and raise a redacted alert. Expected financial rejections stay outside the operational failure counter. Isolated restoration preserves account and operator audit records while clearing old sessions and outstanding links.
- The [candidate notes](docs/release-candidate.md) and [synthetic demo](docs/release-demo.md) record the dependency set, rollback, recovery targets, review evidence and open approval gates.
- Local verification on 23 November 2026 passed 219 tests in 141.049 seconds with zero failures, errors or skips. The release dependency scan reported no known package vulnerabilities. Caddy, Ubuntu systemd verification, JavaScript syntax and Python dependency consistency checks also passed.

## KLD-006C0 supervised staging

- Linux systemd and Caddy configuration supports a single unprivileged API worker with local SQLite and approved TLS. Loopback Caddy validation uses a trusted temporary CA and real Chrome at mobile and desktop widths. Public DNS, certificates and deployed systemd units remain unverified.
- Supervisor-issued invitations verify inbox access. Expiring, one-time reset links enforce session revocation and uniform reset responses. Synthetic capture requires test addresses. Real SMTP delivery remains behind separate approval.
- Privacy-safe structured logs omit raw request and exception data. Local health and recovery thresholds, a scheduled snapshot timer and the isolated restore scenario support rehearsal.
- Verification on 23 November 2026 passed 215 tests in 123.707 seconds with zero failures, errors or skips. Seven focused account, telemetry and acceptance tests passed in 5.622 seconds. Caddy 2.11.9 and Chrome completed the trusted loopback staging test at 390 px and 1440 px. JavaScript syntax, dependency and whitespace checks passed.
- See the [staging architecture and costs](docs/staging-architecture.md) and the [supervised pilot checklist](docs/supervised-pilot.md#go-no-go). Live alert routing, off-host backup scheduling, and Android, TalkBack and printer checks remain open.

## KLD-006B5 synthetic pilot safety

- Recovery uses one immediate SQLite transaction for the claim, existing ledger service and journal outcome. The subprocess tests verify rollback before the write, after insertion and before commit, plus durability and duplicate protection after commit.
- Separately granted operators may inspect blocked attempts and record evidence-backed decisions. The immutable audit survives journal cleanup. Operators have no recovery endpoint for changing financial records.
- The local backup tool creates and validates a consistent snapshot, checks the checksum during restore, revokes restored sessions and publishes a new file. The drill verifies balances, references, unresolved and committed recovery, and audit history.
- The app supports opt-in HTTPS enforcement, HSTS, dashboard CSP, frame denial and no-store headers. See the [pilot operations guide](docs/pilot-operations.md) for the remaining deployment, account, storage and monitoring gaps.
- Verification on 23 November 2026 passed all 207 tests in 90.740 seconds with zero failures, errors or skips. The 25 focused crash, recovery, operator, backup, transport and live browser tests passed in 14.649 seconds. JavaScript syntax, dependency consistency and Git whitespace checks passed.

## KLD-006B4 persistent recovery

- The server saves the confirmed original payload against the business, account, type and reference before the dashboard sends the financial write. The journal survives refresh and sign-out. The browser stores no credentials or journal contents persistently.
- A fresh authorized check matches committed ledger fields in exact kobo. Recovery distinguishes unsent, uncertain, conflicting, rejected and verified saves. Verified results offer receipts. A new write of the same type stays blocked for that account and business while its earlier result is uncertain.
- The live Chrome integration test drops the response after the local API commits a synthetic sale, tests an offline check, refreshes and signs in, then verifies the sale and opens its receipt. The database contains one sale.
- See the [threat model](docs/transaction-recovery.md) and the [recovery workflow](README.md#recover-an-interrupted-save) for privacy decisions and manual escalation.

## KLD-006B3 mobile dashboard

- Six task views with quick actions on Overview, 44 px minimum heights for navigation and form controls, keyboard focus on view headings, and labelled native search and selection controls. The customer search covers the full directory and shows up to 50 matches at a time.
- Existing Lagos reporting, exact kobo amounts, confirmation, business authorization, receipt printing and uncertain-write recovery use the same ledger and services. An optional reference can be assigned automatically. The relevant section identifies pending checks across navigation.
- Automated Chrome coverage runs at 320, 360, 390, 430 and 768 px. The live synthetic review includes 390 px and 1440 px screenshots, keyboard Tab and Enter activation, and the Chrome accessibility tree. Physical phones, assistive technology sessions and printer hardware still need pilot testing.

## KLD-006B2 receipts

- Authenticated, business-scoped read-only receipts are available by type and ID or reference. The API uses committed amounts, explicit UTC and Lagos timestamps, and a flag indicating that external payment verification has not been performed.
- The dashboard offers a receipt after a confirmed save or recovery and can reopen earlier receipts by type and reference. Printing rechecks access and isolates the receipt with A4 and narrow-roll layouts.
- Receipts read business and customer names from the directory at retrieval time. Those names can differ from the names in use on the transaction date.
- Tests cover authorization and expiry, missing and duplicate references, exact naira amounts, UTC-to-Lagos rollover, reversed sales, browser rendering and print invocation. Printer hardware and mobile print dialogs still need manual verification.

## KLD-006B1 reporting

- Daily sales, repayments, expenses and reversals use the interval between consecutive Africa/Lagos midnights, converted to UTC. The API returns the Lagos date and timezone plus explicit UTC bounds. Current outstanding debt remains the balance across all dates.
- Existing SQLite records retain their original UTC timestamps. No schema or data migration is required. Install the updated requirements for IANA timezone data on Windows.
- Regression cases cover 22:59:59, 23:00:00 and 23:00:01 UTC across month-end, year-end and leap-day transitions. The browser test checks the default at Lagos midnight and the customer-select styling.

## KLD-006B0 audit

| Area | Finding and disposition |
| --- | --- |
| Transaction recovery | KLD-006B0 added exact comparisons and in-page recovery controls. KLD-006B4 moved the pending state and match verification to the authenticated server journal. |
| Ledger and reporting | Reviewed authorization, business-scoped uniqueness and immutable records. SQLite serializes repayment, adjustment and reversal balance checks with `BEGIN IMMEDIATE`. A concurrent repayment test covers overpayment and an exact duplicate of the successful write. Duplicate sale, repayment and expense references have distinct domain messages and retain HTTP 400 compatibility. Unexpected constraint errors take the server-error path. The daily report now reads all figures in one SQLite snapshot. Out-of-range amounts are rejected before conversion. |
| Dashboard reliability | The Chrome test uses real DOM controls at 360 px, with controlled API responses for login, logout, customer selection, confirmation, saves and transaction recovery. Separate API tests verify committed records, tenant isolation, balance calculations and report figures. Dashboard amounts are formatted from integer kobo so the confirmation text preserves the selected amount. |
| Account and browser security | Passwords use salted scrypt. Random bearer tokens are stored hashed server-side, expire after 12 hours and are revoked on successful logout. The page keeps credentials and tokens out of persistent browser storage. HTTP 422 responses omit the rejected input values. Per-email SQLite login throttling limits repeated failures. Explicit authorization headers reduce classic cookie-based CSRF exposure. Dynamic customer and transaction text renders through text APIs. Production still needs HTTPS, security headers and a broader security review. |
| Operations | Local SQLite uses foreign keys and transactions. Keep the database and backups out of Git, restrict filesystem access and use synthetic test data. For a pilot, use the SQLite backup API for consistent copies, protect and retain them separately, and verify restoration into an isolated environment. Backup scheduling, restore drills, structured audit logging, monitoring and alerting remain unimplemented. |

## Remaining development limits

- The dashboard blocks new writes of the same kind while the original account and business have an unresolved attempt. Existing direct API clients and separate accounts still rely on scoped reference uniqueness and operator coordination. There is no offline write queue.
- The browser test uses mocked API responses. Physical Android devices and combined live-server/browser response interruption remain unverified. Authentication, financial persistence and lost-response API semantics have separate integration coverage.
- SQLite write contention under sustained load, cumulative integer aggregate limits and extreme-volume reporting have not been load-tested. Process logs, reverse-proxy configuration, rate limits across identities, recovery workflows and secure session handling need review before pilot deployment.
- Registration is local service provisioning. Account verification, password recovery, production deployment, PostgreSQL migration, WhatsApp integration and AI-assisted entry remain future work.

## Next milestone after review

Hold deployment for independent review. The next pilot checks are a real TLS and proxy smoke test, access-controlled backup scheduling and recovery drills on the target host, and alerting for long-unresolved records.
