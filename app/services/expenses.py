import sqlite3
from uuid import uuid4

from app.db.ledger import from_kobo, to_kobo
from app.services.statements import StatementLedger


class ExpenseLedger(StatementLedger):
    """Business-scoped, append-only expense recording."""

    def initialize(self):
        super().initialize()

        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS expenses (
                    id TEXT PRIMARY KEY,
                    business_id TEXT NOT NULL,
                    expense_reference TEXT NOT NULL,
                    category TEXT NOT NULL
                        CHECK(length(trim(category)) BETWEEN 2 AND 80),
                    description TEXT NOT NULL
                        CHECK(length(trim(description)) BETWEEN 3 AND 500),
                    amount_kobo INTEGER NOT NULL
                        CHECK(amount_kobo > 0),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(business_id) REFERENCES businesses(id),
                    UNIQUE(business_id, expense_reference)
                );

                CREATE INDEX IF NOT EXISTS idx_expenses_business_date
                    ON expenses(business_id, created_at);

                CREATE TRIGGER IF NOT EXISTS prevent_expense_update
                BEFORE UPDATE ON expenses
                BEGIN
                    SELECT RAISE(
                        ABORT, 'Recorded expenses cannot be updated'
                    );
                END;

                CREATE TRIGGER IF NOT EXISTS prevent_expense_delete
                BEFORE DELETE ON expenses
                BEGIN
                    SELECT RAISE(
                        ABORT, 'Recorded expenses cannot be deleted'
                    );
                END;
            """)

    def record_expense(
        self, token, business_id, reference,
        category, description, amount_naira, confirmed=False
    ):
        self._authorize(token, business_id)

        if confirmed is not True:
            raise ValueError("Expense requires confirmation")

        for value, minimum, maximum, label in (
            (reference, 1, 100, "Reference"),
            (category, 2, 80, "Category"),
            (description, 3, 500, "Description"),
        ):
            if (
                not isinstance(value, str)
                or not minimum <= len(value.strip()) <= maximum
            ):
                raise ValueError(f"Invalid expense {label.lower()}")

        amount = to_kobo(amount_naira)

        if amount <= 0:
            raise ValueError("Expense amount must be positive")

        expense_id = str(uuid4())

        with self.connect() as db:
            try:
                db.execute(
                    """INSERT INTO expenses
                       (id, business_id, expense_reference,
                        category, description, amount_kobo)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        expense_id,
                        business_id,
                        reference.strip(),
                        category.strip(),
                        description.strip(),
                        amount,
                    ),
                )
            except sqlite3.IntegrityError as error:
                if error.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                    raise ValueError("Duplicate expense reference") from None
                raise

        return expense_id

    def list_expenses(self, token, business_id):
        self._authorize(token, business_id)

        with self.connect() as db:
            rows = db.execute(
                """SELECT id, expense_reference, category,
                          description, amount_kobo, created_at
                   FROM expenses
                   WHERE business_id = ?
                   ORDER BY created_at, rowid""",
                (business_id,),
            ).fetchall()

        return [
            {
                "id": row["id"],
                "reference": row["expense_reference"],
                "category": row["category"],
                "description": row["description"],
                "amount": str(from_kobo(row["amount_kobo"])),
                "created_at": row["created_at"],
                "currency": "NGN",
            }
            for row in rows
        ]

    def expense_summary(self, token, business_id):
        self._authorize(token, business_id)

        with self.connect() as db:
            row = db.execute(
                """SELECT COUNT(*) AS expense_count,
                          COALESCE(SUM(amount_kobo), 0) AS total_kobo
                   FROM expenses
                   WHERE business_id = ?""",
                (business_id,),
            ).fetchone()

        return {
            "business_id": business_id,
            "currency": "NGN",
            "expense_count": row["expense_count"],
            "total_expenses": str(from_kobo(row["total_kobo"])),
        }
