import json
import logging
import sqlite3
import time

from app.services.staff_management import StaffManagementLedger


LOGGER = logging.getLogger("kudiledger.operations")
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False


def event(name, **fields):
    LOGGER.info(json.dumps({"event": name, **fields}, separators=(",", ":")))


class StagingLedger(StaffManagementLedger):
    def initialize(self):
        super().initialize()
        with self.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS failed_write_windows (
                    minute INTEGER PRIMARY KEY,
                    count INTEGER NOT NULL
                )
            """)

    def note_failed_write(self):
        now = int(time.time()) // 60
        try:
            with self._using_connection(immediate=True) as db:
                db.execute("DELETE FROM failed_write_windows WHERE minute < ?", (now - 1440,))
                db.execute(
                    """INSERT INTO failed_write_windows (minute, count) VALUES (?, 1)
                       ON CONFLICT(minute) DO UPDATE SET count = count + 1""", (now,),
                )
        except sqlite3.Error:
            event("write_metric_unavailable")

def operational_counts(db):
    now = int(time.time()) // 60
    failed = db.execute(
        "SELECT coalesce(sum(count), 0) FROM failed_write_windows WHERE minute > ?",
        (now - 15,),
    ).fetchone()[0]
    unresolved = db.execute(
        """SELECT count(*) FROM recovery_attempts
           WHERE stage IN ('sending', 'saved', 'conflict')
           AND created_at <= datetime('now', '-30 minutes')"""
    ).fetchone()[0]
    mail_failed = db.execute(
        """SELECT count(*) FROM account_security_audit
           WHERE event = 'account_link_delivery_failed' AND created_at > ?""",
        (int(time.time()) - 900,),
    ).fetchone()[0]
    return {"failed_financial_writes_15m": failed, "unresolved_over_30m": unresolved,
            "account_mail_failures_15m": mail_failed}
