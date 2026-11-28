"""Explicit version-three SQLite migration for append-only staff permission audit."""

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path


AUDIT_STATEMENTS = (
    """CREATE TABLE staff_permission_audit (
        id INTEGER PRIMARY KEY,
        actor_user_id TEXT NOT NULL REFERENCES users(id),
        organization_id TEXT NOT NULL REFERENCES organizations(id),
        affected_user_id TEXT REFERENCES users(id),
        branch_id TEXT,
        action TEXT NOT NULL CHECK(action IN (
            'assigned', 'role_changed', 'assignment_revoked', 'membership_revoked', 'reassigned'
        )),
        outcome TEXT NOT NULL CHECK(outcome IN ('allowed', 'denied')),
        previous_role TEXT CHECK(previous_role IN ('MANAGER', 'CASHIER', 'ACCOUNTANT')),
        resulting_role TEXT CHECK(resulting_role IN ('MANAGER', 'CASHIER', 'ACCOUNTANT')),
        created_at INTEGER NOT NULL,
        FOREIGN KEY(organization_id, branch_id) REFERENCES branches(organization_id, id),
        CHECK ((outcome = 'allowed' AND affected_user_id IS NOT NULL)
            OR (outcome = 'denied' AND affected_user_id IS NULL AND branch_id IS NULL
                AND previous_role IS NULL AND resulting_role IS NULL))
    )""",
    """CREATE TRIGGER staff_permission_audit_no_update BEFORE UPDATE ON staff_permission_audit
       BEGIN SELECT RAISE(ABORT, 'Staff permission audit is immutable'); END""",
    """CREATE TRIGGER staff_permission_audit_no_delete BEFORE DELETE ON staff_permission_audit
       BEGIN SELECT RAISE(ABORT, 'Staff permission audit is immutable'); END""",
    """CREATE TRIGGER staff_permission_audit_no_replace BEFORE INSERT ON staff_permission_audit
       WHEN EXISTS (SELECT 1 FROM staff_permission_audit WHERE id = NEW.id)
       BEGIN SELECT RAISE(ABORT, 'Staff permission audit is immutable'); END""",
)

PREREQUISITES = {"kudiledger_schema_versions", "users", "organizations", "branches",
                 "organization_memberships", "branch_assignments", "staff_invitations",
                 "staff_invitation_branches", "staff_invitation_audit"}


def migrate_staff_permissions(database, *, dry_run=False):
    path = Path(database).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)) as db, db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("BEGIN IMMEDIATE")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")}
        if not PREREQUISITES <= tables:
            raise ValueError("Apply the explicit staff invitation migration first")
        versions = [row[0] for row in db.execute("SELECT version FROM kudiledger_schema_versions ORDER BY version")]
        if versions not in ([1, 2], [1, 2, 3]) or db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Unexpected schema version or foreign key violations")
        applied = versions == [1, 2]
        if applied:
            for statement in AUDIT_STATEMENTS:
                db.execute(statement)
            db.execute("INSERT INTO kudiledger_schema_versions(version) VALUES (3)")
        elif "staff_permission_audit" not in tables:
            raise ValueError("Incomplete staff permission schema")
        if dry_run:
            db.rollback()
    return {"version": 3, "applied": applied and not dry_run, "dry_run": dry_run}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(migrate_staff_permissions(args.database, dry_run=args.dry_run)))
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.exit(1, f"Migration failed: {error}\n")


if __name__ == "__main__":
    main()
