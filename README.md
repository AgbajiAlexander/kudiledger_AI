# KudiLedger AI — Starter Engine v0.1

This is a **rule-based offline prototype**, not yet an AI model. It only recognizes a narrow sentence pattern, and stores nothing. Never use it to book real financial transactions.

## Requirements
- Python 3.10 or newer. No third-party packages.

## Windows PowerShell
```powershell
cd "$HOME\Desktop\KudiLedger-AI\03-Product-Development"
python engine.py
```
If Python is installed through the launcher, `py engine.py` is also supported.

Input example: `Musa bought goods worth 15000 naira. He paid 10000 naira.`

Run tests: `python -m unittest -v`

## Next milestones
1. Flexible AI-based extraction with a strict schema and human confirmation.
2. Save confirmed records in a transactional database.
3. Add debt repayments, expense tracking, and reports.
4. Connect WhatsApp with authorized accounts and privacy safeguards.
