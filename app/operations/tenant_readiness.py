"""Read-only, redacted validation of branch mappings and effective owners."""

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from app.operations.migration_reconciliation import _open_snapshot
from app.services.authorization import has_scope_schema


CHECKS = {
    "unmapped_businesses": """SELECT count(*) FROM businesses l
        WHERE NOT EXISTS (SELECT 1 FROM branches b WHERE b.id = l.id)""",
    "duplicate_branch_ids": """SELECT count(*) FROM (
        SELECT id FROM branches GROUP BY id HAVING count(*) > 1)""",
    "conflicting_branches": """SELECT count(*) FROM branches b
        LEFT JOIN businesses l ON l.id = b.id LEFT JOIN organizations o ON o.id = b.organization_id
        WHERE l.id IS NULL OR o.id IS NULL OR b.id = b.organization_id""",
    "wrong_default_counts": """SELECT count(*) FROM organizations o WHERE
        (SELECT count(*) FROM branches b WHERE b.organization_id = o.id AND b.is_default = 1) <> 1""",
    "legacy_owners_on_nondefault_branches": """SELECT count(*) FROM branches b
        JOIN memberships l ON l.business_id = b.id AND l.role = 'OWNER' WHERE b.is_default <> 1""",
    "legacy_owner_drift": """SELECT count(*) FROM branches b
        JOIN memberships l ON l.business_id = b.id AND l.role = 'OWNER'
        WHERE b.is_default = 1 AND NOT EXISTS (
            SELECT 1 FROM organization_memberships m WHERE m.organization_id = b.organization_id
            AND m.user_id = l.user_id AND m.role = 'OWNER')""",
    "organization_owner_drift": """SELECT count(*) FROM organization_memberships m
        WHERE m.role = 'OWNER' AND NOT EXISTS (
            SELECT 1 FROM branches b JOIN memberships l ON l.business_id = b.id
            WHERE b.organization_id = m.organization_id AND b.is_default = 1
              AND l.user_id = m.user_id AND l.role = 'OWNER')""",
    "organizations_without_effective_owner": """SELECT count(*) FROM organizations o WHERE NOT EXISTS (
        SELECT 1 FROM branches b JOIN memberships l ON l.business_id = b.id AND l.role = 'OWNER'
        JOIN organization_memberships m ON m.organization_id = b.organization_id
             AND m.user_id = l.user_id AND m.role = 'OWNER'
        WHERE b.organization_id = o.id AND b.is_default = 1)""",
    "orphaned_assignments": """SELECT count(*) FROM branch_assignments a
        LEFT JOIN branches b ON b.id = a.branch_id
        LEFT JOIN organization_memberships m ON m.organization_id = a.organization_id AND m.user_id = a.user_id
        LEFT JOIN users u ON u.id = a.user_id
        WHERE b.id IS NULL OR m.user_id IS NULL OR u.id IS NULL""",
    "cross_organization_assignments": """SELECT count(*) FROM branch_assignments a
        JOIN branches b ON b.id = a.branch_id WHERE b.organization_id <> a.organization_id""",
    "nonstaff_assignments": """SELECT count(*) FROM branch_assignments a
        JOIN organization_memberships m ON m.organization_id = a.organization_id AND m.user_id = a.user_id
        WHERE m.role <> 'MEMBER' OR a.role NOT IN ('MANAGER', 'CASHIER', 'ACCOUNTANT')""",
}


def verify_tenant_readiness(snapshot):
    with closing(_open_snapshot(snapshot)) as db:
        try:
            ready_schema = has_scope_schema(db)
        except PermissionError:
            ready_schema = False
        counts = {"businesses": db.execute("SELECT count(*) FROM businesses").fetchone()[0]}
        if not ready_schema:
            return {"schema_ready": False, "counts": counts, "passed": False}
        for table in ("branches", "organizations", "branch_assignments"):
            counts[table] = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        issues = {name: db.execute(query).fetchone()[0] for name, query in CHECKS.items()}
        issues["foreign_key_violations"] = len(db.execute("PRAGMA foreign_key_check").fetchall())
        integrity = db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        return {"schema_ready": True, "counts": counts, "issues": issues,
                "sqlite_integrity": integrity, "passed": integrity and not any(issues.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    try:
        result = verify_tenant_readiness(args.snapshot)
    except (OSError, sqlite3.Error, ValueError):
        parser.exit(1, "Readiness verification failed: unreadable or incompatible snapshot.\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
