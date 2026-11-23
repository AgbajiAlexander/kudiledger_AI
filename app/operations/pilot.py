"""Local SQLite commissioning tools for the synthetic pilot."""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from app.services.operators import PilotLedger


REPOSITORY = Path(__file__).resolve().parents[2]
PILOT_TABLES = (
    "businesses", "customers", "sales", "repayments", "expenses",
    "sale_reversals", "debt_adjustments", "recovery_attempts",
    "recovery_operators", "recovery_operator_audit",
)


def _read_only(path):
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)


def _digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _validate(path):
    with closing(_read_only(path)) as db:
        results = db.execute("PRAGMA integrity_check").fetchall()
        if results != [("ok",)] or db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("SQLite integrity or foreign key check failed")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not set(PILOT_TABLES).issubset(tables) or "sessions" not in tables:
            raise ValueError("The file is missing required pilot tables")
        # Table names come from the fixed list above.
        return {table: db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                for table in PILOT_TABLES}


def verify_database(path):
    file = Path(path).resolve(strict=True)
    return {"counts": _validate(file), "sha256": _digest(file)}


def _destination(path):
    target = Path(path).resolve()
    if target.is_relative_to(REPOSITORY):
        raise ValueError("Use a backup or restore destination outside the repository")
    if target.exists():
        raise FileExistsError("The backup or restore destination already exists")
    if not target.parent.is_dir():
        raise ValueError("The destination directory must already exist")
    return target


def _publish(target, write):
    fd, name = tempfile.mkstemp(prefix=".kudiledger-", suffix=".sqlite", dir=target.parent)
    os.close(fd)
    staged = Path(name)
    try:
        write(staged)
        # Publish a standalone snapshot even when the source database uses WAL.
        with closing(sqlite3.connect(staged)) as db:
            db.execute("PRAGMA journal_mode = DELETE").fetchone()
        result = verify_database(staged)
        with staged.open("r+b") as file:
            os.fsync(file.fileno())
        # Publish a complete file and fail if another process created the target.
        os.link(staged, target)
        return result
    finally:
        staged.unlink(missing_ok=True)


def backup_database(source, destination):
    source = Path(source).resolve(strict=True)
    target = _destination(destination)

    def snapshot(staged):
        with closing(_read_only(source)) as original, closing(sqlite3.connect(staged)) as copy:
            original.backup(copy, pages=128)

    return _publish(target, snapshot)


def restore_database(backup, destination, expected_sha256):
    backup = Path(backup).resolve(strict=True)
    target = _destination(destination)

    def restore_copy(staged):
        shutil.copyfile(backup, staged)
        if _digest(staged) != expected_sha256.strip().lower():
            raise ValueError("Backup checksum does not match")
        _validate(staged)
        with closing(sqlite3.connect(staged)) as db, db:
            # Restored credentials remain usable for a new sign-in.
            db.execute("DELETE FROM sessions")
            if db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'account_links'").fetchone():
                db.execute("DELETE FROM account_links")

    return _publish(target, restore_copy)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("backup", "restore"):
        command = commands.add_parser(name)
        command.add_argument("source")
        command.add_argument("destination")
        if name == "restore":
            command.add_argument("--sha256", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("source")
    for name in ("grant-operator", "revoke-operator"):
        command = commands.add_parser(name)
        command.add_argument("--database", required=True)
        command.add_argument("--business-id", required=True)
        command.add_argument("--email", required=True)

    args = parser.parse_args()
    try:
        if args.command == "backup":
            result = backup_database(args.source, args.destination)
        elif args.command == "restore":
            result = restore_database(args.source, args.destination, args.sha256)
        elif args.command == "verify":
            result = verify_database(args.source)
        else:
            database = Path(args.database).resolve(strict=True)
            PilotLedger(database).set_recovery_operator(
                args.business_id, args.email, enabled=args.command == "grant-operator",
            )
            result = {"status": args.command}
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, str(error) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
