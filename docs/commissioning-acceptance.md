# Supervised synthetic acceptance

Run from the repository root with installed requirements. The console starts an isolated loopback server with a short-lived SQLite database and a private captured mailbox. Start with a new browser profile and use synthetic details and passwords throughout.

```powershell
.venv/Scripts/python.exe -m scripts.commissioning_demo
```

On Linux, use `.venv/bin/python`. Open the activation link from the invitation JSON in the private capture directory printed by the console. Treat the links as credentials and keep the files out of screenshots, Git and screen sharing. Enter `Q` to shut down the demo and remove its temporary data. This interactive run uses loopback HTTP. The independent Caddy fixture below verifies local HTTPS.

| Workflow | Guide and expected result | Owner decision |
| --- | --- | --- |
| Activation and customer | Activate `commissioning@example.test` with a synthetic password, sign in and add a customer named Amina Demo. | ☐ Pass ☐ Reject |
| Credit sale and debt | Record reference `DEMO-SALE-1` for ₦100.01 with ₦20.01 paid. Verify the current customer debt is ₦80.00. | ☐ Pass ☐ Reject |
| Repayment | Record `DEMO-PAY-1` for ₦5.01. Verify the debt is ₦74.99. | ☐ Pass ☐ Reject |
| Expense | Record `DEMO-EXP-1` as a transport expense of ₦1.01. Verify the saved reference. | ☐ Pass ☐ Reject |
| Lagos reporting | In Overview on today's Lagos date, expect sales ₦100.01, money received ₦25.02 and expenses ₦1.01. Current debt is ₦74.99. Run the three actions within one Lagos day. | ☐ Pass ☐ Reject |
| Receipts and print | Retrieve the sale receipt. Confirm the amounts, customer, reference, Lagos timestamp and recorded-payment wording. Open A4 and Narrow roll print previews and inspect the receipt content. | ☐ Pass ☐ Reject |
| Lost acknowledgement | Enter `L` in the console. Record `DEMO-LOST-1` for ₦20.01, paid ₦0.00. The server commits and replaces the acknowledgement with a synthetic HTTP failure. Refresh, sign back in, check the original reference in Recovery and view its receipt. Verify one sale for the reference and debt of ₦95.00. | ☐ Pass ☐ Reject |
| Operator audit | Attempt a sale of ₦101.01 with ₦20.01 paid using the original `DEMO-SALE-1` reference. Verify conflict and the unchanged original receipt. In the console enter `O`, supply that reference and the synthetic password, and confirm with `RELEASE`. Check the audit identifier and verify debt stays at ₦95.00. | ☐ Pass ☐ Reject |
| Password reset | Keep an authenticated tab open, request **Forgot password?** in a separate browser session, use `M` to locate the captured reset JSON, and choose a new synthetic password. Verify the reset link is single-use and the previous session requires sign-in on its next authorized action. | ☐ Pass ☐ Reject |
| Backup and restore | Enter `B` and then `R`. Open the second loopback address and sign in again with the new password. Compare the four committed references, debt of ₦95.00 and the restored audit confirmation. | ☐ Pass ☐ Reject |

Record the reviewed commit, reviewer, Lagos date, evidence references, failures and decision. Repeat on desktop and mobile. The automated Caddy browser fixture can regenerate [mobile receipt](review/KLD-006C2/mobile-receipt.png), [desktop overview](review/KLD-006C2/desktop-overview.png) and [print render](review/KLD-006C2/receipt-preview.pdf) with `KUDILEDGER_REQUIRE_STAGING_BROWSER=1`, `KUDILEDGER_CADDY` set to the verified binary, and `KUDILEDGER_RC_SCREENSHOTS` set to an output directory, then `python -m unittest tests.test_tls_staging`. The live CDP browser recovery tests exercise an actual lost response independently. The owner decisions above are pending.

## Physical device protocol

Use supervised synthetic accounts on at least two physical Android phones, including one low-cost model. Record devices, RAM, Android/Chrome versions, screen widths, network/print equipment, test date, result and redacted evidence. Use an approved isolated device test environment. Public test hosting requires separate approval.

| Exercise | Verify on the physical device |
| --- | --- |
| Android Chrome and TalkBack | Complete the journey with touch and with TalkBack. Check labelled controls, form error announcements, readable amounts, focus after validation and receipt closure, absence of overflow, and reachable confirmation controls. |
| Slow link and disconnection | On a representative mobile network and a throttled link, disconnect before delivery, during save, and after a confirmed server commit but before receipt of the response. Return online, look up the original reference and prove a single financial effect for each committed transaction. Preserve uncertainty where outcomes cannot be established. |
| Background and interruption | Background Chrome during confirmation and while recovering. Reopen after session expiry, then repeat with a controlled safe device restart or low-power interruption. Sign back into the same account, check recovery, and compare behavior with a different synthetic account. Verify pending details remain appropriately scoped. |
| Physical printing | With the Android print service, print A4 and the target narrow roll size. Inspect clipping, legibility, naira glyphs, page count and references. Repeat after closing a receipt, failed lookup and expired session. Stale receipt details must remain unavailable. |
| Reconciliation | Compare starting and ending debt, reference counts, daily totals and receipts against the expected kobo values. Test the Lagos date transition with controlled synthetic timestamps. Record wrong balances, missing records, duplicates and any uncertainty a trader could mistake for a failed save. |

Physical checks remain open. In case of a wrong balance, duplicate financial effect, unauthorized disclosure or unsafe retry prompt, stop the exercise immediately, preserve synthetic references and evidence, and escalate to the pilot supervisor. Desktop/mobile emulation evidence covers the automated scenarios only.
