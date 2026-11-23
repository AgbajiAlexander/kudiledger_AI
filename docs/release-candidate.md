# KLD-006C1 release candidate

## Identity and dependency manifest

The candidate is the reviewed commit on `feature/KLD-006C1-release-candidate`. Record its full SHA with `git rev-parse HEAD` and use that exact SHA for review, CI and any approved build. The candidate adds no application dependencies. The complete set of direct and transitive Python package versions is pinned in [requirements.txt](../requirements.txt). SHA-256 of the Git blob is `750ad9cec46b301aaf1335c7b9938e99e43167af7482c185c8487b950a3d83d9`.

| Runtime or tool | Version and scope |
| --- | --- |
| Python | Local Windows validation uses 3.13.12 with SQLite 3.50.4. The Linux CI candidate is pinned to the security release 3.13.18. Treat the local interpreter as a synthetic rehearsal runtime. |
| Node.js | Local browser driver uses 24.18.0. CI pins the security release 24.22.3. Node runs the browser tests only. |
| Caddy | Caddy 2.11.9 with the official archive checksum verified. Linux CI pins the archive and SHA-512 digest. |
| Browser | Runner Chrome for CI and local Chrome for Windows. Check the browser version again on each Android review device. |
| Audit | `pip-audit==2.10.1` runs against the application pins. The local scan reported no known package vulnerabilities. The test also runs `pip check`. |
| GitHub Actions | The workflow pins checkout, setup-python, setup-node and artifact upload to commit SHAs. |

Interpreter references include the [Python security release](https://www.python.org/downloads/release/python-31318/) and the [Node 24 security release](https://nodejs.org/en/blog/release/v24.22.3). The Python package advisory scan covers published advisories at execution time. Interpreter, OS, browser, account transport and host controls require separate review.

The application audit covered dashboard and CSP, credentials and sessions, ledger and recovery boundaries, operator audit, backup restore, mail and monitoring. The host configuration review covers Caddy, the API unit, monitor and backup services and timers, environment example and least-privilege layout. Ubuntu's `systemd-analyze` parses the checked-in units in a temporary root and verifies the Lagos calendar. This verifies unit syntax and schedule independently of starting the services.

## Release gate

[Release candidate checks](../.github/workflows/release-candidate.yml) runs on feature pushes, pull requests to main and candidate tags. It requires the full synthetic Python suite with Chrome and Caddy, systemd validation, JavaScript syntax, a pinned dependency audit, and a tracked private-file check. The final `release-gate` job fails if either prerequisite job fails or is skipped. Review the exact commit's run and its test-results artifact. [Branch workflow runs](https://github.com/AgbajiAlexander/kudiledger_AI/actions?query=branch%3Afeature%2FKLD-006C1-release-candidate)

Before releasing, require **release-gate** as a status check in the main branch ruleset and record owner approval for the exact green SHA. Verify the ruleset in GitHub. Release or deployment is a separate approved step. This workflow has no release, tag, deployment, email or infrastructure credentials.

The tracked-file guard rejects database files, key and certificate artifacts, private environment filenames and common high-confidence credential patterns. This is a targeted check of the tracked tree. Review Git history if an exposure is suspected. Application logs omit raw input, paths, headers and errors. Keep live secrets out of command history, CI inputs, captures and operational logs.

## Operational changes and rollback

- Expected financial rejections are labeled separately from technical failures. The failed-write threshold counts HTTP 5xx on write routes. A recovery rejection returned in a successful HTTP envelope is a business outcome and remains outside that counter.
- A failed mail attempt invalidates only its newly issued link and leaves earlier delivered links usable. A failed mail delivery creates a redacted audit event and an alert. The reset response stays generic. SMTP acknowledgement indicates accepted transport, and inbox delivery or bounce handling needs separate validation.
- On POSIX, private capture, credential and scheduled backup paths must deny group and other access. Windows ACLs, database ownership, host service options and off-host storage permissions need review on the selected host.
- An isolated restore preserves account security events and operator decisions while revoking old sessions and unconsumed account links. Restored operators should review grants and credentials created or revoked after the snapshot.

**Rollback procedure.** Record the last reviewed application commit, dependency manifest, configuration revision and backup digest before a change. If a release fails, pause writes and keep the current database and restricted logs. Restore the previous reviewed application and its matching virtual environment only after confirming it can read the current database in a rehearsal copy. Start it in an isolated environment and verify authentication, totals, references, receipts and recovery cases. If the current data cannot safely run with the previous application, restore a verified backup to a separate path. Reconcile entries, grants and credential changes after the snapshot and obtain explicit approval before pointing the service at that copy. Preserve the newer database for investigation. Resume writes only after the supervisor signs off.

**Pilot targets.** Target an RPO of **24 hours** for a host loss and an RTO of **2 hours** after incident declaration. These are acceptance limits, based on a daily off-host copy and an available recovery operator. An overdue copy or a missed restoration target is a no-go for resuming entries. The isolated automated restore passed locally. Off-host transport and elapsed recovery on the selected infrastructure still need measuring.

## Readiness matrix

| Area | Evidence | Status |
| --- | --- | --- |
| Full suite, security audit and required job | The exact SHA's GitHub Actions run is authoritative. | Check the linked CI run before release. |
| HTTPS, forwarding, security headers and CSP | Running Caddy with a trusted temporary CA, isolated Uvicorn and Chrome. | Verified in local integration tests. |
| Account lifecycle, redacted failure alerts and restore of account and recovery audit | Synthetic capture, API tests and SQLite restore. | Verified in local integration tests. |
| Mobile and desktop merchant workflow, receipt print rendering | Live Chrome on synthetic TLS, including a PDF render and post-reset session check. | Verified in local integration tests. Physical print dialogs remain open. |
| Deployment files, Lagos timer and review artifacts | Operator review of config and artifacts plus local Caddy and Ubuntu systemd verification. | Verified manually and with local tools. Services were not started under systemd. |
| Android Chrome, TalkBack, mobile-network interruption and actual printers | [Android checklist](supervised-pilot.md#manual-on-actual-android). | Not yet tested. |
| Public certificates and renewal, firewall and deployed units, SMTP, off-host backups and external monitoring | Target-host rehearsal with named owners and approval record. | Requires infrastructure approval. |

**Remaining priorities.** First, obtain a green `release-gate` for the exact SHA and enforce it in GitHub. Then approve the budget and host and prove public TLS renewal, SMTP delivery, external alerts and off-host restoration. Next, complete Android, TalkBack, network and printer checks with the supervisor. Keep real onboarding on hold until these checks pass. [Staging design and hosting costs](staging-architecture.md)
