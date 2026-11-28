"""Scoped staff invitation lifecycle with no financial authorization entry point."""

import secrets
import time
from uuid import uuid4

from app.services.authorization import active_user, organization_owner
from app.services.identity import IdentityLedger, digest


STAFF_ROLES = frozenset({"MANAGER", "CASHIER", "ACCOUNTANT"})
INVITATION_TTL = 24 * 3600


def _require_staff_schema(db):
    tables = {row[0] for row in db.execute(
        """SELECT name FROM sqlite_schema WHERE type = 'table' AND name IN
           ('kudiledger_schema_versions', 'staff_invitations',
            'staff_invitation_branches', 'staff_invitation_audit')"""
    )}
    if len(tables) != 4 or not db.execute(
        "SELECT 1 FROM kudiledger_schema_versions WHERE version = 2"
    ).fetchone():
        raise PermissionError("Staff invitation schema unavailable")


def _validate_grants(db, organization_id, grants):
    if not grants or len(grants) > 50 or len({branch for branch, _ in grants}) != len(grants):
        raise ValueError("Select one to 50 distinct branches")
    for branch, role in grants:
        if role not in STAFF_ROLES or not db.execute(
            "SELECT 1 FROM branches WHERE id = ? AND organization_id = ?", (branch, organization_id),
        ).fetchone():
            raise ValueError("Invalid branch or staff role")


def _check_existing_grants(db, organization_id, user_id, grants):
    if db.execute(
        "SELECT 1 FROM organization_memberships WHERE organization_id = ? AND user_id = ? AND role = 'OWNER'",
        (organization_id, user_id),
    ).fetchone():
        raise ValueError("Staff invitations cannot modify organization owners")
    assigned = {row[0] for row in db.execute(
        "SELECT branch_id FROM branch_assignments WHERE organization_id = ? AND user_id = ?",
        (organization_id, user_id),
    )}
    if any(branch in assigned for branch, _ in grants):
        raise ValueError("An assignment already exists for a selected branch")


def _audit(db, invitation_id, actor, event, now):
    db.execute(
        """INSERT INTO staff_invitation_audit(invitation_id, actor_user_id, event, created_at)
           VALUES (?, ?, ?, ?)""", (invitation_id, actor, event, now),
    )


class StaffInvitationLedger(IdentityLedger):
    def issue_staff_invitation(self, token, organization_id, email, grants):
        email = self.normalize_email(email)
        if not email.endswith(".test"):
            raise ValueError("Staff invitations require a synthetic recipient")
        with self._using_connection(immediate=True) as db:
            _require_staff_schema(db)
            issuer = active_user(db, token)
            organization_owner(db, issuer, organization_id)
            _validate_grants(db, organization_id, grants)
            recipient = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if recipient:
                _check_existing_grants(db, organization_id, recipient["id"], grants)
            now = int(time.time())
            if db.execute(
                """SELECT 1 FROM staff_invitations WHERE organization_id = ? AND email = ?
                   AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > ?""",
                (organization_id, email, now),
            ).fetchone():
                raise ValueError("A pending invitation already exists")
            invitation_id = str(uuid4())
            secret = secrets.token_urlsafe(32)
            db.execute(
                """INSERT INTO staff_invitations
                   (id, organization_id, email, token_hash, issuer_user_id, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (invitation_id, organization_id, email, digest(secret), issuer, now, now + INVITATION_TTL),
            )
            db.executemany(
                """INSERT INTO staff_invitation_branches(invitation_id, organization_id, branch_id, role)
                   VALUES (?, ?, ?, ?)""",
                ((invitation_id, organization_id, branch, role) for branch, role in grants),
            )
            _audit(db, invitation_id, issuer, "issued", now)
        return invitation_id, secret

    def accept_staff_invitation(self, secret, *, token=None, password=None):
        with self._using_connection(immediate=True) as db:
            _require_staff_schema(db)
            invitation = db.execute(
                """SELECT id, organization_id, issuer_user_id, email FROM staff_invitations
                   WHERE token_hash = ? AND expires_at > ? AND accepted_at IS NULL AND revoked_at IS NULL""",
                (digest(secret), int(time.time())),
            ).fetchone()
            if not invitation or not invitation["email"].endswith(".test"):
                raise ValueError("This staff invitation is unavailable")
            invitation_id, organization_id = invitation["id"], invitation["organization_id"]
            organization_owner(db, invitation["issuer_user_id"], organization_id)
            grants = list(db.execute(
                """SELECT branch_id, role FROM staff_invitation_branches
                   WHERE invitation_id = ? AND organization_id = ?""", (invitation_id, organization_id),
            ))
            _validate_grants(db, organization_id, grants)
            recipient = db.execute("SELECT id FROM users WHERE email = ?", (invitation["email"],)).fetchone()
            if recipient:
                user_id = recipient["id"]
                if active_user(db, token) != user_id or password is not None:
                    raise PermissionError("Sign in as the intended recipient")
            else:
                if token is not None or password is None:
                    raise ValueError("Complete verified account setup for this invitation")
                user_id = self._create_user(db, invitation["email"], password)
                self.audit_account(db, "email_verified", user_id)
            _check_existing_grants(db, organization_id, user_id, grants)
            db.execute(
                """INSERT INTO organization_memberships(organization_id, user_id, role)
                   VALUES (?, ?, 'MEMBER') ON CONFLICT(organization_id, user_id) DO NOTHING""",
                (organization_id, user_id),
            )
            db.executemany(
                """INSERT INTO branch_assignments(organization_id, branch_id, user_id, role)
                   VALUES (?, ?, ?, ?)""",
                ((organization_id, branch, user_id, role) for branch, role in grants),
            )
            now = int(time.time())
            if db.execute(
                """UPDATE staff_invitations SET accepted_at = ?, accepted_user_id = ?
                   WHERE id = ? AND expires_at > ? AND accepted_at IS NULL AND revoked_at IS NULL""",
                (now, user_id, invitation_id, now),
            ).rowcount != 1:
                raise ValueError("This staff invitation is unavailable")
            _audit(db, invitation_id, user_id, "accepted", now)

    def revoke_staff_invitation(self, token, organization_id, invitation_id):
        with self._using_connection(immediate=True) as db:
            _require_staff_schema(db)
            actor = active_user(db, token)
            organization_owner(db, actor, organization_id)
            self._revoke_staff_invitation(db, organization_id, invitation_id, actor, "revoked")

    def fail_staff_invitation_delivery(self, organization_id, invitation_id):
        with self._using_connection(immediate=True) as db:
            self._revoke_staff_invitation(db, organization_id, invitation_id, None, "delivery_failed")

    @staticmethod
    def _revoke_staff_invitation(db, organization_id, invitation_id, actor, event):
        now = int(time.time())
        if db.execute(
            """UPDATE staff_invitations SET revoked_at = ? WHERE id = ? AND organization_id = ?
               AND accepted_at IS NULL AND revoked_at IS NULL""", (now, invitation_id, organization_id),
        ).rowcount != 1:
            raise ValueError("This staff invitation is unavailable")
        _audit(db, invitation_id, actor, event, now)
