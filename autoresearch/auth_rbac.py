from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any


PERMISSIONS = {
    "approve_rag_intake",
    "ignore_rag_intake",
    "edit_reply_draft",
    "mark_posted_manually",
    "create_task",
    "create_note",
    "approve_high_risk_item",
    "withdraw_consent",
    "manage_users",
    "manage_roles",
}

ROLE_PERMISSIONS = {
    "super_admin": PERMISSIONS,
    "admin": {
        "approve_rag_intake",
        "ignore_rag_intake",
        "edit_reply_draft",
        "mark_posted_manually",
        "create_task",
        "create_note",
        "approve_high_risk_item",
        "withdraw_consent",
    },
    "operator": {"approve_rag_intake", "ignore_rag_intake", "create_task", "create_note"},
    "reviewer": {"ignore_rag_intake"},
    "readonly": set(),
}


class AuthRbacMixin:
    def _hash_password(self, password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    def _auth_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def createUser(self, username: str, password: str, role: str = "readonly", actorSessionToken: str | None = None) -> dict[str, Any]:
        if actorSessionToken:
            allowed = self.requirePermission(actorSessionToken, "manage_users", "create_user")
            if not allowed["allowed"]:
                return allowed
        if role not in ROLE_PERMISSIONS:
            raise ValueError(f"Unsupported role: {role}")
        now = self._auth_now()
        user_id = hashlib.sha1(f"user:{username}".encode()).hexdigest()
        self.store.conn.execute(
            """
            INSERT OR REPLACE INTO users (id, username, password_hash, role_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'active', COALESCE((SELECT created_at FROM users WHERE id=?), ?), ?)
            """,
            (user_id, username, self._hash_password(password), role, user_id, now, now),
        )
        self.store.conn.commit()
        self._auth_audit(user_id, "create_user", {"role": role})
        return {"userId": user_id, "username": username, "role": role, "status": "active"}

    def login(self, username: str, password: str) -> dict[str, Any]:
        row = self.store.conn.execute("SELECT * FROM users WHERE username=? AND status='active'", (username,)).fetchone()
        if row is None or row["password_hash"] != self._hash_password(password):
            self._auth_audit(None, "login_failed", {"username": username})
            return {"authenticated": False, "reason": "invalid_credentials"}
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(hours=8)).isoformat()
        self.store.conn.execute(
            "INSERT INTO sessions (id, user_id, session_token, created_at, expires_at, revoked_at) VALUES (?, ?, ?, ?, ?, NULL)",
            (hashlib.sha1(f"session:{token}".encode()).hexdigest(), row["id"], token, now.isoformat(), expires_at),
        )
        self.store.conn.commit()
        self._auth_audit(row["id"], "login", {"username": username})
        return {"authenticated": True, "sessionToken": token, "userId": row["id"], "role": row["role_id"], "expiresAt": expires_at}

    def logout(self, sessionToken: str) -> dict[str, Any]:
        session = self._session_row(sessionToken)
        now = self._auth_now()
        if session:
            self.store.conn.execute("UPDATE sessions SET revoked_at=? WHERE session_token=?", (now, sessionToken))
            self.store.conn.commit()
            self._auth_audit(session["user_id"], "logout", {})
        return {"loggedOut": True}

    def getSessionUser(self, sessionToken: str) -> dict[str, Any] | None:
        session = self._session_row(sessionToken)
        if session is None:
            return None
        user = self.store.conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if user is None:
            return None
        return {"userId": user["id"], "username": user["username"], "role": user["role_id"], "status": user["status"]}

    def getUserRole(self, sessionToken: str) -> str | None:
        user = self.getSessionUser(sessionToken)
        return user["role"] if user else None

    def getPermissionsForRole(self, role: str) -> set[str]:
        rows = self.store.conn.execute("SELECT permission_id FROM role_permissions WHERE role_id=?", (role,)).fetchall()
        return {row["permission_id"] for row in rows}

    def hasPermission(self, sessionToken: str, permission: str) -> bool:
        role = self.getUserRole(sessionToken)
        return bool(role and permission in self.getPermissionsForRole(role))

    def requirePermission(self, sessionToken: str, permission: str, actionName: str) -> dict[str, Any]:
        user = self.getSessionUser(sessionToken)
        allowed = bool(user and permission in self.getPermissionsForRole(user["role"]))
        self._auth_audit(user["userId"] if user else None, "permission_check", {"permission": permission, "actionName": actionName, "allowed": allowed})
        if not allowed:
            return {"allowed": False, "permission": permission, "actionName": actionName, "reason": "permission_denied"}
        return {"allowed": True, "permission": permission, "actionName": actionName, "role": user["role"]}

    def enforcePermission(self, sessionToken: str | None, permission: str, actionName: str) -> dict[str, Any]:
        if sessionToken is None:
            return {"allowed": True, "permission": permission, "actionName": actionName, "role": "internal_system"}
        return self.requirePermission(sessionToken, permission, actionName)

    def getAuthAuditLog(self) -> list[dict[str, Any]]:
        rows = self.store.conn.execute("SELECT * FROM auth_audit_events ORDER BY created_at ASC").fetchall()
        return [dict(row) for row in rows]

    def _session_row(self, sessionToken: str) -> Any:
        now = self._auth_now()
        return self.store.conn.execute(
            "SELECT * FROM sessions WHERE session_token=? AND revoked_at IS NULL AND expires_at > ?",
            (sessionToken, now),
        ).fetchone()

    def _auth_audit(self, user_id: str | None, event_type: str, payload: dict[str, Any]) -> None:
        now = self._auth_now()
        event_id = hashlib.sha1(f"auth-audit:{user_id}:{event_type}:{now}".encode()).hexdigest()
        self.store.conn.execute(
            "INSERT INTO auth_audit_events (id, user_id, event_type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
            (event_id, user_id, event_type, str(payload), now),
        )
        self.store.conn.commit()
