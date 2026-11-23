# KLD-006B5 architecture decision

## Atomic recovery submission

The existing recovery path commits a claim, calls a ledger method that owns a second transaction, and then records the outcome in a third. An interruption can leave a durable claim with no sale or leave a committed sale whose journal has not been updated. The lookup still protects against a blind retry, but a claim can require investigation.

| Option | Consequence |
| --- | --- |
| Reconcile an independently committed claim | Keeps the existing transaction boundaries. Absence of a ledger row cannot distinguish a crashed worker from a delayed one. |
| Add a separate implementation of the ledger writes | Allows one transaction but duplicates amount, confirmation, tenant, reference and repayment balance rules. |
| Pass an explicit transaction connection through existing services | Reuses the validated write methods. A caller that supplies a connection owns locking, commit and rollback. Existing direct API callers continue using methods that own their transaction. |

Use the explicit connection for dashboard recovery. An immediate SQLite transaction serializes authorization, claim, financial write and journal outcome. A savepoint isolates the financial write when a known validation error occurs. The outer transaction rolls back an unexpected exception. Success returns only after commit. A response lost after commit still requires a fresh authorized lookup. A pre-commit interruption rolls back to an unsent intent. The browser may cancel the intent and confirm a new one. The browser never resends a financial POST on a missing lookup.

Legacy attempts claimed before this change may still be uncertain. Do not bulk edit them. The restricted operator workflow records the decision and evidence in an immutable audit table. Release requires explicit confirmation and applicable evidence. A lookup miss can justify retaining an attempt and cannot by itself justify release.

The immediate writer lock is held for a larger part of the request. For a small SQLite pilot, the tradeoff is predictable serialization. Monitor lock contention and keep external calls outside the transaction. Standard business reference constraints and ledger immutability remain in place.
