# KudiLedger AI

KudiLedger is a local financial ledger for Nigerian small businesses. The dashboard lets an owner sign in, add customers, record sales and debt repayments, record expenses, and view a daily overview and customer balances. The API also supports customer statements, debt adjustments and eligible unpaid sale reversals.

## Run locally on Windows

Run these commands in PowerShell from the repository directory. The project is verified with Python 3.13. Use Node.js on PATH for the dashboard syntax tests and a Chromium browser for the interaction test.
Install the updated requirements when upgrading an existing checkout. The pinned `tzdata` package supplies IANA timezone data on Windows.

```powershell
py -3.13 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
$env:KUDILEDGER_DB = Join-Path $env:TEMP ("kudiledger-demo-" + [guid]::NewGuid() + ".db")
.venv/Scripts/python.exe -c "import os; from getpass import getpass; from app.services.reports import ReportLedger; ReportLedger(os.environ['KUDILEDGER_DB']).register_owner('Demo Shop', 'owner@example.test', getpass('Choose a demo password (at least 12 characters): '))"
.venv/Scripts/python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/app` and sign in with the synthetic account created above. API documentation is at `/docs` and the health check is at `/health`. A password needs 12 to 1024 characters. Owner registration is available through the Python service for local provisioning. The dashboard supports accounts linked to one business.

| Environment variable | Purpose |
| --- | --- |
| `KUDILEDGER_DB` | SQLite path for the API. Defaults to `kudiledger_api.db` relative to the working directory. Use a separate database for demos and testing. |
| `KUDILEDGER_REQUIRE_HTTPS` | Defaults to `0` for local synthetic use. Set `1` to require HTTPS and send HSTS on secure requests. Review trusted proxy configuration first. |
| `KUDILEDGER_BROWSER` | Optional path to Chromium, Chrome, or Edge for the browser test. The test also checks PATH and standard Windows installation locations. |

## Demo workflow

1. Sign in, then add a synthetic customer named Musa.
2. Record a sale for Musa with reference `DEMO-SALE-1`, total NGN 2,500.01 and NGN 1,000 already paid. Accept the confirmation.
3. Record a repayment of NGN 500 with reference `DEMO-REPAY-1` and an expense of NGN 200 with reference `DEMO-EXP-1`. The dashboard should show NGN 1,500 in recorded receipts and NGN 1,000.01 in outstanding debt.
4. Submit the identical sale again with the same reference. The dashboard should verify the original entry and leave the totals unchanged. For the simulated lost-response flow, run the browser test below. It drops a response after capturing the write, returns unresolved and conflicting results, and finally returns the matching record.
5. Log out. To review the mobile layout manually, set the device width to 360 px in browser developer tools and repeat the workflow.

## Mobile trader dashboard

The six sections are **Overview**, **Customers**, **Sales**, **Repayments**, **Expenses**, and **Receipts**. Overview opens after sign-in and gives direct access to recording a sale, repayment, or expense. The same forms and ledger rules apply on phones, tablets, and desktops.

Use **Customers** to add someone or search by name. In a sale or repayment, type part of the customer’s name and then choose the customer from the filtered list. Search covers the full business directory, while each list displays at most 50 matches. The form never picks a customer on its own.

Enter naira amounts with up to two decimal places. You can leave the reference blank to have KudiLedger assign one. Confirm the transaction before saving. A dot on the section button and its accessible name indicate a record that needs checking. Open that section and select **Check saved transaction** before trying again.

Mobile and desktop images use synthetic records from the running app. [Mobile overview](docs/review/KLD-006B3/mobile-overview.png) · [Mobile sale](docs/review/KLD-006B3/mobile-sale.png) · [Mobile receipt](docs/review/KLD-006B3/mobile-receipt.png) · [Desktop overview](docs/review/KLD-006B3/desktop-overview.png)

## Nigerian business-day reporting

The dashboard starts on today's date in Nigeria. After recording the demo transactions, select the previous reporting date and choose **Refresh records**. On a fresh demo database, daily sales, receipts and expenses for that earlier date are zero. Current customer debts still show the balance across all dates.

`GET /api/v1/businesses/{business_id}/reports/daily?report_date=YYYY-MM-DD` interprets `report_date` as an Africa/Lagos calendar date. The response retains `date` and the existing totals, sets `timezone` to `Africa/Lagos`, and adds `period_start_utc` (inclusive) and `period_end_utc` (exclusive). Sales, repayments, expenses and reversals use the same interval. Each reversal is reported separately on the date it was recorded. For example, February 29, 2024 starts at 23:00 UTC on February 28 and ends at 23:00 UTC on February 29.

API clients upgrading from UTC reporting should update their date selection and read the returned timezone. Stored UTC audit timestamps and their SQLite format need no migration or backfill. To replay month-end, year-end and leap-day transitions on synthetic data, run `.venv/Scripts/python.exe -m unittest -v tests.test_reports tests.test_api_reports`.

## View and print receipts

1. Record and confirm a synthetic sale, repayment, or expense. Select **View Receipt** on that form. To reopen an older receipt, use **Find a receipt** and enter the original type and reference.
2. Check the business, amount, Nigeria timestamp and relevant customer or expense details. A sale shows its paid and due amounts as recorded at sale, plus a reversal notice when applicable. Receipts document entries in KudiLedger and carry no external payment verification.
3. Choose **A4** or **Narrow roll**, then select **Print Receipt**. Choose the matching paper size in your browser or printer dialog. The app rechecks access and refreshes the receipt before opening the print dialog. Use this button to include receipt details in the printout.

With an active bearer session, call `GET /api/v1/businesses/{business_id}/receipts?kind=sale&transaction_id=...` or use `reference=...` instead of `transaction_id`. The supported kinds are `sale`, `repayment`, and `expense`. A reference is scoped to its business and kind. Successful responses are marked `Cache-Control: no-store` and return exact two-decimal naira strings, `recorded_at_utc`, `recorded_at_local`, and the `Africa/Lagos` timezone.

The API requires authorization for the requested business. Receipts use the business name and applicable customer name stored in the ledger directory at retrieval time. Those names can differ from the names in use on the transaction date. The browser controls print margins and paper settings. Verify sizing on the intended physical printer before using printed receipts in a pilot.

## Architecture and financial rules

- FastAPI serves the vanilla HTML, CSS and JavaScript dashboard and the versioned API. The SQLite ledger and services hold the authoritative financial records.
- The API converts naira amounts to integer kobo, requires explicit confirmation and checks ownership on business operations. Sale, repayment and expense references are unique per business and transaction type. Confirmed financial records are protected by database triggers. Adjustments and reversals record supported corrections separately.
- Financial saves from the dashboard use a server-side recovery journal before issuing the write. The claim, financial write and outcome commit atomically. The original fields stay on the server and amounts are compared in exact kobo.

## Recover an interrupted save

1. Reconnect and sign in with the account that recorded the transaction. Open **Recovery**. The list survives refresh and sign-out.
2. Find the reference and select **Check saved transaction**. **Verified as saved** offers the receipt. **Ready but unsent** means this workflow never started the save. You can cancel the unsent record and then record it again. A **Rejected** result lets you review and confirm a correction.
3. If the record is **Still uncertain** or a different record uses the reference, keep the reference and leave the record in Recovery. A missing result can change after the connection returns. Avoid recording the same activity under a new reference.
4. If repeated checks stay uncertain or show a conflict, contact the business operator or support through your usual channel. Give them the business, transaction type, reference, and approximate Nigeria time. A granted operator can investigate and record an auditable decision. Keep the entry blocked if they cannot establish the outcome. External payment verification happens with the payment provider. Keep passwords and tokens private.

Recently checked records retain the last few references after a successful save and can be checked again to reopen receipts. See the [recovery threat model](docs/transaction-recovery.md) for authorization, storage, retention, and concurrency details.

### Reproduce the lost-response demo

Run the following with Chrome or Edge and Node.js 24. It launches a local Uvicorn server with synthetic data, interrupts the already committed response in Chrome, checks the offline state, reloads the page, signs in again, and opens the saved receipt. It asserts that exactly one sale was committed.

```powershell
.venv/Scripts/python.exe -m unittest -v tests.test_browser_persistent_recovery
```

[After refresh and sign-in](docs/review/KLD-006B4/unresolved-after-sign-in.png) · [Verified sale with receipt action](docs/review/KLD-006B4/verified-with-receipt.png)

## Tests

```powershell
.venv/Scripts/python.exe -m unittest discover -v
.venv/Scripts/python.exe -m unittest -v tests.test_dashboard_javascript tests.test_dashboard_recovery
.venv/Scripts/python.exe -m unittest -v tests.test_api_recovery tests.test_browser_persistent_recovery
git diff --check
```

The tests create synthetic records in temporary SQLite databases. Node checks the embedded JavaScript syntax. The interaction test runs the dashboard at 320, 360, 390, 430 and 768 px in headless Chromium with controlled API responses. It checks overflow, touch-target heights, focus, accessible labels, customer search, confirmed saves, receipt printing and recovery. The Python API tests exercise SQLite and backend authorization separately. In restricted Windows runners the tests require access to create and clean up temporary directories and launch the browser.

## Development limits

Use the local server with synthetic data. Before an external pilot, validate deployed TLS, approved email delivery, alert routing and restore on the target host. A PostgreSQL migration remains future work. See [PROJECT_STATUS.md](PROJECT_STATUS.md) for the audit and review gate. Run `python engine.py` for the standalone rule-based parsing demo.

## Synthetic pilot safety

KLD-006B5 adds atomic recovery, restricted operator decisions, and local backup and restore commands. The new operator tables initialize on startup. Stop any workers running the older version before upgrading the database.

```powershell
.venv/Scripts/python.exe -m unittest -v tests.test_atomic_recovery tests.test_recovery_operator tests.test_pilot_database tests.test_pilot_security
```

See the [architecture decision](docs/pilot-architecture.md) for the transaction design and the [pilot operations guide](docs/pilot-operations.md) for operator provisioning, the backup drill, HTTPS configuration, and the remaining readiness gaps.

## Supervised staging and account lifecycle

The default local setup uses existing trusted test registration. The supervised pilot uses the staging host invitation command and locally captured `.test` email. An invitation verifies inbox access before creating the account. Password reset is available from **Forgot password?** and signs out existing sessions when a reset completes.

Use [staging architecture](docs/staging-architecture.md) for hosting costs, the Linux service configuration and approved TLS setup. See [supervised pilot acceptance and operations](docs/supervised-pilot.md) for synthetic email configuration, test commands, retention, monitoring, manual Android checks and the go/no-go checklist. Keep any real provider deployment and email delivery behind the review gate.

## Release candidate review

See the [release candidate notes](docs/release-candidate.md) for the version manifest, CI gate, rollback procedure, recovery targets and readiness matrix. The [product-owner demo](docs/release-demo.md) includes a repeatable synthetic journey, mobile and desktop screenshots, and a receipt print render.
