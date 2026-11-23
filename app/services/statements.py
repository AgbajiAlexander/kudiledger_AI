from app.db.ledger import from_kobo
from app.services.reversals import ReversalLedger


class StatementLedger(ReversalLedger):
    """Produce a customer debt statement from immutable records."""

    def customer_statement(self, token, business_id, customer_id):
        self._authorize(token, business_id)

        with self.connect() as db:
            # Check customer ownership through the existing ledger.
            authoritative_balance = self._balance_kobo(
                db, business_id, customer_id
            )

            rows = db.execute(
                """
                SELECT id, reference, kind, delta_kobo,
                       created_at, source_order, sequence
                FROM (
                    SELECT id, sale_reference AS reference,
                           'SALE' AS kind,
                           total_kobo - paid_kobo AS delta_kobo,
                           created_at,
                           1 AS source_order,
                           rowid AS sequence
                    FROM sales
                    WHERE business_id = ? AND customer_id = ?

                    UNION ALL

                    SELECT id, repayment_reference,
                           'REPAYMENT', -amount_kobo,
                           created_at, 2, rowid
                    FROM repayments
                    WHERE business_id = ? AND customer_id = ?

                    UNION ALL

                    SELECT id, adjustment_reference,
                           'ADJUSTMENT', delta_kobo,
                           created_at, 3, rowid
                    FROM debt_adjustments
                    WHERE business_id = ? AND customer_id = ?

                    UNION ALL

                    SELECT r.id, r.reversal_reference,
                           'SALE_REVERSAL', -r.amount_kobo,
                           r.created_at, 4, r.rowid
                    FROM sale_reversals r
                    JOIN sales s ON s.id = r.sale_id
                    WHERE r.business_id = ?
                      AND s.business_id = ?
                      AND s.customer_id = ?
                )
                ORDER BY created_at, source_order, sequence
                """,
                (
                    business_id, customer_id,
                    business_id, customer_id,
                    business_id, customer_id,
                    business_id, business_id, customer_id,
                ),
            ).fetchall()

        running_balance = 0
        transactions = []

        for row in rows:
            running_balance += row["delta_kobo"]

            transactions.append({
                "id": row["id"],
                "reference": row["reference"],
                "type": row["kind"],
                "date": row["created_at"],
                "debt_change": str(
                    from_kobo(row["delta_kobo"])
                ),
                "running_balance": str(
                    from_kobo(running_balance)
                ),
            })

        return {
            "business_id": business_id,
            "customer_id": customer_id,
            "currency": "NGN",
            "transactions": transactions,
            "transaction_count": len(transactions),
            "closing_balance": str(
                from_kobo(authoritative_balance)
            ),
            "reconciled": (
                running_balance == authoritative_balance
            ),
        }
