import sqlite3
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4


def to_kobo(amount):
    """Convert a naira amount to exact integer kobo."""
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Invalid money amount") from None

    if not value.is_finite():
        raise ValueError("Amount must be finite")

    if value < 0:
        raise ValueError("Amount cannot be negative")

    if value.as_tuple().exponent < -2:
        raise ValueError("Use at most two decimal places")

    kobo = int(value * 100)

    if kobo > 9_000_000_000_000_000:
        raise ValueError("Amount exceeds supported limit")

    return kobo


def from_kobo(kobo):
    """Return a Decimal naira amount."""
    return Decimal(kobo) / Decimal(100)


class Ledger:
    def __init__(self, database_path="kudiledger.db"):
        self.database_path = str(Path(database_path))
        self.initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS businesses (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL CHECK(length(trim(name)) > 0)
                );

                CREATE TABLE IF NOT EXISTS customers (
                    id TEXT PRIMARY KEY,
                    business_id TEXT NOT NULL,
                    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
                    FOREIGN KEY (business_id)
                        REFERENCES businesses(id),
                    UNIQUE (business_id, id)
                );

                CREATE TABLE IF NOT EXISTS sales (
                    id TEXT PRIMARY KEY,
                    business_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    sale_reference TEXT NOT NULL,
                    total_kobo INTEGER NOT NULL
                        CHECK(total_kobo > 0),
                    paid_kobo INTEGER NOT NULL
                        CHECK(paid_kobo >= 0),
                    status TEXT NOT NULL DEFAULT 'CONFIRMED'
                        CHECK(status = 'CONFIRMED'),
                    created_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    CHECK(paid_kobo <= total_kobo),
                    FOREIGN KEY (business_id)
                        REFERENCES businesses(id),
                    FOREIGN KEY (business_id, customer_id)
                        REFERENCES customers(business_id, id),
                    UNIQUE (business_id, sale_reference)
                );

                CREATE INDEX IF NOT EXISTS idx_sales_customer
                    ON sales(business_id, customer_id);
            """)

    def create_business(self, name):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Business name is required")

        business_id = str(uuid4())

        with self.connect() as db:
            db.execute(
                "INSERT INTO businesses (id, name) VALUES (?, ?)",
                (business_id, name.strip()),
            )

        return business_id

    def create_customer(self, business_id, name):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Customer name is required")

        customer_id = str(uuid4())

        with self.connect() as db:
            if not db.execute(
                "SELECT id FROM businesses WHERE id = ?",
                (business_id,),
            ).fetchone():
                raise ValueError("Business not found")

            db.execute(
                """INSERT INTO customers
                   (id, business_id, name)
                   VALUES (?, ?, ?)""",
                (customer_id, business_id, name.strip()),
            )

        return customer_id

    def record_sale(
        self,
        business_id,
        customer_id,
        reference,
        total_naira,
        paid_naira,
        confirmed=False,
    ):
        if confirmed is not True:
            raise ValueError("Sale must be confirmed before saving")

        if not isinstance(reference, str) or not reference.strip():
            raise ValueError("Sale reference is required")

        total = to_kobo(total_naira)
        paid = to_kobo(paid_naira)

        if total == 0:
            raise ValueError("Sale amount must be greater than zero")

        if paid > total:
            raise ValueError("Payment cannot exceed sale amount")

        sale_id = str(uuid4())

        with self.connect() as db:
            customer = db.execute(
                """SELECT id FROM customers
                   WHERE id = ? AND business_id = ?""",
                (customer_id, business_id),
            ).fetchone()

            if customer is None:
                raise ValueError("Customer does not belong to business")

            try:
                db.execute(
                    """INSERT INTO sales
                       (id, business_id, customer_id,
                        sale_reference, total_kobo, paid_kobo)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        sale_id,
                        business_id,
                        customer_id,
                        reference.strip(),
                        total,
                        paid,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    "Duplicate sale reference or invalid sale"
                ) from error

        return sale_id

    def customer_balance(self, business_id, customer_id):
        with self.connect() as db:
            customer = db.execute(
                """SELECT id FROM customers
                   WHERE id = ? AND business_id = ?""",
                (customer_id, business_id),
            ).fetchone()

            if customer is None:
                raise ValueError("Customer not found for business")

            result = db.execute(
                """SELECT COALESCE(
                       SUM(total_kobo - paid_kobo), 0
                   ) AS balance
                   FROM sales
                   WHERE business_id = ?
                   AND customer_id = ?
                   AND status = 'CONFIRMED'""",
                (business_id, customer_id),
            ).fetchone()

        return from_kobo(result["balance"])
