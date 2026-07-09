"""
user_prefs.py — Persist per-user UI preferences in MongoDB.
"""
from typing import Any, Dict, Optional

from mongo_client import find_one, upsert_one


def get_pref(email: str, key: str, default: Any = None) -> Any:
    if not email:
        return default
    doc = find_one("user_prefs", {"email": email})
    if not doc:
        return default
    return doc.get(key, default)


def set_pref(email: str, key: str, value: Any) -> bool:
    if not email:
        return False
    return upsert_one("user_prefs",
                      {"email": email, key: value},
                      ["email"])


def get_all_prefs(email: str) -> Dict[str, Any]:
    if not email:
        return {}
    return find_one("user_prefs", {"email": email}) or {}
