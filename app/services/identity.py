import hashlib
import secrets
import time

from app.services.operators import PilotLedger


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class IdentityLedger(PilotLedger):
    def initialize(self):
        super().initialize()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS account_links (
                    token_hash TEXT PRIMARY KEY,
                    purpose TEXT NOT NULL CHECK(purpose IN ('invite', 'reset')),
                    email TEXT NOT NULL,
                    business_name TEXT,
                    user_id TEXT REFERENCES users(id),
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS account_links_expiry ON account_links(expires_at);
                CREATE INDEX IF NOT EXISTS account_links_user ON account_links(user_id, purpose);
                CREATE TABLE IF NOT EXISTS auth_rate_windows (
                    bucket TEXT PRIMARY KEY,
                    expires_at INTEGER NOT NULL,
                    count INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS auth_rate_expiry ON auth_rate_windows(expires_at);
                CREATE TABLE IF NOT EXISTS account_security_audit (
                    id INTEGER PRIMARY KEY,
                    event TEXT NOT NULL,
                    user_id TEXT,
                    created_at INTEGER NOT NULL
                );
            """)

    @staticmethod
    def audit_account(db, event, user_id=None):
        db.execute(
            "INSERT INTO account_security_audit (event, user_id, created_at) VALUES (?, ?, ?)",
            (event, user_id, int(time.time())),
        )

    def allow_auth(self, operation, key, limit, window):
        now = int(time.time())
        bucket = digest(f"{operation}:{key}")
        with self._using_connection(immediate=True) as db:
            db.execute("DELETE FROM auth_rate_windows WHERE expires_at <= ?", (now,))
            row = db.execute(
                """INSERT INTO auth_rate_windows (bucket, expires_at, count)
                   VALUES (?, ?, 1) ON CONFLICT(bucket) DO UPDATE
                   SET count = min(count + 1, ?)
                   RETURNING count""",
                (bucket, now + window, limit + 1),
            ).fetchone()
            return row["count"] <= limit

    @staticmethod
    def _issue_link(db, purpose, email, ttl_seconds, *, business_name=None, user_id=None):
        token = secrets.token_urlsafe(32)
        expires = int(time.time()) + ttl_seconds
        db.execute("DELETE FROM account_links WHERE expires_at <= ?", (int(time.time()),))
        db.execute(
            """INSERT INTO account_links (token_hash, purpose, email, business_name, user_id, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (digest(token), purpose, email, business_name, user_id, expires),
        )
        return token

    def create_invite(self, email, business_name):
        email = self.normalize_email(email)
        business_name = business_name.strip()
        if not 1 <= len(business_name) <= 150:
            raise ValueError("Business name must contain 1 to 150 characters")
        with self._using_connection(immediate=True) as db:
            if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                raise ValueError("An account already exists for this address")
            token = self._issue_link(db, "invite", email, 24 * 3600, business_name=business_name)
            self.audit_account(db, "invite_issued")
        return token

    def confirm_invite_delivery(self, token):
        with self._using_connection(immediate=True) as db:
            delivered = db.execute(
                "SELECT rowid, email FROM account_links WHERE purpose = 'invite' AND token_hash = ?",
                (digest(token),),
            ).fetchone()
            if delivered:
                db.execute(
                    "DELETE FROM account_links WHERE purpose = 'invite' AND email = ? AND rowid < ?",
                    (delivered["email"], delivered["rowid"]),
                )

    def fail_account_link_delivery(self, purpose, token):
        with self._using_connection(immediate=True) as db:
            row = db.execute(
                "DELETE FROM account_links WHERE purpose = ? AND token_hash = ? RETURNING user_id",
                (purpose, digest(token)),
            ).fetchone()
            self.audit_account(db, "account_link_delivery_failed", row["user_id"] if row else None)

    def request_password_reset(self, email):
        try:
            email = self.normalize_email(email)
        except ValueError:
            return None
        with self._using_connection(immediate=True) as db:
            user = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if user is None:
                return None
            token = self._issue_link(db, "reset", email, 30 * 60, user_id=user["id"])
            self.audit_account(db, "reset_link_issued", user["id"])
        return token

    def consume_account_link(self, purpose, token, password):
        if not 12 <= len(password) <= 1024:
            raise ValueError("Password must contain 12 to 1024 characters")
        with self._using_connection(immediate=True) as db:
            row = db.execute(
                """DELETE FROM account_links
                   WHERE token_hash = ? AND purpose = ? AND expires_at > ?
                   RETURNING email, business_name, user_id""",
                (digest(token), purpose, int(time.time())),
            ).fetchone()
            if row is None:
                raise ValueError("This link is invalid or expired")
            if purpose == "invite":
                account = self.register_owner(
                    row["business_name"], row["email"], password, _db=db,
                )
                db.execute("DELETE FROM account_links WHERE purpose = 'invite' AND email = ?", (row["email"],))
                self.audit_account(db, "email_verified", account["user_id"])
            else:
                user_id = row["user_id"]
                salt = secrets.token_bytes(16)
                db.execute(
                    "UPDATE users SET password_hash = ?, password_salt = ? WHERE id = ?",
                    (self._hash_password(password, salt), salt.hex(), user_id),
                )
                db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
                db.execute("DELETE FROM account_links WHERE user_id = ? AND purpose = 'reset'", (user_id,))
                db.execute("DELETE FROM login_attempts WHERE identifier_hash = ?", (digest(row["email"]),))
                self.audit_account(db, "password_reset_sessions_revoked", user_id)
