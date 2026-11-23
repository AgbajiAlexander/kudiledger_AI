import json
import sqlite3
from uuid import uuid4

from app.db.ledger import to_kobo
from app.services.reports import ReportLedger


class RecoveryNotFound(Exception):
    pass


class RecoveryConflict(Exception):
    pass


class RecoveryLedger(ReportLedger):
    def initialize(self):
        super().initialize()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS recovery_attempts (
                    id TEXT PRIMARY KEY,
                    business_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('sale', 'repayment', 'expense')),
                    reference TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    stage TEXT NOT NULL CHECK(stage IN (
                        'prepared', 'sending', 'saved', 'verified', 'rejected', 'conflict'
                    )),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (business_id) REFERENCES businesses(id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS recovery_one_open
                    ON recovery_attempts(business_id, user_id, kind)
                    WHERE stage IN ('prepared', 'sending', 'saved', 'conflict');
                CREATE INDEX IF NOT EXISTS recovery_owner
                    ON recovery_attempts(business_id, user_id, created_at);
            """)

    @staticmethod
    def _summary(row, stage=None, transaction_id=None):
        status = stage or row["stage"]
        if transaction_id:
            status = "committed"
        elif status in ("sending", "saved"):
            status = "unresolved"
        elif status == "verified":
            status = "recent"
        return {
            "id": row["id"],
            "kind": row["kind"],
            "reference": row["reference"],
            "created_at": row["created_at"],
            "status": status,
            "transaction_id": transaction_id,
        }

    @staticmethod
    def _get_attempt(db, attempt_id, business_id, user_id):
        row = db.execute(
            """SELECT * FROM recovery_attempts
               WHERE id = ? AND business_id = ? AND user_id = ?""",
            (attempt_id, business_id, user_id),
        ).fetchone()
        if row is None:
            raise RecoveryNotFound("Recovery record not found")
        return row

    def list_recovery(self, token, business_id):
        user_id = self._membership(token, business_id)["user_id"]
        with self.connect() as db:
            rows = db.execute(
                """SELECT id, kind, reference, stage, created_at
                   FROM recovery_attempts WHERE business_id = ? AND user_id = ?
                   ORDER BY created_at DESC, rowid DESC""",
                (business_id, user_id),
            ).fetchall()
        return [self._summary(row) for row in rows]

    def prepare_recovery(self, token, business_id, kind, payload):
        user_id = self._membership(token, business_id)["user_id"]
        reference = payload["reference"].strip()
        if not reference or payload["confirmed"] is not True:
            raise ValueError("A reference and confirmation are required")
        payload = {**payload, "reference": reference}
        attempt_id = str(uuid4())
        with self.connect() as db:
            try:
                db.execute(
                    """INSERT INTO recovery_attempts
                       (id, business_id, user_id, kind, reference, payload, stage)
                       VALUES (?, ?, ?, ?, ?, ?, 'prepared')""",
                    (attempt_id, business_id, user_id, kind, reference, json.dumps(payload)),
                )
            except sqlite3.IntegrityError as error:
                if error.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                    raise RecoveryConflict("Check your earlier record first") from None
                raise
            return self._summary(self._get_attempt(db, attempt_id, business_id, user_id))

    def submit_recovery(self, token, business_id, attempt_id):
        user_id = self._membership(token, business_id)["user_id"]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._get_attempt(db, attempt_id, business_id, user_id)
            if row["stage"] != "prepared":
                raise RecoveryConflict("This record can only be submitted once")
            db.execute("UPDATE recovery_attempts SET stage = 'sending' WHERE id = ?", (attempt_id,))

        payload = json.loads(row["payload"])
        reference = row["reference"]
        try:
            if row["kind"] == "sale":
                transaction_id = self.add_sale(
                    token, business_id, payload["customer_id"], reference,
                    payload["total"], payload["paid"], confirmed=payload["confirmed"],
                )
            elif row["kind"] == "repayment":
                transaction_id = self.add_repayment(
                    token, business_id, payload["customer_id"], reference,
                    payload["amount"], confirmed=payload["confirmed"],
                )
            else:
                transaction_id = self.record_expense(
                    token, business_id, reference, payload["category"], payload["description"],
                    payload["amount"], confirmed=payload["confirmed"],
                )
        except ValueError:
            # A duplicate reference can also raise ValueError. Inspect the ledger
            # before distinguishing a confirmed rejection from a conflict.
            return self._check_recovery(token, business_id, attempt_id, rejected=True)
        except PermissionError:
            # The existing ledger services check membership before any write.
            with self.connect() as db:
                db.execute(
                    """UPDATE recovery_attempts SET stage = 'rejected'
                       WHERE id = ? AND stage = 'sending'""",
                    (attempt_id,),
                )
            raise

        with self.connect() as db:
            db.execute(
                """UPDATE recovery_attempts SET stage = 'saved'
                   WHERE id = ? AND stage = 'sending'""",
                (attempt_id,),
            )
        return {"status": "saved", "transaction_id": transaction_id}

    @staticmethod
    def _matches(kind, payload, saved):
        try:
            if kind == "sale":
                return (
                    saved["customer_id"] == payload["customer_id"]
                    and saved["total_kobo"] == to_kobo(payload["total"])
                    and saved["paid_kobo"] == to_kobo(payload["paid"])
                )
            if saved["amount_kobo"] != to_kobo(payload["amount"]):
                return False
        except ValueError:
            return False
        if kind == "repayment":
            return saved["customer_id"] == payload["customer_id"]
        return (
            saved["category"] == payload["category"].strip()
            and saved["description"] == payload["description"].strip()
        )

    def check_recovery(self, token, business_id, attempt_id):
        return self._check_recovery(token, business_id, attempt_id)

    def _check_recovery(self, token, business_id, attempt_id, *, rejected=False):
        user_id = self._membership(token, business_id)["user_id"]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._get_attempt(db, attempt_id, business_id, user_id)
            stage = row["stage"]
            # A prepared attempt has never been claimed by this workflow. Keep
            # it cancellable even if its proposed reference already exists.
            if stage in ("prepared", "rejected"):
                return self._summary(row)
            saved = self._find_transaction(db, business_id, row["kind"], row["reference"])
            transaction_id = None
            if saved is not None:
                if self._matches(row["kind"], json.loads(row["payload"]), saved):
                    stage, transaction_id = "verified", saved["id"]
                else:
                    stage = "conflict"
            elif rejected or stage == "rejected":
                stage = "rejected"
            elif stage != "conflict":
                stage = "sending"
            db.execute("UPDATE recovery_attempts SET stage = ? WHERE id = ?", (stage, attempt_id))
            return self._summary(row, stage, transaction_id)

    def clear_recovery(self, token, business_id, attempt_id, *, cancel=False):
        user_id = self._membership(token, business_id)["user_id"]
        allowed = ("prepared",) if cancel else ("verified", "rejected")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._get_attempt(db, attempt_id, business_id, user_id)
            if row["stage"] not in allowed:
                raise RecoveryConflict("This record cannot be removed in its current state")
            db.execute("DELETE FROM recovery_attempts WHERE id = ?", (attempt_id,))

    def acknowledge_recovery(self, token, business_id, attempt_id, transaction_id):
        user_id = self._membership(token, business_id)["user_id"]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._get_attempt(db, attempt_id, business_id, user_id)
            if row["stage"] not in ("saved", "verified"):
                raise RecoveryConflict("Check the saved record before acknowledging it")
            saved = self._find_transaction(db, business_id, row["kind"], row["reference"])
            if (saved is None or saved["id"] != transaction_id
                    or not self._matches(row["kind"], json.loads(row["payload"]), saved)):
                raise RecoveryConflict("Check the saved record before acknowledging it")

            db.execute("UPDATE recovery_attempts SET stage = 'verified' WHERE id = ?", (attempt_id,))
            # Keep a short history in case the page closed after getting a
            # response but before the trader saw the result.
            db.execute(
                """DELETE FROM recovery_attempts WHERE id IN (
                       SELECT id FROM recovery_attempts
                       WHERE business_id = ? AND user_id = ? AND stage = 'verified'
                       ORDER BY created_at DESC, rowid DESC LIMIT -1 OFFSET 10
                   )""",
                (business_id, user_id),
            )
            return self._summary(row, "verified")
