# KudiLedger AI

KudiLedger is a local financial ledger for Nigerian small businesses. The dashboard lets an owner sign in, add customers, record sales and debt repayments, record expenses, and view a daily overview and customer balances. The API also supports customer statements, debt adjustments and eligible unpaid sale reversals.

## Run locally on Windows

Run these commands in PowerShell from the repository directory. The project is verified with Python 3.13. Use Node.js on PATH for the dashboard syntax tests and a Chromium browser for the interaction test.

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
| `KUDILEDGER_BROWSER` | Optional path to Chromium, Chrome, or Edge for the browser test. The test also checks PATH and standard Windows installation locations. |

## Demo workflow

1. Sign in, then add a synthetic customer named Musa.
2. Record a sale for Musa with reference `DEMO-SALE-1`, total NGN 2,500.01 and NGN 1,000 already paid. Accept the confirmation.
3. Record a repayment of NGN 500 with reference `DEMO-REPAY-1` and an expense of NGN 200 with reference `DEMO-EXP-1`. The dashboard should show NGN 1,500 in recorded receipts and NGN 1,000.01 in outstanding debt.
4. Submit the identical sale again with the same reference. The dashboard should verify the original entry and leave the totals unchanged. For the simulated lost-response flow, run the browser test below. It drops a response after capturing the write, returns unresolved and conflicting results, and finally returns the matching record.
5. Log out. To review the mobile layout manually, set the device width to 360 px in browser developer tools and repeat the workflow.

## Architecture and financial rules

- FastAPI serves the vanilla HTML, CSS and JavaScript dashboard and the versioned API. The SQLite ledger and services hold the authoritative financial records.
- The API converts naira amounts to integer kobo, requires explicit confirmation and checks ownership on business operations. Sale, repayment and expense references are unique per business and transaction type. Confirmed financial records are protected by database triggers. Adjustments and reversals record supported corrections separately.
- Daily figures use UTC. Outstanding debt is the current balance, independent of the selected reporting date.
- Recovery uses the original payload and business, checks the reference with an authenticated GET and compares amounts exactly. A missing lookup after an interrupted write leaves the form blocked. Record the reference, sign in to the same business if needed, and check again. For unresolved or conflicting entries, preserve the reference and review committed records with the operator before posting a replacement.
- Recovery state lives in the open page. The dashboard requests a navigation warning while a financial submission is pending. Browser behavior varies, particularly on mobile. A refresh or tab close can lose the recovery state.

## Tests

```powershell
.venv/Scripts/python.exe -m unittest discover -v
.venv/Scripts/python.exe -m unittest -v tests.test_dashboard_javascript tests.test_dashboard_recovery
git diff --check
```

The tests create synthetic records in temporary SQLite databases. Node checks the embedded JavaScript syntax. The interaction test runs the actual dashboard at 360 px in headless Chromium with controlled API responses, while the Python API tests exercise SQLite and backend authorization. In restricted Windows runners the tests require access to create and clean up temporary directories and launch the browser.

## Development limits

Use the local server with synthetic data. The project still needs secure deployment configuration, account recovery and verification, operational monitoring, backup and restore drills, and a PostgreSQL migration plan. See [PROJECT_STATUS.md](PROJECT_STATUS.md) for the audit and review gate. Run `python engine.py` for the standalone rule-based parsing demo.
