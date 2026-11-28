"""Organization-owner management of staff metadata."""

import time
from contextlib import contextmanager

from app.services.authorization import active_user, organization_owner
from app.services.staff_invitations import StaffInvitationLedger, _require_staff_schema, _validate_grants


def _require_management_schema(db):
    _require_staff_schema(db)
    if not db.execute("SELECT 1 FROM kudiledger_schema_versions WHERE version = 3").fetchone() or not db.execute(
        "SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = 'staff_permission_audit'"
    ).fetchone():
        raise PermissionError("Staff permission schema unavailable")


def _audit(db, actor, organization, action, *, user=None, branch=None, previous=None,
           resulting=None, outcome="allowed"):
    db.execute(
        """INSERT INTO staff_permission_audit
           (actor_user_id, organization_id, affected_user_id, branch_id, action, outcome,
            previous_role, resulting_role, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (actor, organization, user, branch, action, outcome, previous, resulting, int(time.time())),
    )


def _staff_email(db, organization, user):
    row = db.execute(
        """SELECT u.email FROM organization_memberships m JOIN users u ON u.id = m.user_id
           WHERE m.organization_id = ? AND m.user_id = ? AND m.role = 'MEMBER'
             AND NOT EXISTS (
                 SELECT 1 FROM branches b JOIN memberships legacy ON legacy.business_id = b.id
                 WHERE b.organization_id = m.organization_id
                   AND legacy.user_id = m.user_id AND legacy.role = 'OWNER'
             )""", (organization, user),
    ).fetchone()
    if row is None:
        raise PermissionError("Staff member is unavailable")
    return row["email"]


class StaffManagementLedger(StaffInvitationLedger):
    def list_organization_staff(self, token, organization):
        with self.connect() as db:
            db.execute("BEGIN")
            _require_management_schema(db)
            organization_owner(db, active_user(db, token), organization)
            return [dict(row) for row in db.execute(
                """SELECT m.user_id, u.email, a.branch_id, a.role
                   FROM organization_memberships m JOIN users u ON u.id = m.user_id
                   LEFT JOIN branch_assignments a ON a.organization_id = m.organization_id AND a.user_id = m.user_id
                   WHERE m.organization_id = ? AND m.role = 'MEMBER'
                   ORDER BY u.email, a.branch_id""", (organization,),
            )]

    @contextmanager
    def _staff_change(self, token, organization, action):
        with self._using_connection(immediate=True) as db:
            _require_management_schema(db)
            actor = active_user(db, token)
            try:
                organization_owner(db, actor, organization)
            except PermissionError:
                # Record only known actors in their own organizations. Target IDs are untrusted here.
                if db.execute(
                    "SELECT 1 FROM organization_memberships WHERE organization_id = ? AND user_id = ?",
                    (organization, actor),
                ).fetchone():
                    _audit(db, actor, organization, action, outcome="denied")
            else:
                yield db, actor
                return
        raise PermissionError("Access denied for this organization")

    def _cancel_pending(self, db, actor, organization, email, branch=None):
        pending = db.execute(
            """SELECT i.id FROM staff_invitations i
               WHERE i.organization_id = ? AND i.email = ? AND i.accepted_at IS NULL AND i.revoked_at IS NULL
                 AND (? IS NULL OR EXISTS (
                     SELECT 1 FROM staff_invitation_branches b WHERE b.invitation_id = i.id AND b.branch_id = ?
                 ))""", (organization, email, branch, branch),
        ).fetchall()
        for row in pending:
            self._revoke_staff_invitation(db, organization, row["id"], actor, "revoked")

    @staticmethod
    def _add_assignment(db, actor, organization, user, branch, role):
        _validate_grants(db, organization, [(branch, role)])
        if db.execute(
            """INSERT INTO branch_assignments(organization_id, branch_id, user_id, role)
               VALUES (?, ?, ?, ?) ON CONFLICT(organization_id, branch_id, user_id) DO NOTHING""",
            (organization, branch, user, role),
        ).rowcount != 1:
            raise ValueError("An assignment already exists for this branch")
        _audit(db, actor, organization, "assigned", user=user, branch=branch, resulting=role)

    @staticmethod
    def _remove_assignment(db, actor, organization, user, branch):
        row = db.execute(
            """DELETE FROM branch_assignments WHERE organization_id = ? AND user_id = ? AND branch_id = ?
               RETURNING role""", (organization, user, branch),
        ).fetchone()
        if row is None:
            raise ValueError("Branch assignment is unavailable")
        _audit(db, actor, organization, "assignment_revoked", user=user, branch=branch, previous=row["role"])

    def assign_staff_branch(self, token, organization, user, branch, role):
        with self._staff_change(token, organization, "assigned") as (db, actor):
            _staff_email(db, organization, user)
            self._add_assignment(db, actor, organization, user, branch, role)

    def change_staff_branch_role(self, token, organization, user, branch, role):
        with self._staff_change(token, organization, "role_changed") as (db, actor):
            _staff_email(db, organization, user)
            _validate_grants(db, organization, [(branch, role)])
            row = db.execute(
                "SELECT role FROM branch_assignments WHERE organization_id = ? AND user_id = ? AND branch_id = ?",
                (organization, user, branch),
            ).fetchone()
            if row is None or row["role"] == role:
                raise ValueError("Select an existing assignment and a different role")
            db.execute(
                "UPDATE branch_assignments SET role = ? WHERE organization_id = ? AND user_id = ? AND branch_id = ?",
                (role, organization, user, branch),
            )
            _audit(db, actor, organization, "role_changed", user=user, branch=branch,
                   previous=row["role"], resulting=role)

    def revoke_staff_branch(self, token, organization, user, branch):
        with self._staff_change(token, organization, "assignment_revoked") as (db, actor):
            email = _staff_email(db, organization, user)
            self._remove_assignment(db, actor, organization, user, branch)
            self._cancel_pending(db, actor, organization, email, branch)

    def reassign_staff_branch(self, token, organization, user, branch, destination, role):
        with self._staff_change(token, organization, "reassigned") as (db, actor):
            email = _staff_email(db, organization, user)
            if branch == destination:
                raise ValueError("Select a different destination branch")
            self._remove_assignment(db, actor, organization, user, branch)
            self._add_assignment(db, actor, organization, user, destination, role)
            self._cancel_pending(db, actor, organization, email, branch)

    def revoke_staff_membership(self, token, organization, user):
        with self._staff_change(token, organization, "membership_revoked") as (db, actor):
            email = _staff_email(db, organization, user)
            for row in db.execute(
                "SELECT branch_id FROM branch_assignments WHERE organization_id = ? AND user_id = ?",
                (organization, user),
            ).fetchall():
                self._remove_assignment(db, actor, organization, user, row["branch_id"])
            db.execute(
                "DELETE FROM organization_memberships WHERE organization_id = ? AND user_id = ? AND role = 'MEMBER'",
                (organization, user),
            )
            self._cancel_pending(db, actor, organization, email)
            _audit(db, actor, organization, "membership_revoked", user=user)
