from app.db.repayments import RepaymentLedger


ledger = RepaymentLedger("demo_repayments.db")

business_id = ledger.create_business(
    "Demo Abuja Provision Shop"
)

customer_id = ledger.create_customer(
    business_id, "Musa"
)

ledger.record_sale(
    business_id,
    customer_id,
    "SALE-001",
    "15000",
    "10000",
    confirmed=True,
)

print("Customer: Musa")
print("Sale amount: NGN 15,000.00")
print("Initial payment: NGN 10,000.00")

print(
    "Outstanding before repayment:",
    ledger.customer_balance(business_id, customer_id),
)

ledger.record_repayment(
    business_id,
    customer_id,
    "PAY-001",
    "3000",
    confirmed=True,
)

print("Repayment recorded: NGN 3,000.00")

print(
    "Outstanding after repayment:",
    ledger.customer_balance(business_id, customer_id),
)

reopened = RepaymentLedger("demo_repayments.db")

print(
    "Balance after reopening:",
    reopened.customer_balance(business_id, customer_id),
)

print("Repayment history:")
for payment in reopened.list_repayments(
    business_id, customer_id
):
    print(payment["reference"], payment["amount"])
