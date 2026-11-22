# KudiLedger AI — Engineering Rules

## Project
KudiLedger AI is a Nigerian SME financial
record-keeping application with AI assistance.

## Development Principles
1. Keep financial calculations deterministic.
2. Use Decimal or integer minor units for money.
3. Never trust AI-generated financial calculations.
4. Require user confirmation before saving AI drafts.
5. Never hardcode API keys or passwords.
6. Keep each business's records isolated.
7. Create tests for every financial rule.
8. Never silently delete confirmed transactions.
9. Use database transactions for financial writes.
10. Preserve auditability of corrections and payments.

## Current Architecture
- Language: Python
- Local development database: SQLite
- Production database: PostgreSQL
- Backend framework: FastAPI
- Future interfaces: Web dashboard and WhatsApp

## Development Workflow
1. Implement one task.
2. Run tests.
3. Review changes.
4. Commit only verified changes.
