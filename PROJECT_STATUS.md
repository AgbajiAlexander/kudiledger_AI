# KudiLedger AI project status

## Current checkpoint

- `main` at `9142d46` contains KLD-001 through KLD-006A4B. The FastAPI application, SQLite ledger, trader dashboard and authenticated transaction lookup are already implemented. The 173-test baseline passed after allowing the test runner to access Windows temporary directories.
- KLD-006B0 stabilization is on `feature/KLD-006B0-stabilization` for owner and technical review. Keep the review gate before merging or starting KLD-006B1.

## KLD-006B0 audit

| Area | Finding and disposition |
| --- | --- |
| Transaction recovery | Invalid amount conversions could match each other. Recovery now compares validated exact kobo amounts, requires a well-formed lookup response and keeps the original payload bound to its business. Known 400 and 422 rejections permit correction after the matching lookup reports absence. A POST rejected with 401 or 403 clears that attempt. A lookup failure, missing record after response loss, or conflicting reference retains the pending state. The browser uses GET for verification and locks edits and duplicate submissions while pending. It clears visible data on sign-out or expiry and prompts before leaving a page with pending work. |
| Ledger and reporting | Reviewed authorization, business-scoped uniqueness and immutable records. SQLite serializes repayment, adjustment and reversal balance checks with `BEGIN IMMEDIATE`. A concurrent repayment test covers overpayment and an exact duplicate of the successful write. Duplicate sale, repayment and expense references have distinct domain messages and retain HTTP 400 compatibility. Unexpected constraint errors take the server-error path. The daily report now reads all figures in one SQLite snapshot. Out-of-range amounts are rejected before conversion. |
| Dashboard reliability | The Chrome test uses real DOM controls at 360 px, with controlled API responses for login, logout, customer selection, confirmation, saves and transaction recovery. Separate API tests verify committed records, tenant isolation, balance calculations and report figures. Dashboard amounts are formatted from integer kobo so the confirmation text preserves the selected amount. |
| Account and browser security | Passwords use salted scrypt. Random bearer tokens are stored hashed server-side, expire after 12 hours and are revoked on successful logout. The page keeps credentials and tokens out of persistent browser storage. HTTP 422 responses omit the rejected input values. Per-email SQLite login throttling limits repeated failures. Explicit authorization headers reduce classic cookie-based CSRF exposure. Dynamic customer and transaction text renders through text APIs. Production still needs HTTPS, security headers and a broader security review. |
| Operations | Local SQLite uses foreign keys and transactions. Keep the database and backups out of Git, restrict filesystem access and use synthetic test data. For a pilot, use the SQLite backup API for consistent copies, protect and retain them separately, and verify restoration into an isolated environment. Backup scheduling, restore drills, structured audit logging, monitoring and alerting remain unimplemented. |

## Remaining development limits

- In-memory recovery cannot guarantee duplicate prevention across reloads, closed tabs or separate devices when a merchant enters a new reference. The unique database constraint protects a repeated reference within its business and type. Browser navigation prompts are best effort. Persistent recovery and an operator workflow belong to KLD-006B4.
- The browser test uses mocked API responses. Physical Android devices and combined live-server/browser response interruption remain unverified. Authentication, financial persistence and lost-response API semantics have separate integration coverage.
- SQLite write contention under sustained load, cumulative integer aggregate limits and extreme-volume reporting have not been load-tested. Process logs, reverse-proxy configuration, rate limits across identities, recovery workflows and secure session handling need review before pilot deployment.
- Registration is local service provisioning. Account verification, password recovery, receipt printing, production deployment, PostgreSQL migration, WhatsApp integration and AI-assisted entry remain future work.

## Next milestone after review

KLD-006B1 adds Africa/Lagos reporting dates and midnight-boundary tests while preserving UTC audit timestamps. See [README.md](README.md) for startup, configuration, demo and verification commands.
