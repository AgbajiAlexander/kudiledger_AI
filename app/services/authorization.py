"""Live tenant policy. Staff capabilities have no operational API entry point yet."""

import hashlib
import time


ROLE_PERMISSIONS = {
    "OWNER": frozenset({"discover", "read", "report", "export", "record", "correct", "manage"}),
    "MANAGER": frozenset({"discover", "read", "report", "record"}),
    "CASHIER": frozenset({"discover", "read", "record"}),
    "ACCOUNTANT": frozenset({"discover", "read", "report", "export"}),
}


def active_user(db, token):
    if not isinstance(token, str) or not token or len(token) > 256:
        raise PermissionError("Authentication required")
    row = db.execute(
        """SELECT s.user_id FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = ? AND s.expires_at > ?""",
        (hashlib.sha256(token.encode("utf-8")).hexdigest(), int(time.time())),
    ).fetchone()
    if row is None:
        raise PermissionError("Authentication required")
    return row["user_id"]


def has_scope_schema(db):
    names = {row[0] for row in db.execute(
        """SELECT name FROM sqlite_schema WHERE type = 'table' AND name IN
           ('kudiledger_schema_versions', 'organizations', 'branches',
            'organization_memberships', 'branch_assignments')"""
    )}
    if not names:
        return False
    if len(names) != 5 or not db.execute(
        "SELECT 1 FROM kudiledger_schema_versions WHERE version = 1"
    ).fetchone():
        raise PermissionError("Tenant scope unavailable")
    return True


def legacy_owner(db, user_id, branch_id):
    row = db.execute(
        "SELECT role, user_id FROM memberships WHERE user_id = ? AND business_id = ? AND role = 'OWNER'",
        (user_id, branch_id),
    ).fetchone()
    if row is None:
        raise PermissionError("Access denied for this business")
    if has_scope_schema(db):
        mapping = db.execute(
            "SELECT organization_id, is_default FROM branches WHERE id = ?", (branch_id,),
        ).fetchone()
        if mapping is not None:
            if not mapping["is_default"]:
                raise PermissionError("Access denied for this business")
            require_branch_permission(db, user_id, mapping["organization_id"], branch_id, "manage")
    return row


def organization_owner(db, user_id, organization_id):
    if not has_scope_schema(db) or not db.execute(
        """SELECT 1 FROM organization_memberships
           WHERE organization_id = ? AND user_id = ? AND role = 'OWNER'""",
        (organization_id, user_id),
    ).fetchone():
        raise PermissionError("Access denied for this organization")


def require_branch_permission(db, user_id, organization_id, branch_id, permission):
    if not has_scope_schema(db):
        raise PermissionError("Access denied for this branch")
    row = db.execute(
        """SELECT CASE WHEN m.role = 'OWNER' THEN 'OWNER'
                        WHEN m.role = 'MEMBER' THEN a.role END AS role
           FROM branches b
           JOIN organization_memberships m ON m.organization_id = b.organization_id AND m.user_id = ?
           LEFT JOIN branch_assignments a ON a.organization_id = b.organization_id
                 AND a.branch_id = b.id AND a.user_id = m.user_id
           WHERE b.organization_id = ? AND b.id = ?""",
        (user_id, organization_id, branch_id),
    ).fetchone()
    if row is None or permission not in ROLE_PERMISSIONS.get(row["role"], ()):
        raise PermissionError("Access denied for this branch")
    return row["role"]
