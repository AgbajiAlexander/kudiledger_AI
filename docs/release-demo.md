# KLD-006C1 product-owner demo

Use the synthetic staging fixture and a local captured mailbox. Run from the repository root. No real recipients or public listeners are used by the fixture.

```powershell
$env:KUDILEDGER_CADDY = "C:\path\to\verified\caddy.exe"
$env:KUDILEDGER_REQUIRE_STAGING_BROWSER = "1"
.venv/Scripts/python.exe -m unittest -v tests.test_tls_staging tests.test_browser_persistent_recovery tests.test_supervised_pilot tests.test_pilot_database
```

## What to review

1. Open the captured invitation and set a password. Sign in and add a customer named **Synthetic TLS Customer**.
2. Record sale `RC-SALE-1` for **₦100.01** with **₦20.01** paid. Confirm **₦80.00** in customer debt. Record **₦5.01** as a repayment and **₦1.01** as a transport expense.
3. Open **Overview** for the Nigeria reporting date. Expect **₦100.01** total sales, **₦25.02** money received, **₦1.01** expenses and **₦74.99** current customer debt.
4. Open the sale receipt and choose **A4** or **Narrow roll**. The test verifies the print-only view and saves an A4 PDF render when evidence capture is enabled. Use a physical Android printer session to approve printer margins and page sizing.
5. The separate live recovery scenario drops the response after SQLite has committed a sale. Reopen the page, sign in, and check the saved reference. Verify the receipt while the database still contains one sale.
6. Request a reset through **Forgot password?**, open the captured link and choose a new password. The original bearer session receives HTTP 401 after completion.
7. Use the API acceptance and restore tests to review a reference conflict, the granted operator's recorded resolution, and the restored balance. The restored copy preserves both account and operator audit entries and clears old sessions and reset links.

## Captured views

[Mobile receipt at 390 px](review/KLD-006C1/mobile-receipt.png) · [Desktop overview at 1440 px](review/KLD-006C1/desktop-overview.png) · [Browser print render](review/KLD-006C1/receipt-preview.pdf)

The recovery path is also illustrated by the [uncertain record after sign-in](review/KLD-006B4/unresolved-after-sign-in.png) and the [verified record with receipt action](review/KLD-006B4/verified-with-receipt.png). The latest live check is included in the command above.

To regenerate the three new artifacts, set `KUDILEDGER_RC_SCREENSHOTS` to an empty directory you control and rerun `tests.test_tls_staging`. The fixture uses a temporary CA and SQLite file, and cleans up its local processes.
