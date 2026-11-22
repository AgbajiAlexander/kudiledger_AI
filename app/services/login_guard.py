import hashlib
import time


class LoginGuard:
    """Persistent, local prototype login-attempt limiter."""

    MAX_FAILURES = 5
    WINDOW_SECONDS = 15 * 60

    def __init__(self, ledger):
        self.ledger = ledger
        with self.ledger.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS login_attempts (
                    identifier_hash TEXT PRIMARY KEY,
                    failures INTEGER NOT NULL,
                    window_start INTEGER NOT NULL,
                    locked_until INTEGER NOT NULL DEFAULT 0
                )
            """)

    @staticmethod
    def _key(email):
        normalized = email.strip().casefold()
        return hashlib.sha256(
            normalized.encode("utf-8")
        ).hexdigest()

    def allowed(self, email):
        key = self._key(email)
        now = int(time.time())

        with self.ledger.connect() as db:
            row = db.execute(
                """SELECT failures, window_start, locked_until
                   FROM login_attempts
                   WHERE identifier_hash = ?""",
                (key,),
            ).fetchone()

        if row is None:
            return True

        if row["locked_until"] > now:
            return False

        return True

    def failed(self, email):
        key = self._key(email)
        now = int(time.time())

        with self.ledger.connect() as db:
            db.execute("BEGIN IMMEDIATE")

            row = db.execute(
                """SELECT failures, window_start, locked_until
                   FROM login_attempts
                   WHERE identifier_hash = ?""",
                (key,),
            ).fetchone()

            if row and row["locked_until"] > now:
                return

            if (
                row is None
                or now - row["window_start"] >= self.WINDOW_SECONDS
            ):
                failures = 1
                start = now
            else:
                failures = row["failures"] + 1
                start = row["window_start"]

            locked_until = (
                now + self.WINDOW_SECONDS
                if failures >= self.MAX_FAILURES
                else 0
            )

            db.execute(
                """INSERT INTO login_attempts
                   (identifier_hash, failures,
                    window_start, locked_until)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(identifier_hash)
                   DO UPDATE SET
                     failures = excluded.failures,
                     window_start = excluded.window_start,
                     locked_until = excluded.locked_until""",
                (key, failures, start, locked_until),
            )

    def succeeded(self, email):
        key = self._key(email)

        with self.ledger.connect() as db:
            db.execute(
                """DELETE FROM login_attempts
                   WHERE identifier_hash = ?""",
                (key,),
            )
