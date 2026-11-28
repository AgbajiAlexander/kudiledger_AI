"""Explicit additive migrations for an existing KudiLedger SQLite database."""

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4


VERSION = 1
MIGRATION = (
    """CREATE TABLE organizations (
        id TEXT PRIMARY KEY NOT NULL,
        name TEXT NOT NULL CHECK(length(trim(name)) > 0)
    )""",
    """CREATE TABLE branches (
        id TEXT PRIMARY KEY NOT NULL REFERENCES businesses(id),
        organization_id TEXT NOT NULL REFERENCES organizations(id),
        is_default INTEGER NOT NULL CHECK(is_default IN (0, 1)),
        UNIQUE(organization_id, id)
    )""",
    """CREATE UNIQUE INDEX branches_one_default ON branches(organization_id)
       WHERE is_default = 1""",
    """CREATE TRIGGER branches_immutable_identity
       BEFORE UPDATE OF id, organization_id ON branches
       WHEN NEW.id <> OLD.id OR NEW.organization_id <> OLD.organization_id
       BEGIN SELECT RAISE(ABORT, 'Branch identity and ownership are immutable'); END""",
    """CREATE TABLE organization_memberships (
        organization_id TEXT NOT NULL REFERENCES organizations(id),
        user_id TEXT NOT NULL REFERENCES users(id),
        role TEXT NOT NULL CHECK(role IN ('OWNER', 'MEMBER')),
        PRIMARY KEY(organization_id, user_id)
    )""",
    """CREATE TABLE branch_assignments (
        organization_id TEXT NOT NULL,
        branch_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('MANAGER', 'CASHIER', 'ACCOUNTANT')),
        PRIMARY KEY(organization_id, branch_id, user_id),
        FOREIGN KEY(organization_id, branch_id) REFERENCES branches(organization_id, id),
        FOREIGN KEY(organization_id, user_id)
            REFERENCES organization_memberships(organization_id, user_id)
    )""",
)


def _legacy_scope(db):
    businesses = dict(db.execute("SELECT id, name FROM businesses"))
    owners = {business_id: set() for business_id in businesses}
    for business_id, user_id in db.execute("SELECT business_id, user_id FROM memberships WHERE role = 'OWNER'"):
        owners[business_id].add(user_id)
    if any(not users for users in owners.values()):
        raise ValueError("Resolve legacy businesses without an owner before migration")
    return businesses, owners


def _verify_mapping(db, owners):
    seen = set()
    for branch_id, organization_id, is_default in db.execute(
        "SELECT id, organization_id, is_default FROM branches"
    ):
        if (branch_id not in owners or organization_id in owners or not is_default
                or organization_id in seen):
            raise ValueError("Legacy organization and branch mappings conflict")
        expected = {(user_id, "OWNER") for user_id in owners[branch_id]}
        actual = set(db.execute(
            "SELECT user_id, role FROM organization_memberships WHERE organization_id = ?",
            (organization_id,),
        ))
        if actual != expected:
            raise ValueError("Mapped owners do not match legacy ownership")
        seen.add(organization_id)
    if (len(seen) != len(owners) or db.execute("SELECT count(*) FROM organizations").fetchone()[0] != len(seen)
            or db.execute("SELECT 1 FROM branch_assignments LIMIT 1").fetchone()):
        raise ValueError("Migration requires one complete default branch and no staff grants per legacy business")


def migrate_legacy_database(database, *, dry_run=False):
    """Expand and verify legacy mappings under one SQLite writer transaction."""
    path = Path(database).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)) as db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("BEGIN IMMEDIATE")
        try:
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Legacy database has foreign key violations")
            businesses, owners = _legacy_scope(db)
            db.execute("""CREATE TABLE IF NOT EXISTS kudiledger_schema_versions (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            versions = list(db.execute("SELECT version FROM kudiledger_schema_versions ORDER BY version"))
            if versions not in ([], [(VERSION,)]):
                raise ValueError("Unsupported KudiLedger schema version")
            if not versions:
                for statement in MIGRATION:
                    db.execute(statement)
                db.execute("INSERT INTO kudiledger_schema_versions(version) VALUES (?)", (VERSION,))

            mapped = {row[0] for row in db.execute("SELECT id FROM branches")}
            new_branches = businesses.keys() - mapped
            # Legacy owner provisioning can add a business while compatibility mode is active.
            for branch_id in sorted(new_branches):
                organization_id = str(uuid4())
                db.execute("INSERT INTO organizations (id, name) VALUES (?, ?)", (organization_id, businesses[branch_id]))
                db.execute("INSERT INTO branches (id, organization_id, is_default) VALUES (?, ?, 1)",
                           (branch_id, organization_id))
                db.executemany(
                    "INSERT INTO organization_memberships (organization_id, user_id, role) VALUES (?, ?, 'OWNER')",
                    ((organization_id, user_id) for user_id in owners[branch_id]),
                )
            _verify_mapping(db, owners)
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Migrated database has foreign key violations")
            if dry_run:
                db.rollback()
            else:
                db.commit()
        except BaseException:
            db.rollback()
            raise
    return {"version": VERSION, "legacy_branches": len(businesses),
            "new_mappings": len(new_branches), "dry_run": dry_run}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="Verify inside a transaction and roll it back")
    args = parser.parse_args()
    try:
        print(json.dumps(migrate_legacy_database(args.database, dry_run=args.dry_run)))
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.exit(1, f"Migration failed: {error}\n")


if __name__ == "__main__":
    main()
