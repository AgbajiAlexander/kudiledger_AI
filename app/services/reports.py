from datetime import date

from app.db.ledger import from_kobo
from app.services.expenses import ExpenseLedger


class ReportLedger(ExpenseLedger):
    """Daily activity summary using existing financial records."""

    def daily_summary(self, token, business_id, report_date):
        self._authorize(token, business_id)

        if not isinstance(report_date, str):
            raise ValueError("Report date must use YYYY-MM-DD")

        try:
            parsed = date.fromisoformat(report_date)
        except ValueError:
            raise ValueError(
                "Invalid report date; use YYYY-MM-DD"
            ) from None

        if parsed.isoformat() != report_date:
            raise ValueError("Report date must use YYYY-MM-DD")

        with self.connect() as db:
            sales = db.execute(
                """SELECT COUNT(*) AS count,
                          COALESCE(SUM(total_kobo), 0) AS total,
                          COALESCE(SUM(paid_kobo), 0) AS paid
                   FROM sales
                   WHERE business_id = ?
                     AND date(created_at) = ?
                     AND status = 'CONFIRMED'""",
                (business_id, report_date),
            ).fetchone()

            repayments = db.execute(
                """SELECT COUNT(*) AS count,
                          COALESCE(SUM(amount_kobo), 0) AS total
                   FROM repayments
                   WHERE business_id = ?
                     AND date(created_at) = ?""",
                (business_id, report_date),
            ).fetchone()

            expenses = db.execute(
                """SELECT COUNT(*) AS count,
                          COALESCE(SUM(amount_kobo), 0) AS total
                   FROM expenses
                   WHERE business_id = ?
                     AND date(created_at) = ?""",
                (business_id, report_date),
            ).fetchone()

            reversals = db.execute(
                """SELECT COUNT(*) AS count,
                          COALESCE(SUM(amount_kobo), 0) AS total
                   FROM sale_reversals
                   WHERE business_id = ?
                     AND date(created_at) = ?""",
                (business_id, report_date),
            ).fetchone()

            customers = db.execute(
                """SELECT id FROM customers WHERE business_id = ?""",
                (business_id,),
            ).fetchall()

            outstanding = sum(
                self._balance_kobo(db, business_id, row["id"])
                for row in customers
            )

        cash_received = sales["paid"] + repayments["total"]

        return {
            "business_id": business_id,
            "date": report_date,
            "timezone": "UTC",
            "currency": "NGN",
            "sales_count": sales["count"],
            "gross_sales": str(from_kobo(sales["total"])),
            "paid_at_sale": str(from_kobo(sales["paid"])),
            "repayments_count": repayments["count"],
            "repayments_received": str(
                from_kobo(repayments["total"])
            ),
            "recorded_cash_received": str(
                from_kobo(cash_received)
            ),
            "expenses_count": expenses["count"],
            "operating_expenses": str(
                from_kobo(expenses["total"])
            ),
            "reversals_count": reversals["count"],
            "reversed_sale_value": str(
                from_kobo(reversals["total"])
            ),
            "current_outstanding_debt": str(
                from_kobo(outstanding)
            ),
        }


    def lookup_transaction(
        self, token, business_id, kind, reference
    ):
        """Look up an existing business transaction by reference."""
        self._authorize(token, business_id)

        if kind not in ("sale", "repayment", "expense"):
            raise ValueError("Invalid transaction type")

        if (
            not isinstance(reference, str)
            or not 1 <= len(reference.strip()) <= 100
        ):
            raise ValueError("Invalid transaction reference")

        reference = reference.strip()

        queries = {
            "sale": """
                SELECT id, customer_id, sale_reference AS reference,
                       total_kobo, paid_kobo, created_at
                FROM sales
                WHERE business_id = ? AND sale_reference = ?
            """,
            "repayment": """
                SELECT id, customer_id,
                       repayment_reference AS reference,
                       amount_kobo, created_at
                FROM repayments
                WHERE business_id = ? AND repayment_reference = ?
            """,
            "expense": """
                SELECT id, expense_reference AS reference,
                       category, description,
                       amount_kobo, created_at
                FROM expenses
                WHERE business_id = ? AND expense_reference = ?
            """,
        }

        with self.connect() as db:
            row = db.execute(
                queries[kind],
                (business_id, reference),
            ).fetchone()

        if row is None:
            return {
                "found": False,
                "kind": kind,
                "reference": reference,
            }

        result = {
            "found": True,
            "kind": kind,
            "id": row["id"],
            "reference": row["reference"],
            "created_at": row["created_at"],
            "currency": "NGN",
        }

        if kind == "sale":
            result.update({
                "customer_id": row["customer_id"],
                "total": str(from_kobo(row["total_kobo"])),
                "paid": str(from_kobo(row["paid_kobo"])),
            })
        elif kind == "repayment":
            result.update({
                "customer_id": row["customer_id"],
                "amount": str(from_kobo(row["amount_kobo"])),
            })
        else:
            result.update({
                "category": row["category"],
                "description": row["description"],
                "amount": str(from_kobo(row["amount_kobo"])),
            })

        return result

