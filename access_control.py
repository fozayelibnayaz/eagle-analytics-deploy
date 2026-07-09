"""
access_control.py — Eagle 3D Streaming Analytics Hub
======================================================
MongoDB-based access control.

Rules:
  - @eagle3dstreaming.com emails are auto-allowed (viewer role by default,
    unless overridden in the access_control collection).
  - Other emails must exist in access_control collection with is_active=True.
  - Roles: viewer | editor | admin
  - Every login attempt is logged to access_log collection with IP.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from mongo_client import get_raw_db


COMPANY_DOMAIN = "eagle3dstreaming.com"
VALID_ROLES = ("viewer", "editor", "admin")


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.utcnow().isoformat()


def _norm_email(email: str) -> str:
    return str(email or "").strip().lower()


def _users_col():
    db = get_raw_db()
    return None if db is None else db["access_control"]


def _logs_col():
    db = get_raw_db()
    return None if db is None else db["access_log"]


def _active_user_record(email: str) -> Optional[Dict[str, Any]]:
    email = _norm_email(email)
    col = _users_col()
    if col is None or not email:
        return None
    return col.find_one({"email": email, "is_active": True}, {"_id": 0})


# ─────────────────────────────────────────────────────────────────
# ROLES + PERMISSIONS
# ─────────────────────────────────────────────────────────────────
def get_user_role(email: str) -> str:
    email = _norm_email(email)
    if not email or "@" not in email:
        return "none"

    rec = _active_user_record(email)
    if rec:
        return rec.get("role", "viewer")

    domain = email.split("@")[-1]
    if domain == COMPANY_DOMAIN:
        return "admin"  # Company emails default to admin

    return "none"


def is_admin(email: str) -> bool:
    return get_user_role(email) == "admin"


def can_edit(email: str) -> bool:
    return get_user_role(email) in ("editor", "admin")


def is_allowed(email: str) -> Tuple[bool, str, str]:
    """
    Returns:
        (allowed: bool, role: str, reason: str)
    """
    email = _norm_email(email)
    if not email or "@" not in email:
        return False, "none", "Invalid email"

    domain = email.split("@")[-1]
    rec = _active_user_record(email)

    # Company domain: always allowed. Role from record if set, else admin.
    if domain == COMPANY_DOMAIN:
        role = rec.get("role", "admin") if rec else "admin"
        return True, role, "Company domain (auto-allowed)"

    # External: must be in the allow-list
    if rec:
        return True, rec.get("role", "viewer"), "External user in allow-list"

    return False, "none", "Email not authorized"


# ─────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────
def log_access(
    email: str,
    action: str = "login",
    success: bool = True,
    reason: str = "",
    role: str = "viewer",
    ip: str = "unknown",
    **kwargs,
) -> bool:
    col = _logs_col()
    if col is None:
        return False

    # Support alternate kwarg names
    if "allowed" in kwargs and "success" not in kwargs:
        success = bool(kwargs.get("allowed"))
    if "message" in kwargs and not reason:
        reason = str(kwargs.get("message", ""))
    if "user_role" in kwargs and not role:
        role = str(kwargs.get("user_role", "viewer"))

    doc = {
        "timestamp": _now(),
        "email":     _norm_email(email),
        "action":    str(action or "login"),
        "success":   bool(success),
        "reason":    str(reason or ""),
        "role":      str(role or "viewer"),
        "ip":        str(ip or "unknown"),
    }

    try:
        col.insert_one(doc)
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────
# USER MANAGEMENT
# ─────────────────────────────────────────────────────────────────
def list_users() -> List[Dict[str, Any]]:
    col = _users_col()
    if col is None:
        return []
    return list(
        col.find({}, {"_id": 0}).sort([
            ("is_active", -1),
            ("added_at", -1),
            ("email", 1),
        ])
    )


def list_active_users() -> List[Dict[str, Any]]:
    col = _users_col()
    if col is None:
        return []
    return list(
        col.find({"is_active": True}, {"_id": 0}).sort([
            ("role", 1),
            ("email", 1),
        ])
    )


def add_email(email: str, role: str = "viewer",
              added_by: str = "system", notes: str = "") -> Dict[str, Any]:
    email = _norm_email(email)
    if not email or "@" not in email:
        return {"success": False, "message": "Invalid email"}

    role = str(role or "viewer").strip().lower()
    if role not in VALID_ROLES:
        role = "viewer"

    col = _users_col()
    if col is None:
        return {"success": False, "message": "MongoDB not connected"}

    doc = {
        "email":      email,
        "role":       role,
        "is_active":  True,
        "added_by":   str(added_by or "system"),
        "added_at":   _now(),
        "updated_at": _now(),
        "notes":      str(notes or ""),
    }

    try:
        col.update_one({"email": email}, {"$set": doc}, upsert=True)
        log_access(email, action="grant_access", success=True,
                   reason="User added/updated", role=role, ip="system")
        return {"success": True, "message": f"Added {email} as {role}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def remove_email(email: str, removed_by: str = "system",
                 reason: str = "") -> Dict[str, Any]:
    email = _norm_email(email)
    if not email or "@" not in email:
        return {"success": False, "message": "Invalid email"}

    col = _users_col()
    if col is None:
        return {"success": False, "message": "MongoDB not connected"}

    try:
        result = col.update_one(
            {"email": email},
            {"$set": {
                "is_active":     False,
                "removed_by":    str(removed_by or "system"),
                "removed_at":    _now(),
                "remove_reason": str(reason or ""),
                "updated_at":    _now(),
            }},
            upsert=False,
        )

        if result.matched_count == 0:
            return {"success": False,
                    "message": "Email not found in allow-list"}

        log_access(email, action="revoke_access", success=True,
                   reason=reason or "Access revoked", role="none", ip="system")
        return {"success": True, "message": f"Revoked {email}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ─────────────────────────────────────────────────────────────────
# ACCESS LOG READ
# ─────────────────────────────────────────────────────────────────
def get_access_logs(limit: int = 30) -> List[Dict[str, Any]]:
    col = _logs_col()
    if col is None:
        return []
    try:
        return list(
            col.find({}, {"_id": 0})
               .sort("timestamp", -1)
               .limit(int(limit or 30))
        )
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    db = get_raw_db()
    print(f"MongoDB connected: {db is not None}")
    print(f"Users:             {len(list_users())}")
    print(f"Active users:      {len(list_active_users())}")
    test = "ayaz@eagle3dstreaming.com"
    print(f"is_allowed({test}): {is_allowed(test)}")
