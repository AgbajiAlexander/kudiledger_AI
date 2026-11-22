"""KudiLedger prototype: simple rule-based transaction extraction.

This is intentionally not an AI model. Confirm every proposed entry.
"""
import re
from dataclasses import dataclass
from decimal import Decimal

AMOUNT = r"(?:₦\s*)?(\d[\d,]*(?:\.\d{1,2})?)\s*(?:naira)?"

@dataclass(frozen=True)
class Transaction:
    customer: str
    sale: Decimal
    paid: Decimal
    balance: Decimal


def parse_sale(message: str) -> Transaction:
    """Parse limited examples: '<Name> bought ... worth X. He paid Y'."""
    message = message.strip()
    who = re.search(r"^([a-zA-Z][a-zA-Z'-]*)\s+bought\b", message, re.I)
    amount = re.search(r"\bworth\s+" + AMOUNT, message, re.I)
    paid = re.search(r"\bpaid\s+" + AMOUNT, message, re.I)
    if not (who and amount and paid):
        raise ValueError("Unsupported wording. Try: 'Musa bought goods worth 15000 naira. He paid 10000 naira.'")
    sale = Decimal(amount.group(1).replace(',', ''))
    payment = Decimal(paid.group(1).replace(',', ''))
    if sale <= 0 or payment < 0 or payment > sale:
        raise ValueError("Check amounts: sale must be positive and payment between zero and sale.")
    return Transaction(who.group(1).title(), sale, payment, sale - payment)


def money(amount: Decimal) -> str:
    return f"₦{amount:,.2f}"


def main() -> None:
    print("KudiLedger v0.1 — offline demonstration (not AI)")
    print("Example: Musa bought goods worth 15000 naira. He paid 10000 naira.")
    message = input("Describe a sale: ")
    try:
        tx = parse_sale(message)
    except ValueError as exc:
        print(f"Could not draft transaction: {exc}")
        return
    print("\nTRANSACTION DRAFT (NOT SAVED)")
    print(f"Customer: {tx.customer}")
    print(f"Sale:     {money(tx.sale)}")
    print(f"Paid:     {money(tx.paid)}")
    print(f"Balance:  {money(tx.balance)}")
    answer = input("Are these details correct? (yes/no): ").strip().lower()
    if answer == 'yes':
        print("Confirmed for demonstration only. No database or spreadsheet has been updated.")
    else:
        print("Discarded. Please correct the original message.")


if __name__ == '__main__':
    main()
