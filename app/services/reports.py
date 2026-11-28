from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.db.ledger import from_kobo
from app.services.expenses import ExpenseLedger


LAGOS = ZoneInfo("Africa/Lagos")


class ReportLedger(ExpenseLedger):
    """Daily activity summary using existing financial records."""

    def daily_summary(self, token, business_id, report_date):
        with self._authorized_read(token, business_id) as db:
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

            try:
                start_utc = datetime.combine(
                    parsed, time.min, LAGOS
                ).astimezone(timezone.utc)
                end_utc = datetime.combine(
                    parsed + timedelta(days=1), time.min, LAGOS
                ).astimezone(timezone.utc)
            except OverflowError:
                raise ValueError("Report date exceeds supported range") from None

            # Match the UTC text format written by SQLite CURRENT_TIMESTAMP.
            bounds = tuple(
                f"{instant.date().isoformat()} {instant.time().isoformat(timespec='seconds')}"
                for instant in (start_utc, end_utc)
            )
            sales = db.execute(
                """SELECT COUNT(*) AS count,
                          COALESCE(SUM(total_kobo), 0) AS total,
                          COALESCE(SUM(paid_kobo), 0) AS paid
                   FROM sales
                   WHERE business_id = ?
                     AND created_at >= ? AND created_at < ?
                     AND status = 'CONFIRMED'""",
                (business_id, *bounds),
            ).fetchone()

            repayments = db.execute(
                """SELECT COUNT(*) AS count,
                          COALESCE(SUM(amount_kobo), 0) AS total
                   FROM repayments
                   WHERE business_id = ?
                     AND created_at >= ? AND created_at < ?""",
                (business_id, *bounds),
            ).fetchone()

            expenses = db.execute(
                """SELECT COUNT(*) AS count,
                          COALESCE(SUM(amount_kobo), 0) AS total
                   FROM expenses
                   WHERE business_id = ?
                     AND created_at >= ? AND created_at < ?""",
                (business_id, *bounds),
            ).fetchone()

            reversals = db.execute(
                """SELECT COUNT(*) AS count,
                          COALESCE(SUM(amount_kobo), 0) AS total
                   FROM sale_reversals
                   WHERE business_id = ?
                     AND created_at >= ? AND created_at < ?""",
                (business_id, *bounds),
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
            "timezone": LAGOS.key,
            "period_start_utc": start_utc.isoformat(),
            "period_end_utc": end_utc.isoformat(),
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


    def _find_transaction(self, db, business_id, kind, identifier, *, by_id=False):
        # Identifiers in SQL come only from these fixed transaction definitions.
        definitions = {
            "sale": ("sales", "sale_reference", "t.customer_id, t.total_kobo, t.paid_kobo",
                     "AND t.status = 'CONFIRMED'"),
            "repayment": ("repayments", "repayment_reference", "t.customer_id, t.amount_kobo", ""),
            "expense": ("expenses", "expense_reference", "t.category, t.description, t.amount_kobo", ""),
        }
        if kind not in definitions:
            raise ValueError("Invalid transaction type")

        table, reference, fields, condition = definitions[kind]
        column = "id" if by_id else reference
        customer = "NULL" if kind == "expense" else "t.customer_id"
        return db.execute(
            f"""SELECT t.id, t.{reference} AS reference, t.created_at, {fields},
                           b.name AS business_name, c.name AS customer_name,
                           EXISTS (
                               SELECT 1 FROM sale_reversals r
                               WHERE r.business_id = t.business_id AND r.sale_id = t.id
                           ) AS reversed
                    FROM {table} t
                    JOIN businesses b ON b.id = t.business_id
                    LEFT JOIN customers c ON c.business_id = t.business_id AND c.id = {customer}
                    WHERE t.business_id = ? AND t.{column} = ? {condition}""",
            (business_id, identifier),
        ).fetchone()

    def lookup_transaction(self, token, business_id, kind, reference):
        """Look up an existing business transaction by reference."""
        with self._authorized_read(token, business_id) as db:
            if kind not in ("sale", "repayment", "expense"):
                raise ValueError("Invalid transaction type")
            if not isinstance(reference, str) or not 1 <= len(reference.strip()) <= 100:
                raise ValueError("Invalid transaction reference")

            reference = reference.strip()
            row = self._find_transaction(db, business_id, kind, reference)

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


    def transaction_receipt(self, token, business_id, kind, transaction_id, reference):
        """Read a receipt for a committed transaction owned by this business."""
        with self._authorized_read(token, business_id) as db:
            if (transaction_id is None) == (reference is None):
                raise ValueError("Provide either transaction_id or reference")
            by_id = transaction_id is not None
            identifier = (transaction_id if by_id else reference).strip()
            if not 1 <= len(identifier) <= 100:
                raise ValueError("Invalid transaction identifier")
            row = self._find_transaction(db, business_id, kind, identifier, by_id=by_id)
        if row is None:
            return None

        recorded = datetime.fromisoformat(row["created_at"])
        if recorded.tzinfo is None:
            # SQLite CURRENT_TIMESTAMP stores UTC without an offset suffix.
            recorded = recorded.replace(tzinfo=timezone.utc)
        recorded_utc = recorded.astimezone(timezone.utc)
        amount = row["total_kobo"] if kind == "sale" else row["amount_kobo"]
        receipt = {
            "id": row["id"],
            "kind": kind,
            "reference": row["reference"],
            "business_name": row["business_name"],
            "currency": "NGN",
            "amount": f"{from_kobo(amount):.2f}",
            "recorded_at_utc": recorded_utc.isoformat(),
            "recorded_at_local": recorded_utc.astimezone(LAGOS).isoformat(),
            "timezone": LAGOS.key,
            "external_payment_verified": False,
        }
        if kind == "sale":
            receipt.update(
                customer_name=row["customer_name"],
                paid_at_sale=f"{from_kobo(row['paid_kobo']):.2f}",
                due_at_sale=f"{from_kobo(amount - row['paid_kobo']):.2f}",
                reversed=bool(row["reversed"]),
            )
        elif kind == "repayment":
            receipt["customer_name"] = row["customer_name"]
        else:
            receipt.update(category=row["category"], description=row["description"])
        return receipt
