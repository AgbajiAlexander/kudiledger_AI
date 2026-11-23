import hashlib
import hmac
import secrets
import sqlite3
import time
from uuid import uuid4

from app.db.repayments import RepaymentLedger


class AccountLedger(RepaymentLedger):
    """Local identity and business-scoped ledger operations."""

    def initialize(self):
        super().initialize()

        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    created_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS memberships (
                    user_id TEXT NOT NULL,
                    business_id TEXT NOT NULL,
                    role TEXT NOT NULL
                        CHECK(role IN ('OWNER')),
                    PRIMARY KEY (user_id, business_id),
                    FOREIGN KEY(user_id) REFERENCES users(id),
                    FOREIGN KEY(business_id)
                        REFERENCES businesses(id)
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE INDEX IF NOT EXISTS
                    idx_sessions_user ON sessions(user_id);
            """)

    @staticmethod
    def _hash_password(password, salt):
        return hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=16384,
            r=8,
            p=1,
            dklen=32,
        ).hex()

    @staticmethod
    def normalize_email(email):
        email = email.strip().casefold()
        if (len(email) > 254 or email.count("@") != 1
                or not all(email.split("@")) or any(c.isspace() for c in email)):
            raise ValueError("Valid email required")
        return email

    def register_owner(self, business_name, email, password, *, _db=None):
        if not isinstance(business_name, str) or not business_name.strip():
            raise ValueError("Business name required")

        if not isinstance(email, str):
            raise ValueError("Valid email required")

        email = self.normalize_email(email)

        if (
            not isinstance(password, str)
            or len(password) < 12
            or len(password) > 1024
        ):
            raise ValueError(
                "Password must contain 12 to 1024 characters"
            )

        salt = secrets.token_bytes(16)
        encoded = self._hash_password(password, salt)

        user_id = str(uuid4())
        business_id = str(uuid4())

        with self._using_connection(_db) as db:
            try:
                db.execute(
                    "INSERT INTO businesses (id, name) VALUES (?, ?)",
                    (business_id, business_name.strip()),
                )

                db.execute(
                    """INSERT INTO users
                       (id, email, password_hash, password_salt)
                       VALUES (?, ?, ?, ?)""",
                    (user_id, email, encoded, salt.hex()),
                )

                db.execute(
                    """INSERT INTO memberships
                       (user_id, business_id, role)
                       VALUES (?, ?, 'OWNER')""",
                    (user_id, business_id),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    "Account could not be registered"
                ) from error

        return {"user_id": user_id, "business_id": business_id}

    def login(self, email, password):
        if not isinstance(email, str) or not isinstance(password, str):
            raise ValueError("Invalid credentials")

        normalized = email.strip().casefold()

        with self.connect() as db:
            user = db.execute(
                "SELECT * FROM users WHERE email = ?",
                (normalized,),
            ).fetchone()

            candidate = self._hash_password(
                password,
                bytes.fromhex(user["password_salt"]) if user else b"\0" * 16,
            )

            if user is None or not hmac.compare_digest(
                candidate, user["password_hash"]
            ):
                raise ValueError("Invalid credentials")

            token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(
                token.encode("utf-8")
            ).hexdigest()

            expires = int(time.time()) + 12 * 60 * 60

            issued = db.execute(
                """INSERT INTO sessions
                   (token_hash, user_id, expires_at)
                   SELECT ?, id, ? FROM users
                   WHERE id = ? AND password_hash = ?""",
                (token_hash, expires, user["id"], user["password_hash"]),
            )
            if issued.rowcount != 1:
                raise ValueError("Invalid credentials")

        return token

    def _authorize(self, token, business_id, *, _db=None):
        return self._membership(token, business_id, _db=_db)["role"]

    def _membership(self, token, business_id, *, _db=None):
        if not isinstance(token, str) or not token:
            raise PermissionError("Authentication required")

        token_hash = hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()

        with self._using_connection(_db) as db:
            row = db.execute(
                """SELECT m.role, m.user_id FROM sessions s
                   JOIN memberships m
                     ON m.user_id = s.user_id
                   WHERE s.token_hash = ?
                     AND s.expires_at > ?
                     AND m.business_id = ?""",
                (token_hash, int(time.time()), business_id),
            ).fetchone()

        if row is None:
            raise PermissionError(
                "Access denied for this business"
            )

        return row

    def is_active_session(self, token):
        """Check that a login token exists and has not expired."""
        if not isinstance(token, str) or not token:
            return False

        if len(token) > 256:
            return False

        token_hash = hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()

        with self.connect() as db:
            row = db.execute(
                """SELECT 1 FROM sessions s
                   JOIN users u ON u.id = s.user_id
                   WHERE s.token_hash = ?
                     AND s.expires_at > ?""",
                (token_hash, int(time.time())),
            ).fetchone()

        return row is not None

    def logout(self, token):
        if not isinstance(token, str) or not token:
            return

        token_hash = hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()

        with self.connect() as db:
            db.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (token_hash,),
            )

    def add_customer(self, token, business_id, name):
        self._authorize(token, business_id)
        return super().create_customer(business_id, name)

    def add_sale(
        self, token, business_id, customer_id,
        reference, total, paid, confirmed=False, *, _db=None
    ):
        self._authorize(token, business_id, _db=_db)

        return super().record_sale(
            business_id, customer_id, reference,
            total, paid, confirmed=confirmed, _db=_db
        )

    def add_repayment(
        self, token, business_id, customer_id,
        reference, amount, confirmed=False, *, _db=None
    ):
        self._authorize(token, business_id, _db=_db)

        return super().record_repayment(
            business_id, customer_id, reference,
            amount, confirmed=confirmed, _db=_db
        )

    def get_balance(self, token, business_id, customer_id):
        self._authorize(token, business_id)

        return super().customer_balance(
            business_id, customer_id
        )

    def get_repayments(self, token, business_id, customer_id):
        self._authorize(token, business_id)

        return super().list_repayments(
            business_id, customer_id
        )

    def list_my_businesses(self, token):
        """Return businesses belonging to an active session."""
        if not self.is_active_session(token):
            raise PermissionError("Authentication required")

        token_hash = hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()

        with self.connect() as db:
            rows = db.execute(
                """SELECT b.id, b.name, m.role
                   FROM sessions s
                   JOIN memberships m ON m.user_id = s.user_id
                   JOIN businesses b ON b.id = m.business_id
                   WHERE s.token_hash = ?
                     AND s.expires_at > ?
                   ORDER BY b.name COLLATE NOCASE, b.id""",
                (token_hash, int(time.time())),
            ).fetchall()

        return [
            {
                "id": row["id"],
                "name": row["name"],
                "role": row["role"],
            }
            for row in rows
        ]

