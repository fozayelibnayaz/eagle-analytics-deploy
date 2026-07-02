#!/usr/bin/env python3
"""
Access Control System — MongoDB only

Rules:
- @eagle3dstreaming.com emails are allowed by default
- Other emails must exist in access_control collection with is_active=True
- Roles are stored in MongoDB
- Access events are logged in access_log collection
"""

from datetime import datetime
from typing import Tuple, Dict, Any, List
from mongo_client import get_db


COMPANY_DOMAIN = "eagle3dstreaming.com"


def _get_sb():
    """Legacy compatibility name. Returns MongoDB database."""
    return get_db()


def _now() -> str:
    return datetime.utcnow().isoformat()


def _norm_email(email: str) -> str:
    return str(email or "").strip().lower()


def _users_col():
    db = get_db()
    return None if db is None else db["access_control"]


def _logs_col():
    db = get_db()
    return None if db is None else db["access_log"]


def _active_user_record(email: str) -> Dict[str, Any]:
    email = _norm_email(email)
    col = _users_col()
    if col is None or not email:
        return None
    return col.find_one({"email": email, "is_active": True}, {"_id": 0})


def get_user_role(email: str) -> str:
    email = _norm_email(email)
    if not email or "@" not in email:
        return "none"

    rec = _active_user_record(email)
    if rec:
        return rec.get("role", "viewer")

    domain = email.split("@")[-1]
    if domain == COMPANY_DOMAIN:
        return "viewer"

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

    # Rule 1: company domain always allowed
    if domain == COMPANY_DOMAIN:
        role = rec.get("role", "viewer") if rec else "viewer"
        return True, role, "Company domain allowlist"

    # Rule 2: explicit allowlist
    if rec:
        return True, rec.get("role", "viewer"), "Explicit allowlist"

    return False, "none", "Email not authorized"


def log_access(email: str, action="login", success=True, reason="", role="viewer", ip="unknown", **kwargs) -> bool:
    """
    Flexible logger for access attempts.
    Compatible with different call styles from the app.
    """
    col = _logs_col()
    if col is None:
        return False

    email = _norm_email(email)

    # Support alternate kwarg names if app passes them
    if "allowed" in kwargs and "success" not in kwargs:
        success = bool(kwargs.get("allowed"))
    if "message" in kwargs and not reason:
        reason = str(kwargs.get("message", ""))
    if "user_role" in kwargs and not role:
        role = str(kwargs.get("user_role", "viewer"))

    doc = {
        "timestamp": _now(),
        "email": email,
        "action": str(action or "login"),
        "success": bool(success),
        "reason": str(reason or ""),
        "role": str(role or "viewer"),
        "ip": str(ip or "unknown"),
    }

    try:
        col.insert_one(doc)
        return True
    except Exception:
        return False


def list_users() -> List[Dict[str, Any]]:
    col = _users_col()
    if col is None:
        return []

    rows = list(col.find({}, {"_id": 0}).sort([("is_active", -1), ("added_at", -1), ("email", 1)]))
    return rows


def list_active_users() -> List[Dict[str, Any]]:
    col = _users_col()
    if col is None:
        return []

    rows = list(col.find({"is_active": True}, {"_id": 0}).sort([("role", 1), ("email", 1)]))
    return rows


def add_email(email: str, role="viewer", added_by="system", notes="") -> Dict[str, Any]:
    email = _norm_email(email)
    if not email or "@" not in email:
        return {"success": False, "message": "Invalid email"}

    role = str(role or "viewer").strip().lower()
    if role not in ("viewer", "editor", "admin"):
        role = "viewer"

    col = _users_col()
    if col is None:
        return {"success": False, "message": "MongoDB not connected"}

    doc = {
        "email": email,
        "role": role,
        "is_active": True,
        "added_by": str(added_by or "system"),
        "added_at": _now(),
        "updated_at": _now(),
        "notes": str(notes or ""),
    }

    try:
        col.update_one({"email": email}, {"$set": doc}, upsert=True)
        log_access(email, action="grant_access", success=True, reason="User added/updated", role=role, ip="system")
        return {"success": True, "message": f"Added {email} as {role}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def remove_email(email: str, removed_by="system", reason="") -> Dict[str, Any]:
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
                "is_active": False,
                "removed_by": str(removed_by or "system"),
                "removed_at": _now(),
                "remove_reason": str(reason or ""),
                "updated_at": _now(),
            }},
            upsert=False,
        )

        if result.matched_count == 0:
            return {"success": False, "message": "Email not found in explicit allowlist"}

        log_access(email, action="revoke_access", success=True, reason=reason or "Access revoked", role="none", ip="system")
        return {"success": True, "message": f"Revoked {email}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def get_access_logs(limit=30) -> List[Dict[str, Any]]:
    col = _logs_col()
    if col is None:
        return []

    try:
        rows = list(col.find({}, {"_id": 0}).sort("timestamp", -1).limit(int(limit or 30)))
        return rows
    except Exception:
        return []


if __name__ == "__main__":
    print("MongoDB connected:", get_db() is not None)
    test_email = "ayaz@eagle3dstreaming.com"
    print("is_allowed:", is_allowed(test_email))
    print("users:", len(list_users()))
    print("logs:", len(get_access_logs(5)))
