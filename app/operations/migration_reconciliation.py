"""Compare standalone pre/post KLD-007B snapshots and emit only redacted evidence."""

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from app.db.migrations import VERSION, _legacy_scope, _verify_mapping


FINANCIAL = {
    "sales": ("sale_reference", ("total_kobo", "paid_kobo")),
    "repayments": ("repayment_reference", ("amount_kobo",)),
    "expenses": ("expense_reference", ("amount_kobo",)),
    "debt_adjustments": ("adjustment_reference", ("delta_kobo",)),
    "sale_reversals": ("reversal_reference", ("amount_kobo",)),
}


def _open_snapshot(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file() or any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("Use a standalone snapshot from the SQLite backup tool")
    # Offline backup copies only. Immutable mode avoids touching journal sidecars.
    return sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)


def _schema(db):
    return {row[1]: row for row in db.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"
    )}


def _row_digest(db, table):
    identifier = '"' + table.replace('"', '""') + '"'
    digest = hashlib.sha256()
    for row in db.execute(f"SELECT * FROM {identifier} ORDER BY rowid"):
        # Compare values privately. Only the boolean comparison enters the report.
        for value in row:
            data = value if isinstance(value, bytes) else repr(value).encode("utf-8")
            digest.update(f"{type(value).__name__}:{len(data)}:".encode("ascii"))
            digest.update(data)
        digest.update(b"\n")
    return digest.digest()


def _metrics(db):
    financial = {}
    for table, (reference, columns) in FINANCIAL.items():
        count, refs = db.execute(
            f"SELECT (SELECT count(*) FROM {table}), count(*) FROM "
            f"(SELECT DISTINCT business_id, {reference} FROM {table})"
        ).fetchone()
        totals = dict.fromkeys(columns, 0)
        for row in db.execute(f"SELECT {', '.join(columns)} FROM {table}"):
            for column, amount in zip(columns, row):
                if type(amount) is not int:
                    raise ValueError("Expected exact integer kobo")
                totals[column] += amount
        financial[table] = {"records": count, "scoped_references": refs, "totals_kobo": totals}
    recovery = dict(db.execute("SELECT stage, count(*) FROM recovery_attempts GROUP BY stage ORDER BY stage"))
    if not recovery.keys() <= {"prepared", "sending", "saved", "verified", "rejected", "conflict"}:
        raise ValueError("Unexpected recovery status")
    return {
        "legacy_businesses": db.execute("SELECT count(*) FROM businesses").fetchone()[0],
        "financial": financial,
        "recovery": {"records": sum(recovery.values()), "by_stage": recovery},
        "audits": {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                   for table in ("account_security_audit", "recovery_operator_audit")},
    }


def _mapping_valid(db, versions):
    try:
        if versions != [VERSION]:
            return False
        _, owners = _legacy_scope(db)
        _verify_mapping(db, owners)
    except ValueError:
        return False
    return True


def reconcile(before, after):
    with closing(_open_snapshot(before)) as pre, closing(_open_snapshot(after)) as post:
        original, expanded = _schema(pre), _schema(post)
        tables = [name for name, row in original.items() if row[0] == "table"]
        versions = [row[0] for row in post.execute("SELECT version FROM kudiledger_schema_versions ORDER BY version")]
        pre_metrics, post_metrics = _metrics(pre), _metrics(post)
        invariants = {
            "pre_is_unmigrated": "kudiledger_schema_versions" not in original,
            "legacy_schema_unchanged": all(expanded.get(name) == row for name, row in original.items()),
            "legacy_rows_unchanged": all(name in expanded and _row_digest(pre, name) == _row_digest(post, name)
                                         for name in tables),
            "legacy_aggregates_unchanged": pre_metrics == post_metrics,
            "mapped_ownership_verified": _mapping_valid(post, versions),
            "sqlite_integrity_verified": all(db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
                                             and db.execute("PRAGMA foreign_key_check").fetchone() is None
                                             for db in (pre, post)),
        }
        return {
            "schema_versions": versions,
            "before": pre_metrics,
            "after": {**post_metrics, "mapped_branches": post.execute("SELECT count(*) FROM branches").fetchone()[0],
                      "organizations": post.execute("SELECT count(*) FROM organizations").fetchone()[0]},
            "invariants": invariants,
            "passed": all(invariants.values()),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args()
    try:
        result = reconcile(args.before, args.after)
    except (OSError, sqlite3.Error, ValueError):
        parser.exit(1, "Reconciliation failed: unreadable or incompatible snapshots.\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
