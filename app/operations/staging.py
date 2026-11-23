import argparse
import json
import os
import sqlite3
import ssl
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, build_opener
from uuid import uuid4

from app.operations.pilot import backup_database
from app.services.account_mail import AccountMail, private_path
from app.services.telemetry import StagingLedger, operational_counts


def invite(database, email, business, mail):
    email = StagingLedger.normalize_email(email)
    if not mail.permits(email):
        raise ValueError("Email delivery is disabled for this recipient")
    ledger = StagingLedger(Path(database).resolve(strict=True))
    token = ledger.create_invite(email, business)
    try:
        mail.send("invite", email, token)
    except Exception:
        ledger.fail_account_link_delivery("invite", token)
        raise RuntimeError("Invitation delivery failed") from None
    ledger.confirm_invite_delivery(token)


class RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        return None


def check_health(origin, ca_file=None):
    if urlsplit(origin).scheme != "https":
        return False
    try:
        context = ssl.create_default_context(cafile=ca_file)
        opener = build_opener(HTTPSHandler(context=context), RejectRedirects())
        with opener.open(origin.rstrip("/") + "/health", timeout=5) as response:
            return response.status == 200 and json.loads(response.read(4096)).get("status") == "ok"
    except (OSError, ValueError, AttributeError):
        return False


def monitor(database, origin, ca_file=None):
    healthy = check_health(origin, ca_file)
    alerts = [] if healthy else ["availability"]
    counts = {}
    try:
        source = Path(database).resolve(strict=True)
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as db:
            counts = operational_counts(db)
    except (OSError, sqlite3.Error):
        alerts.append("metrics_unavailable")
    if counts.get("failed_financial_writes_15m", 0) >= 3:
        alerts.append("failed_financial_writes")
    if counts.get("unresolved_over_30m", 0) >= 1:
        alerts.append("old_unresolved_recovery")
    if counts.get("account_mail_failures_15m", 0) >= 1:
        alerts.append("account_mail_delivery")
    return {"event": "pilot_monitor", "available": healthy, **counts, "alerts": alerts}


def scheduled_backup(database, directory):
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = private_path(directory) / f"snapshot-{timestamp}-{uuid4().hex[:8]}.sqlite"
    result = backup_database(database, filename)
    with os.fdopen(os.open(filename.with_suffix(".sha256"),
                          os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="ascii") as file:
        file.write(result["sha256"] + "\n")
    return {"event": "pilot_backup", "file": filename.name, **result}


def main():
    parser = argparse.ArgumentParser(description="Supervised staging operations")
    commands = parser.add_subparsers(dest="command", required=True)
    invitation = commands.add_parser("invite")
    invitation.add_argument("--email", required=True)
    invitation.add_argument("--business", required=True)
    monitoring = commands.add_parser("monitor")
    monitoring.add_argument("--ca-file")
    commands.add_parser("scheduled-backup")
    args = parser.parse_args()
    try:
        database = os.environ["KUDILEDGER_DB"]
        if args.command == "invite":
            invite(database, args.email, args.business, AccountMail.from_environment())
            result = {"event": "pilot_invite_dispatched"}
        elif args.command == "monitor":
            result = monitor(database, os.environ["KUDILEDGER_PUBLIC_ORIGIN"], args.ca_file)
        else:
            result = scheduled_backup(database, os.environ["KUDILEDGER_BACKUP_DIR"])
    except Exception:
        # SMTP, SQLite and I/O errors may contain user data or private paths.
        print(json.dumps({"event": "pilot_operation_failed", "operation": args.command}))
        raise SystemExit(1) from None
    print(json.dumps(result))
    if result.get("alerts"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
