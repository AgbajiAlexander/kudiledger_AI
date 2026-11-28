"""Explicit version-two SQLite migration for staff invitation metadata."""

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path


VERSION = 2
STATEMENTS = (
    """CREATE TABLE staff_invitations (
        id TEXT PRIMARY KEY NOT NULL,
        organization_id TEXT NOT NULL REFERENCES organizations(id),
        email TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        issuer_user_id TEXT NOT NULL REFERENCES users(id),
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL CHECK(expires_at > created_at),
        accepted_at INTEGER,
        accepted_user_id TEXT REFERENCES users(id),
        revoked_at INTEGER,
        UNIQUE (id, organization_id),
        CHECK ((accepted_at IS NULL) = (accepted_user_id IS NULL)),
        CHECK (accepted_at IS NULL OR revoked_at IS NULL)
    )""",
    """CREATE INDEX staff_invites_pending ON staff_invitations(organization_id, email, expires_at)
       WHERE accepted_at IS NULL AND revoked_at IS NULL""",
    """CREATE TABLE staff_invitation_branches (
        invitation_id TEXT NOT NULL,
        organization_id TEXT NOT NULL,
        branch_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('MANAGER', 'CASHIER', 'ACCOUNTANT')),
        PRIMARY KEY(invitation_id, branch_id),
        FOREIGN KEY(invitation_id, organization_id) REFERENCES staff_invitations(id, organization_id),
        FOREIGN KEY(organization_id, branch_id) REFERENCES branches(organization_id, id)
    )""",
    """CREATE TABLE staff_invitation_audit (
        id INTEGER PRIMARY KEY,
        invitation_id TEXT NOT NULL REFERENCES staff_invitations(id),
        actor_user_id TEXT REFERENCES users(id),
        event TEXT NOT NULL CHECK(event IN ('issued', 'accepted', 'revoked', 'delivery_failed', 'restore_revoked')),
        created_at INTEGER NOT NULL
    )""",
    """CREATE TRIGGER staff_audit_no_update BEFORE UPDATE ON staff_invitation_audit
       BEGIN SELECT RAISE(ABORT, 'Staff invitation audit is immutable'); END""",
    """CREATE TRIGGER staff_audit_no_delete BEFORE DELETE ON staff_invitation_audit
       BEGIN SELECT RAISE(ABORT, 'Staff invitation audit is immutable'); END""",
)


def migrate_staff_invitations(database, *, dry_run=False):
    path = Path(database).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)) as db, db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("BEGIN IMMEDIATE")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")}
        if not {"kudiledger_schema_versions", "users", "organizations", "branches",
                "organization_memberships", "branch_assignments"} <= tables:
            raise ValueError("Apply the explicit legacy mapping migration first")
        versions = [row[0] for row in db.execute("SELECT version FROM kudiledger_schema_versions ORDER BY version")]
        if versions not in ([1], [1, VERSION]) or db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Unexpected schema version or foreign key violations")
        applied = versions == [1]
        if applied:
            for statement in STATEMENTS:
                db.execute(statement)
            db.execute("INSERT INTO kudiledger_schema_versions(version) VALUES (?)", (VERSION,))
        elif not {"staff_invitations", "staff_invitation_branches", "staff_invitation_audit"} <= tables:
            raise ValueError("Incomplete staff invitation schema")
        if dry_run:
            db.rollback()
    return {"version": VERSION, "applied": applied and not dry_run, "dry_run": dry_run}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(migrate_staff_invitations(args.database, dry_run=args.dry_run)))
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.exit(1, f"Migration failed: {error}\n")


if __name__ == "__main__":
    main()
