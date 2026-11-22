from app.db.ledger import Ledger

ledger = Ledger("demo_kudiledger.db")

business_id = ledger.create_business("Demo Provision Shop")
customer_id = ledger.create_customer(business_id, "Musa")

ledger.record_sale(
    business_id=business_id,
    customer_id=customer_id,
    reference="SALE-001",
    total_naira="15000",
    paid_naira="10000",
    confirmed=True,
)

print("Sale recorded successfully.")
print("Customer: Musa")
print("Total sale: NGN 15,000")
print("Amount paid: NGN 10,000")

balance = ledger.customer_balance(
    business_id, customer_id
)

print(f"Outstanding balance: NGN {balance:,.2f}")

reopened = Ledger("demo_kudiledger.db")
saved_balance = reopened.customer_balance(
    business_id, customer_id
)

print(f"Balance after reopening: NGN {saved_balance:,.2f}")
