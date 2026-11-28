import sqlite3
from decimal import Decimal
from uuid import uuid4

from app.db.ledger import Ledger, to_kobo, from_kobo


class RepaymentLedger(Ledger):
    """Ledger extended with auditable customer debt repayments."""

    def initialize(self):
        super().initialize()

        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS repayments (
                    id TEXT PRIMARY KEY,
                    business_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    repayment_reference TEXT NOT NULL,
                    amount_kobo INTEGER NOT NULL
                        CHECK(amount_kobo > 0),
                    created_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (business_id, customer_id)
                        REFERENCES customers(business_id, id),

                    UNIQUE (business_id, repayment_reference)
                );

                CREATE INDEX IF NOT EXISTS idx_repayments_customer
                    ON repayments(business_id, customer_id);

                CREATE TRIGGER IF NOT EXISTS
                    prevent_repayment_update
                BEFORE UPDATE ON repayments
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Confirmed repayments cannot be updated'
                    );
                END;

                CREATE TRIGGER IF NOT EXISTS
                    prevent_repayment_delete
                BEFORE DELETE ON repayments
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Confirmed repayments cannot be deleted'
                    );
                END;
            """)

    def _balance_kobo(self, db, business_id, customer_id):
        customer = db.execute(
            """SELECT id FROM customers
               WHERE business_id = ? AND id = ?""",
            (business_id, customer_id),
        ).fetchone()

        if customer is None:
            raise ValueError("Customer not found for business")

        sales = db.execute(
            """SELECT COALESCE(
                   SUM(total_kobo - paid_kobo), 0
               ) AS amount
               FROM sales
               WHERE business_id = ?
                 AND customer_id = ?
                 AND status = 'CONFIRMED'""",
            (business_id, customer_id),
        ).fetchone()["amount"]

        repayments = db.execute(
            """SELECT COALESCE(SUM(amount_kobo), 0) AS amount
               FROM repayments
               WHERE business_id = ?
                 AND customer_id = ?""",
            (business_id, customer_id),
        ).fetchone()["amount"]

        return sales - repayments

    def customer_balance(self, business_id, customer_id, *, _db=None):
        with self._using_connection(_db) as db:
            balance = self._balance_kobo(
                db, business_id, customer_id
            )

        return from_kobo(balance)

    def record_repayment(
        self,
        business_id,
        customer_id,
        reference,
        amount_naira,
        confirmed=False,
        *,
        _db=None,
    ):
        if confirmed is not True:
            raise ValueError(
                "Repayment must be confirmed before saving"
            )

        if not isinstance(reference, str) or not reference.strip():
            raise ValueError("Repayment reference is required")

        amount = to_kobo(amount_naira)

        if amount <= 0:
            raise ValueError(
                "Repayment must be greater than zero"
            )

        repayment_id = str(uuid4())

        with self._using_connection(_db, immediate=True) as db:
            existing = db.execute(
                """SELECT 1 FROM repayments
                   WHERE business_id = ? AND repayment_reference = ?""",
                (business_id, reference.strip()),
            ).fetchone()
            if existing:
                raise ValueError("Duplicate repayment reference")

            outstanding = self._balance_kobo(
                db, business_id, customer_id
            )

            if outstanding <= 0:
                raise ValueError(
                    "Customer has no outstanding debt"
                )

            if amount > outstanding:
                raise ValueError(
                    "Repayment exceeds outstanding balance"
                )

            try:
                db.execute(
                    """INSERT INTO repayments
                       (id, business_id, customer_id,
                        repayment_reference, amount_kobo)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        repayment_id,
                        business_id,
                        customer_id,
                        reference.strip(),
                        amount,
                    ),
                )
            except sqlite3.IntegrityError as error:
                if error.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                    raise ValueError("Duplicate repayment reference") from None
                raise

        return repayment_id

    def list_repayments(self, business_id, customer_id, *, _db=None):
        with self._using_connection(_db) as db:
            self._balance_kobo(
                db, business_id, customer_id
            )

            rows = db.execute(
                """SELECT id, repayment_reference,
                          amount_kobo, created_at
                   FROM repayments
                   WHERE business_id = ?
                     AND customer_id = ?
                   ORDER BY created_at, rowid""",
                (business_id, customer_id),
            ).fetchall()

        return [
            {
                "id": row["id"],
                "reference": row["repayment_reference"],
                "amount": from_kobo(row["amount_kobo"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
