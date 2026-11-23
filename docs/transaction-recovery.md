# KLD-006B4 recovery threat model

## Current lifecycle and decision

The dashboard generates or accepts a reference, confirms the financial record, then keeps the payload in a form-local map while it posts the write. A refresh discards the map and its submission guard. The ledger still rejects a repeated reference within a business and transaction type, but recording the same activity with a new reference could create another entry.

| Option | Tradeoff |
| --- | --- |
| In-memory state | Keeps payloads out of browser storage and loses them on refresh. |
| Browser storage (sessionStorage, localStorage, IndexedDB) | Survives some interruptions. Data is accessible to scripts on the origin and can remain on a shared device across sign-ins. A reference alone cannot establish a match. Persisting the payload or a low-entropy fingerprint introduces disclosure risk. |
| Authenticated server journal | Keeps the original payload behind business membership and account checks and works across browsers. Preparation requires connectivity and adds a request and sensitive server-side state to protect. |

Use an authenticated SQLite journal. Write the confirmed intent before issuing the financial POST. The dashboard keeps tokens and recovery data in page memory only. Journal API responses omit the original payload and use no-store. Every operation checks the signed-in user and business membership. On sign-out or expiry the page clears its recovery display.

The financial POST claims a prepared intent once and calls the existing ledger write with the stored payload. Preparing and submitting are separate so losing a preparation response cannot cause a financial record. In KLD-006B5 the claim, write and result use an immediate transaction on the same connection. A pre-commit process interruption rolls back to an unsent intent. An unsent intent can be cancelled with an atomic check. The dashboard never resends a financial POST after a lost response.

A fresh authorized check reads the applicable committed record by business, kind and reference and compares the saved fields against the original payload using exact kobo. A matching record unlocks receipt access. A different record is a conflict. Absence alone leaves a claimed attempt unresolved. A ledger validation rejection is recorded separately from a network error. A partial unique index blocks new dashboard submissions in that scope while an earlier record remains unsettled.

The journal adds a table and indexes to the existing SQLite database on app startup. Ledger tables and recorded transactions keep their existing format. An acknowledged save releases the block and keeps a recent journal entry, so a tab closing immediately after a successful response still leaves the last reference available. Acknowledgement requires the ID of the matching committed transaction. It caps verified history at the newest 10 records per account and business. A fresh check still supplies the receipt ID. The owner can remove verified or rejected journal entries. Unresolved and conflicting entries never expire automatically.

## Outcomes and concurrent access

| State | Meaning and safe action |
| --- | --- |
| Ready but unsent | The server stored the confirmation and this intent has no committed write. A process interruption before atomic commit also leaves this state. Cancel the entry if you want to start again. Cancellation checks the current state inside a transaction. |
| Still uncertain | The response was lost before acknowledgement, or an older version persisted a standalone claim. Check the ledger. A missing row alone leaves a legacy claim intact. |
| Reference already used | The same type and reference identify a different committed record. The new entry remains blocked for review. |
| Verified as saved | An authorized lookup matched the original fields and exact kobo values. Open the receipt or remove the check from the journal. |
| Rejected | The ledger established a validation or pre-write authorization rejection. Review the entries and explicitly confirm any correction. |
| Unauthorized or offline | A failed check supplies no financial result. Reconnect or sign in again, then check with the original account. |

The SQLite partial unique index admits one blocking attempt per kind, account and business, including across tabs. A transaction claims an attempt once before it calls the existing write service. Concurrent checks cannot trigger a financial write. Standard API clients can still call the existing financial endpoints, which retain business and type reference uniqueness. The recovery guard applies to the new dashboard write path. Different references can represent indistinguishable real-world activity, so an independent account or old client still needs to coordinate before entering a replacement.

## Access, retention and operating limits

- The browser keeps only an in-memory bearer token. The journal stores the confirmed fields required for matching on the server, including customer IDs and expense descriptions. Keep the SQLite file and backups access-controlled, and avoid personal information in free-text references. HTTP access logs and operation logs should be reviewed before pilot deployment.
- Browser storage isolation covers shared-device sign-in changes. An active script compromise or compromised server can still act with the current user's access. Pilot controls should include HTTPS, script restrictions, database access controls and restricted diagnostic logs.
- Receipt lookup remains business-authorized. Recovery additionally scopes the journal to the creating account, including when two accounts belong to the same business. An unrelated account cannot retrieve the journal or use an attempt ID to take action.
- A standalone claim left by KLD-006B4 may still be unresolved. A missing ledger row alone cannot prove the original process stopped before writing. A granted operator can record an evidence-backed decision without changing financial records. Follow the [operator workflow](pilot-operations.md#audited-investigation).
- The workflow needs a connection to prepare a new write or verify an earlier one. It provides no offline queue. Recovery covers submissions made by the new dashboard path and cannot reconstruct earlier browser-only attempts.

The [architecture decision](pilot-architecture.md) explains the atomic boundary. The [restore drill](pilot-operations.md#backup-and-restore-drill) backs up the journal and ledger from the same SQLite snapshot.
