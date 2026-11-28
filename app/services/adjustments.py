import sqlite3
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from app.db.ledger import to_kobo, from_kobo
from app.services.accounts import AccountLedger


class AdjustmentLedger(AccountLedger):
    """An append-only customer debt adjustment ledger."""

    def initialize(self):
        super().initialize()

        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS debt_adjustments (
                    id TEXT PRIMARY KEY,
                    business_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    adjustment_reference TEXT NOT NULL,
                    delta_kobo INTEGER NOT NULL
                        CHECK(delta_kobo != 0),
                    reason TEXT NOT NULL
                        CHECK(
                            length(trim(reason)) BETWEEN 10 AND 500
                        ),
                    created_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (business_id, customer_id)
                        REFERENCES customers(business_id, id),
                    UNIQUE(business_id, adjustment_reference)
                );

                CREATE INDEX IF NOT EXISTS
                    idx_debt_adjustments_customer
                ON debt_adjustments(business_id, customer_id);

                CREATE TRIGGER IF NOT EXISTS
                    prevent_debt_adjustment_update
                BEFORE UPDATE ON debt_adjustments
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Debt adjustments cannot be updated'
                    );
                END;

                CREATE TRIGGER IF NOT EXISTS
                    prevent_debt_adjustment_delete
                BEFORE DELETE ON debt_adjustments
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Debt adjustments cannot be deleted'
                    );
                END;
            """)

    def _balance_kobo(self, db, business_id, customer_id):
        original = super()._balance_kobo(
            db, business_id, customer_id
        )

        result = db.execute(
            """SELECT COALESCE(SUM(delta_kobo), 0) AS total
               FROM debt_adjustments
               WHERE business_id = ? AND customer_id = ?""",
            (business_id, customer_id),
        ).fetchone()

        return original + result["total"]

    def adjust_customer_balance(
        self, token, business_id, customer_id,
        reference, amount_naira, reason, confirmed=False
    ):
        self._authorize(token, business_id)

        if confirmed is not True:
            raise ValueError("Adjustment requires confirmation")

        if not isinstance(reference, str):
            raise ValueError("Invalid adjustment reference")

        reference = reference.strip()

        if not reference or len(reference) > 100:
            raise ValueError("Invalid adjustment reference")

        if not isinstance(reason, str):
            raise ValueError("A correction reason is required")

        reason = reason.strip()

        if not 10 <= len(reason) <= 500:
            raise ValueError(
                "Reason must contain 10 to 500 characters"
            )

        try:
            value = Decimal(str(amount_naira))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError("Invalid adjustment amount") from None

        if not value.is_finite() or value == 0:
            raise ValueError("Adjustment must be nonzero")

        magnitude = to_kobo(abs(value))
        delta = -magnitude if value < 0 else magnitude

        adjustment_id = str(uuid4())

        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._authorize(token, business_id, _db=db)

            current = self._balance_kobo(
                db, business_id, customer_id
            )

            if current + delta < 0:
                raise ValueError(
                    "Adjustment exceeds outstanding debt"
                )

            try:
                db.execute(
                    """INSERT INTO debt_adjustments
                       (id, business_id, customer_id,
                        adjustment_reference, delta_kobo, reason)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        adjustment_id, business_id, customer_id,
                        reference, delta, reason
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    "Duplicate adjustment reference or invalid data"
                ) from error

        return adjustment_id

    def get_adjustments(self, token, business_id, customer_id):
        with self._authorized_read(token, business_id) as db:
            self._balance_kobo(
                db, business_id, customer_id
            )

            rows = db.execute(
                """SELECT id, adjustment_reference,
                          delta_kobo, reason, created_at
                   FROM debt_adjustments
                   WHERE business_id = ? AND customer_id = ?
                   ORDER BY created_at, rowid""",
                (business_id, customer_id),
            ).fetchall()

        return [
            {
                "id": row["id"],
                "reference": row["adjustment_reference"],
                "amount": from_kobo(row["delta_kobo"]),
                "reason": row["reason"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
