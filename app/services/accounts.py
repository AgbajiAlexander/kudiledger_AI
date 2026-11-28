import hashlib
import hmac
import secrets
import sqlite3
import time
from contextlib import contextmanager
from uuid import uuid4

from app.db.repayments import RepaymentLedger
from app.services.authorization import (
    LegacyScope, active_user, has_scope_schema, legacy_owner, organization_owner, owned_organizations,
)


class AccountLedger(RepaymentLedger):
    """Local identity and business-scoped ledger operations."""

    # Future rollout must explicitly opt out of unmapped legacy fallback.
    legacy_scope = LegacyScope.COMPATIBILITY

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

    def _create_user(self, db, email, password):
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
        db.execute(
            "INSERT INTO users (id, email, password_hash, password_salt) VALUES (?, ?, ?, ?)",
            (user_id, email, encoded, salt.hex()),
        )
        return user_id

    def register_owner(self, business_name, email, password, *, _db=None):
        if not isinstance(business_name, str) or not business_name.strip():
            raise ValueError("Business name required")

        if not isinstance(email, str):
            raise ValueError("Valid email required")

        email = self.normalize_email(email)
        business_id = str(uuid4())

        with self._using_connection(_db, immediate=True) as db:
            if self.legacy_scope is not LegacyScope.COMPATIBILITY and (
                self.legacy_scope is not LegacyScope.MAPPED_ONLY or not has_scope_schema(db)
            ):
                raise PermissionError("Tenant provisioning unavailable")
            try:
                db.execute(
                    "INSERT INTO businesses (id, name) VALUES (?, ?)",
                    (business_id, business_name.strip()),
                )

                user_id = self._create_user(db, email, password)

                db.execute(
                    """INSERT INTO memberships
                       (user_id, business_id, role)
                       VALUES (?, ?, 'OWNER')""",
                    (user_id, business_id),
                )
                if self.legacy_scope is LegacyScope.MAPPED_ONLY:
                    organization_id = str(uuid4())
                    db.execute("INSERT INTO organizations (id, name) VALUES (?, ?)",
                               (organization_id, business_name.strip()))
                    db.execute("INSERT INTO branches (id, organization_id, is_default) VALUES (?, ?, 1)",
                               (business_id, organization_id))
                    db.execute(
                        "INSERT INTO organization_memberships (organization_id, user_id, role) VALUES (?, ?, 'OWNER')",
                        (organization_id, user_id),
                    )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    "Account could not be registered"
                ) from error

        return {"user_id": user_id, "business_id": business_id}

    def create_business(self, name):
        if self.legacy_scope is not LegacyScope.COMPATIBILITY:
            raise PermissionError("Mapped businesses must be provisioned with an owner")
        return super().create_business(name)

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

    @contextmanager
    def _authorized_read(self, token, business_id):
        with self.connect() as db:
            db.execute("BEGIN")
            self._authorize(token, business_id, _db=db)
            yield db

    def _membership(self, token, business_id, *, _db=None):
        with self._using_connection(_db) as db:
            if _db is None:
                db.execute("BEGIN")
            return legacy_owner(db, active_user(db, token), business_id, scope=self.legacy_scope)

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
        with self._using_connection(immediate=True) as db:
            self._authorize(token, business_id, _db=db)
            return super().create_customer(business_id, name, _db=db)

    def add_sale(
        self, token, business_id, customer_id,
        reference, total, paid, confirmed=False, *, _db=None
    ):
        with self._using_connection(_db, immediate=True) as db:
            self._authorize(token, business_id, _db=db)
            return super().record_sale(
                business_id, customer_id, reference, total, paid, confirmed=confirmed, _db=db
            )

    def add_repayment(
        self, token, business_id, customer_id,
        reference, amount, confirmed=False, *, _db=None
    ):
        with self._using_connection(_db, immediate=True) as db:
            self._authorize(token, business_id, _db=db)
            return super().record_repayment(
                business_id, customer_id, reference, amount, confirmed=confirmed, _db=db
            )

    def get_balance(self, token, business_id, customer_id):
        with self._authorized_read(token, business_id) as db:
            return super().customer_balance(business_id, customer_id, _db=db)

    def get_repayments(self, token, business_id, customer_id):
        with self._authorized_read(token, business_id) as db:
            return super().list_repayments(business_id, customer_id, _db=db)

    def list_my_businesses(self, token):
        """Return businesses belonging to an active session."""
        with self.connect() as db:
            db.execute("BEGIN")
            user_id = active_user(db, token)
            rows = db.execute(
                """SELECT b.id, b.name, m.role, m.user_id
                   FROM memberships m
                   JOIN businesses b ON b.id = m.business_id
                   WHERE m.user_id = ? AND m.role = 'OWNER'
                   ORDER BY b.name COLLATE NOCASE, b.id""",
                (user_id,),
            ).fetchall()
            businesses = []
            for row in rows:
                try:
                    legacy_owner(db, user_id, row["id"], scope=self.legacy_scope)
                except PermissionError:
                    continue
                businesses.append({"id": row["id"], "name": row["name"],
                                   "role": row["role"], "account_id": row["user_id"]})
            return businesses

    def list_my_organizations(self, token):
        with self.connect() as db:
            db.execute("BEGIN")
            return [dict(row) for row in owned_organizations(db, active_user(db, token))]

    def list_organization_branches(self, token, organization_id):
        with self.connect() as db:
            db.execute("BEGIN")
            organization_owner(db, active_user(db, token), organization_id)
            return [dict(row) for row in db.execute(
                """SELECT b.id, ledger.name, b.is_default FROM branches b JOIN businesses ledger
                   ON ledger.id = b.id WHERE b.organization_id = ?
                   ORDER BY b.is_default DESC, ledger.name, b.id""", (organization_id,),
            )]

