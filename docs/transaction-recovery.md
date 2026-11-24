# KLD-006B4 recovery threat model

## Current lifecycle and decision

The dashboard generates or accepts a reference and confirms the financial record. If connectivity fails before the server can acknowledge preparation, the dashboard keeps a minimal recovery reminder across refresh. Form fields remain in page memory and are lost at refresh. The ledger rejects a repeated reference within a business and transaction type, but a new reference may represent the same real-world activity.

| Option | Tradeoff |
| --- | --- |
| In-memory state | Keeps payloads out of browser storage and loses them on refresh. |
| Browser storage (sessionStorage, localStorage, IndexedDB) | Survives some interruptions. Data is accessible to scripts on the origin and can remain on a shared device across sign-ins. A reference alone cannot establish a match. Persisting the payload or a low-entropy fingerprint introduces disclosure risk. |
| Authenticated server journal | Keeps the original payload behind business membership and account checks and works across browsers. Preparation requires connectivity and adds a request and sensitive server-side state to protect. |

The authenticated SQLite journal records confirmed intent before the financial POST. After confirmation, the dashboard writes a browser-local reminder containing the reference and a random attempt ID. The storage key scopes it to the authenticated account, business and transaction kind. Only the authorized server journal holds the confirmed payload. Tokens stay in memory. Journal responses omit the original payload and use no-store. On sign-out or expiry the dashboard clears the visible recovery state.

The dashboard supplies the attempt ID when preparing the journal record. Once its matching server draft is acknowledged, the dashboard removes the reminder before it can send the financial request. A lost preparation response can leave both a reminder and a server draft. The dashboard prefers the exact authorized draft and lets the owner cancel it before recording again. If no draft exists, an explicit check and confirmation can clear the reminder. The browser serializes this check against preparation across same-origin tabs using Web Locks. Clearing never prepares or submits a transaction. Offline or unauthorized checks retain the reminder.

The financial POST claims a prepared intent once and calls the existing ledger write with the stored payload. Preparing and submitting are separate so losing a preparation response cannot cause a financial record. In KLD-006B5 the claim, write and result use an immediate transaction on the same connection. A pre-commit process interruption rolls back to an unsent intent. An unsent intent can be cancelled with an atomic check. The dashboard never resends a financial POST after a lost response.

A fresh authorized check reads the applicable committed record by business, kind and reference and compares the saved fields against the original payload using exact kobo. A matching record unlocks receipt access. A different record is a conflict. Absence alone leaves a claimed attempt unresolved. A ledger validation rejection is recorded separately from a network error. A partial unique index blocks new dashboard submissions in that scope while an earlier record remains unsettled.

The journal adds a table and indexes to the existing SQLite database on app startup. Ledger tables and recorded transactions keep their existing format. An acknowledged save releases the block and keeps a recent journal entry, so a tab closing immediately after a successful response still leaves the last reference available. Acknowledgement requires the ID of the matching committed transaction. It caps verified history at the newest 10 records per account and business. A fresh check still supplies the receipt ID. The owner can remove verified or rejected journal entries. Unresolved and conflicting entries never expire automatically.

## Outcomes and concurrent access

| State | Meaning and safe action |
| --- | --- |
| Save start not confirmed | The browser could not confirm that the server prepared the save. Reconnect, sign in with the same account, and use **Check with KudiLedger**. The browser can clear the reminder after a fresh authorized check and explicit confirmation. |
| Ready but unsent | The server stored the confirmation and this intent has no committed write. A process interruption before atomic commit also leaves this state. Cancel the entry if you want to start again. Cancellation checks the current state inside a transaction. |
| Still uncertain | The response was lost before acknowledgement, or an older version persisted a standalone claim. Check the ledger. A missing row alone leaves a legacy claim intact. |
| Reference already used | The same type and reference identify a different committed record. The new entry remains blocked for review. |
| Verified as saved | An authorized lookup matched the original fields and exact kobo values. Open the receipt or remove the check from the journal. |
| Rejected | The ledger established a validation or pre-write authorization rejection. Review the entries and explicitly confirm any correction. |
| Unauthorized or offline | A failed check supplies no financial result. Reconnect or sign in again, then check with the original account. |

The SQLite partial unique index admits one blocking attempt per kind, account and business, including across tabs. A transaction claims an attempt once before it calls the existing write service. Concurrent checks cannot trigger a financial write. Standard API clients can still call the existing financial endpoints, which retain business and type reference uniqueness. The recovery guard applies to the new dashboard write path. Different references can represent indistinguishable real-world activity, so an independent account or old client still needs to coordinate before entering a replacement.

## Access, retention and operating limits

- The browser keeps only an in-memory bearer token. The journal stores the confirmed fields required for matching on the server, including customer IDs and expense descriptions. Keep the SQLite file and backups access-controlled, and avoid personal information in free-text references. HTTP access logs and operation logs should be reviewed before pilot deployment.
- The dashboard shows reminders only after sign-in to the matching account and business. Anyone with access to browser developer tools or the browser profile may inspect local data, so avoid personal information in references and use a trusted device. A cleared site profile, a different origin (including a changed USB demo port), or a different device cannot recover a browser-only reminder. A browser without required local storage or Web Locks cannot start a financial save in the dashboard.
- Receipt lookup remains business-authorized. Recovery additionally scopes the journal to the creating account, including when two accounts belong to the same business. An unrelated account cannot retrieve the journal or use an attempt ID to take action.
- A standalone claim left by KLD-006B4 may still be unresolved. A missing ledger row alone cannot prove the original process stopped before writing. A granted operator can record an evidence-backed decision without changing financial records. Follow the [operator workflow](pilot-operations.md#audited-investigation).
- The workflow needs a connection to prepare a new write or verify an earlier one. It provides no offline queue. Recovery covers submissions made by the new dashboard path and cannot reconstruct earlier browser-only attempts.
- A delayed prepare can still arrive after a reminder was cleared. It can create an unsent server draft; the interrupted browser will never submit it. If a subsequent save is blocked by that draft, cancel it through Recovery.

The [architecture decision](pilot-architecture.md) explains the atomic boundary. The [restore drill](pilot-operations.md#backup-and-restore-drill) backs up the journal and ledger from the same SQLite snapshot.
