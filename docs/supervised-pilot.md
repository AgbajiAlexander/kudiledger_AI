# Supervised pilot acceptance and operations

## Account lifecycle

The supervisor issues an invitation from the staging host using the restricted service account. Use synthetic `.test` recipients until real email has separate approval.

```powershell
.venv/Scripts/python.exe -m app.operations.staging invite --email owner@example.test --business "Synthetic Market"
```

Configure `KUDILEDGER_DB`, `KUDILEDGER_PUBLIC_ORIGIN`, `KUDILEDGER_MAIL_MODE=capture` and an existing private `KUDILEDGER_MAIL_CAPTURE_DIR` outside the checkout. The capture contains a one-time link. Open the link and set a password to verify ownership of the inbox and create the owner account. Invitations last 24 hours and reissue replaces previous invitations for that address. They are never shown in command output. Existing locally provisioned legacy accounts remain usable. Approve and verify the pilot roster independently before enabling external access.

**Forgot password?** returns the same message for existing and unknown accounts. Reset links last 30 minutes, are single-use, and revoke all existing sessions and other reset links when consumed. Only hashes of outstanding links are persisted in SQLite. The browser removes link tokens from the fragment on load and submits them in the request body. An incomplete visit can be restarted from the original email. Avoid posting links in chat or logs. Login retains the existing per-email failure limit and adds a source limit. Reset requests allow eight per source in 15 minutes and three deliveries per recipient in an hour. Link completion allows 12 attempts per source per 15 minutes. Shared carrier addresses may require operator review if legitimate requests reach these limits.

The database security audit records invitation issuance, email verification, reset link issuance and reset-triggered session revocation without passwords or tokens. Protect audit and capture directories. Delete synthetic capture files after the drill or once their links expire. SMTP error events contain a fixed category. Delivery runs in the application process, so a restart can interrupt it. Supervisors can reissue an invitation, and users can request a new reset once permitted by the rate limit.

## Monitoring and backups

| Check | Initial response | Owner |
| --- | --- | --- |
| HTTPS health unavailable | Check from another connection immediately and page after two failed two-minute probes. | Pilot operator |
| Three HTTP 5xx responses on financial write routes within 15 minutes | Pause the affected workflow after checking the journal and database health. | Technical operator |
| At least one unresolved or conflicting recovery older than 30 minutes | Investigate the reference with the restricted operator workflow. | Recovery operator |
| Nightly backup missing or invalid | Investigate before the next session and confirm the latest usable restore point. | Backup custodian |

The two-minute monitor timer runs the HTTPS probe and SQLite counts. It prints JSON and exits nonzero on threshold breach. Connect failed units or the log stream to an approved alert destination before the pilot. Configure an independent availability probe, because the on-host timer cannot report host loss. The app logs fixed route templates, method, status, elapsed time and a generated request ID. It excludes bodies, raw URLs, headers, account values and exception strings. Uvicorn access logging is disabled in the unit and Caddy omits request fields from its error logs. Provider and host logging still need review on the deployment target.

The backup timer runs at **02:00 Africa/Lagos**. It publishes a verified SQLite snapshot and checksum file. Copy both to an encrypted off-host location through the approved channel. Start with seven daily and four weekly copies, review retention with the pilot owner, and remove expired copies through the restricted backup process. Access belongs to the backup custodian and designated recovery administrator. Retain operational logs for an initial 14 days and extend only with a documented incident need. Restrict raw audit access and incident evidence to approved personnel.

Restore into a fresh isolated path. Restore revokes old sessions and outstanding account links. Compare balances, references, recent operator decisions and recovery states before cutover. A daily schedule implies up to 24 hours of exposure if there is no later backup. Confirm an acceptable recovery time in a target-host drill before accepting real entries. See [the restore and incident procedure](pilot-operations.md#backup-and-restore-drill).

## Repeatable synthetic acceptance

Set `KUDILEDGER_CADDY` to an installed or checksum-verified Caddy executable and `KUDILEDGER_REQUIRE_STAGING_BROWSER=1` to require Chrome, Node 24 and OpenSSL. Run:

```powershell
.venv/Scripts/python.exe -m unittest -v tests.test_account_lifecycle tests.test_operational_telemetry tests.test_supervised_pilot tests.test_tls_staging tests.test_browser_persistent_recovery tests.test_dashboard_recovery
```

The API scenario covers invitation, authentication, customer creation, sale, debt, repayment, expense, Lagos reporting, receipt, reauthentication, operator intervention, scheduled snapshot, isolated restore and tenant isolation. Chrome independently drops a real financial response after commit and verifies recovery after reload. The loopback staging test verifies certificate trust against a temporary CA, HTTP redirect, backend rejection of plain HTTP, HSTS and CSP, and that spoofed forwarding headers cannot bypass the reset limit. It exercises invitation and customer creation at 390 px and navigation at 1440 px. The automated mobile suite also covers 320, 360, 390, 430 and 768 px.

### Manual on actual Android

- Use Chrome on at least one low-memory phone and one newer phone. Check readability, scrolling, keyboard input on naira and customer fields, and navigation back to the active task.
- Use TalkBack to check headings, field names, error announcements, focus return, and the distinction between current debt and selected-day amounts.
- Open a synthetic invitation and reset from the phone's email flow. Verify reopening an expired link and resuming after the browser is backgrounded.
- Toggle airplane mode during a synthetic financial save, reopen the app, sign in again, and verify the reference and receipt without another write.
- Test actual A4 and narrow-roll print dialogs with the intended printer. Check clipping and naira glyphs.
- Try the pilot's primary and fallback mobile networks. Record page load and save times alongside device, browser and network.

## Go/no-go

- [x] Atomic recovery, operator audit and isolated synthetic restore passed locally.
- [x] Verified onboarding, reset, revocation, rate limits and privacy-safe request logging passed with synthetic capture.
- [x] Loopback real TLS, forwarding and browser checks passed on the reviewed Caddy configuration.
- [ ] Review and approve the exact commit, provider, recurring costs, data handling and pilot roster.
- [ ] Verify real DNS, public TLS renewal, firewall, proxy trust, OS permissions and systemd units on the approved host.
- [ ] Verify approved SMTP delivery, backup scheduling and off-host restoration. Exercise external alerts with named responders.
- [ ] Pass the actual Android, TalkBack, connectivity and printer checks. Obtain supervisor sign-off on escalation and a stop condition.

**No-go for real onboarding until the open checks are signed off.** During a suspected integrity or account incident, pause entries, preserve the restricted logs and database snapshot, revoke affected grants or sessions and follow the operator workflow. Resume only after reconciliation and approval.
