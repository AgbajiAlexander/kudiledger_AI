import json
from uuid import uuid4

from app.services.recovery import RecoveryConflict, RecoveryLedger, RecoveryNotFound


class PilotLedger(RecoveryLedger):
    def initialize(self):
        super().initialize()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS recovery_operators (
                    user_id TEXT NOT NULL,
                    business_id TEXT NOT NULL,
                    granted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, business_id),
                    FOREIGN KEY (user_id, business_id)
                        REFERENCES memberships(user_id, business_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS recovery_operator_audit (
                    id TEXT PRIMARY KEY,
                    attempt_id TEXT NOT NULL,
                    business_id TEXT NOT NULL,
                    subject_user_id TEXT NOT NULL,
                    operator_user_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    reference TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,
                    evidence_reference TEXT NOT NULL,
                    evidence_notes TEXT NOT NULL,
                    previous_stage TEXT NOT NULL,
                    resulting_stage TEXT NOT NULL,
                    transaction_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS recovery_audit_lookup
                    ON recovery_operator_audit(business_id, attempt_id);
                CREATE TRIGGER IF NOT EXISTS recovery_audit_no_update
                    BEFORE UPDATE ON recovery_operator_audit
                    BEGIN SELECT RAISE(ABORT, 'Operator audit is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS recovery_audit_no_delete
                    BEFORE DELETE ON recovery_operator_audit
                    BEGIN SELECT RAISE(ABORT, 'Operator audit is immutable'); END;
            """)

    def set_recovery_operator(self, business_id, email, *, enabled):
        """Provision a grant through the trusted database-host CLI."""
        with self._using_connection(immediate=True) as db:
            member = db.execute(
                """SELECT u.id FROM users u
                   JOIN memberships m ON m.user_id = u.id
                   WHERE u.email = ? AND m.business_id = ?""",
                (email.strip().casefold(), business_id),
            ).fetchone()
            if member is None:
                raise ValueError("Operator must already belong to the business")
            if enabled:
                db.execute(
                    """INSERT INTO recovery_operators (user_id, business_id)
                       VALUES (?, ?) ON CONFLICT (user_id, business_id) DO NOTHING""",
                    (member["id"], business_id),
                )
            else:
                db.execute(
                    "DELETE FROM recovery_operators WHERE user_id = ? AND business_id = ?",
                    (member["id"], business_id),
                )

    def _operator(self, db, token, business_id):
        user_id = self._membership(token, business_id, _db=db)["user_id"]
        grant = db.execute(
            "SELECT 1 FROM recovery_operators WHERE user_id = ? AND business_id = ?",
            (user_id, business_id),
        ).fetchone()
        if grant is None:
            raise PermissionError("Recovery operator permission required")
        return user_id

    def list_operator_recovery(self, token, business_id, reference=None):
        with self.connect() as db:
            db.execute("BEGIN")
            self._operator(db, token, business_id)
            rows = db.execute(
                """SELECT id, kind, reference, stage, created_at
                   FROM recovery_attempts
                   WHERE business_id = ? AND stage IN ('sending', 'saved', 'conflict')
                     AND (? IS NULL OR reference = ?)
                   ORDER BY created_at, id LIMIT 100""",
                (business_id, reference, reference),
            ).fetchall()
        return [self._summary(row) for row in rows]

    def operator_recovery_audit(self, token, business_id, attempt_id):
        with self.connect() as db:
            db.execute("BEGIN")
            self._operator(db, token, business_id)
            rows = db.execute(
                """SELECT * FROM recovery_operator_audit
                   WHERE business_id = ? AND attempt_id = ?
                   ORDER BY created_at, rowid""",
                (business_id, attempt_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def decide_recovery(
        self, token, business_id, attempt_id, *, decision,
        evidence_type, evidence_reference, evidence_notes, confirmed,
    ):
        evidence_reference = evidence_reference.strip()
        evidence_notes = evidence_notes.strip()
        if not evidence_reference or len(evidence_notes) < 24:
            raise ValueError("Include an evidence reference and at least 24 characters of notes")
        if confirmed is not True:
            raise ValueError("Confirm the investigation decision")

        with self._using_connection(immediate=True) as db:
            operator_id = self._operator(db, token, business_id)
            row = db.execute(
                "SELECT * FROM recovery_attempts WHERE business_id = ? AND id = ?",
                (business_id, attempt_id),
            ).fetchone()
            if row is None:
                raise RecoveryNotFound("Recovery record not found")
            previous = row["stage"]
            if previous not in ("sending", "saved", "conflict"):
                raise RecoveryConflict("Only a blocked recovery record can be investigated")

            saved = self._find_transaction(db, business_id, row["kind"], row["reference"])
            match = saved is not None and self._matches(row["kind"], json.loads(row["payload"]), saved)
            stage = self._decision_stage(previous, decision, evidence_type, saved is not None, match)

            audit_id = str(uuid4())
            db.execute("UPDATE recovery_attempts SET stage = ? WHERE id = ?", (stage, attempt_id))
            db.execute(
                """INSERT INTO recovery_operator_audit (
                       id, attempt_id, business_id, subject_user_id, operator_user_id,
                       kind, reference, decision, evidence_type, evidence_reference,
                       evidence_notes, previous_stage, resulting_stage, transaction_id
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (audit_id, attempt_id, business_id, row["user_id"], operator_id,
                 row["kind"], row["reference"], decision, evidence_type, evidence_reference,
                 evidence_notes, previous, stage, saved["id"] if saved is not None else None),
            )
            return {
                "audit_id": audit_id,
                "status": "committed" if stage == "verified" else self._summary(row, stage)["status"],
            }

    @staticmethod
    def _decision_stage(previous, decision, evidence_type, found, match):
        if decision == "retain_uncertain" and evidence_type == "inconclusive":
            return previous
        if decision == "confirm_committed" and evidence_type == "ledger_match" and match:
            return "verified"
        if decision == "release_failed" and not match:
            if evidence_type == "ledger_conflict" and found:
                return "rejected"
            if evidence_type == "prewrite_failure" and not found and previous == "sending":
                return "rejected"
        raise RecoveryConflict("The decision is unsupported by the ledger and specified evidence")
