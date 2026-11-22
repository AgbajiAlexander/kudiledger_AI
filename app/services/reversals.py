import sqlite3
from uuid import uuid4

from app.db.ledger import from_kobo
from app.services.adjustments import AdjustmentLedger


class ReversalLedger(AdjustmentLedger):
    """Record immutable reversals of eligible unpaid sales."""

    def initialize(self):
        super().initialize()

        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sale_reversals (
                    id TEXT PRIMARY KEY,
                    business_id TEXT NOT NULL,
                    sale_id TEXT NOT NULL,
                    reversal_reference TEXT NOT NULL,
                    amount_kobo INTEGER NOT NULL
                        CHECK(amount_kobo > 0),
                    reason TEXT NOT NULL
                        CHECK(length(trim(reason)) BETWEEN 10 AND 500),
                    created_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (business_id)
                        REFERENCES businesses(id),
                    FOREIGN KEY (sale_id)
                        REFERENCES sales(id),

                    UNIQUE(sale_id),
                    UNIQUE(business_id, reversal_reference)
                );

                CREATE INDEX IF NOT EXISTS idx_sale_reversals_business
                    ON sale_reversals(business_id);

                CREATE TRIGGER IF NOT EXISTS
                    prevent_sale_reversal_update
                BEFORE UPDATE ON sale_reversals
                BEGIN
                    SELECT RAISE(
                        ABORT, 'Sale reversals cannot be updated'
                    );
                END;

                CREATE TRIGGER IF NOT EXISTS
                    prevent_sale_reversal_delete
                BEFORE DELETE ON sale_reversals
                BEGIN
                    SELECT RAISE(
                        ABORT, 'Sale reversals cannot be deleted'
                    );
                END;
            """)

    def _balance_kobo(self, db, business_id, customer_id):
        original = super()._balance_kobo(
            db, business_id, customer_id
        )

        reversed_total = db.execute(
            """SELECT COALESCE(SUM(r.amount_kobo), 0) AS total
               FROM sale_reversals r
               JOIN sales s ON s.id = r.sale_id
               WHERE r.business_id = ?
                 AND s.business_id = ?
                 AND s.customer_id = ?""",
            (business_id, business_id, customer_id),
        ).fetchone()["total"]

        return original - reversed_total

    def reverse_unpaid_sale(
        self, token, business_id, sale_id,
        reference, reason, confirmed=False
    ):
        self._authorize(token, business_id)

        if confirmed is not True:
            raise ValueError("Reversal requires confirmation")

        if not isinstance(reference, str):
            raise ValueError("Reversal reference is required")

        reference = reference.strip()

        if not 1 <= len(reference) <= 100:
            raise ValueError("Invalid reversal reference")

        if not isinstance(reason, str):
            raise ValueError("Reversal reason is required")

        reason = reason.strip()

        if not 10 <= len(reason) <= 500:
            raise ValueError(
                "Reason must contain 10 to 500 characters"
            )

        reversal_id = str(uuid4())

        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")

            sale = db.execute(
                """SELECT id, customer_id, total_kobo, paid_kobo
                   FROM sales
                   WHERE id = ? AND business_id = ?
                     AND status = 'CONFIRMED'""",
                (sale_id, business_id),
            ).fetchone()

            if sale is None:
                raise ValueError("Sale not found for business")

            if sale["paid_kobo"] != 0:
                raise ValueError(
                    "Paid sales require a refund workflow"
                )

            customer_id = sale["customer_id"]

            repayments = db.execute(
                """SELECT COUNT(*) AS count
                   FROM repayments
                   WHERE business_id = ? AND customer_id = ?""",
                (business_id, customer_id),
            ).fetchone()["count"]

            adjustments = db.execute(
                """SELECT COUNT(*) AS count
                   FROM debt_adjustments
                   WHERE business_id = ? AND customer_id = ?""",
                (business_id, customer_id),
            ).fetchone()["count"]

            if repayments or adjustments:
                raise ValueError(
                    "Customer has subsequent financial activity; "
                    "manual reconciliation is required"
                )

            outstanding = self._balance_kobo(
                db, business_id, customer_id
            )

            if outstanding < sale["total_kobo"]:
                raise ValueError(
                    "Reversal would create a negative balance"
                )

            try:
                db.execute(
                    """INSERT INTO sale_reversals
                       (id, business_id, sale_id,
                        reversal_reference, amount_kobo, reason)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        reversal_id, business_id, sale_id,
                        reference, sale["total_kobo"], reason,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    "Sale already reversed or duplicate reference"
                ) from error

        return reversal_id

    def list_sale_reversals(self, token, business_id):
        self._authorize(token, business_id)

        with self.connect() as db:
            rows = db.execute(
                """SELECT r.id, r.sale_id,
                          r.reversal_reference, r.amount_kobo,
                          r.reason, r.created_at
                   FROM sale_reversals r
                   WHERE r.business_id = ?
                   ORDER BY r.created_at, r.rowid""",
                (business_id,),
            ).fetchall()

        return [
            {
                "id": row["id"],
                "sale_id": row["sale_id"],
                "reference": row["reversal_reference"],
                "amount": from_kobo(row["amount_kobo"]),
                "reason": row["reason"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
