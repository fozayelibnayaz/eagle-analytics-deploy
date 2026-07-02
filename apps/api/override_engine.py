#!/usr/bin/env python3
"""
MANUAL OVERRIDE ENGINE — Priority 2
Manual overrides are AUTHORITATIVE and PERMANENT.
No automated process can overwrite them.
Full audit trail with who/when/why/before/after.
"""
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional

OVERRIDE_FILE    = Path("data_output/manual_overrides.json")
OVERRIDE_LOG     = Path("data_output/override_audit_log.json")
OVERRIDE_DIR     = Path("data_output")
OVERRIDE_DIR.mkdir(parents=True, exist_ok=True)

# Status mappings
VALID_ACTIONS = {
    "accept":  {"final_status": "ACCEPTED", "category": "MANUAL_ACCEPT"},
    "reject":  {"final_status": "REJECTED", "category": "MANUAL_REJECT"},
    "pending": {"final_status": "PENDING",  "category": "MANUAL_PENDING"},
}

ACTION_TO_STATUS = VALID_ACTIONS


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [Override] {msg}", flush=True)


def normalize_email(email: str) -> str:
    if not email:
        return ""
    return str(email).strip().lower()


def _load_overrides() -> dict:
    """Load override store. Returns dict keyed by normalized email."""
    if OVERRIDE_FILE.exists():
        try:
            return json.loads(OVERRIDE_FILE.read_text())
        except Exception as e:
            log(f"Override load error: {e}")
    return {}


def _save_overrides(overrides: dict):
    """Atomically save overrides — write to temp then rename."""
    tmp = OVERRIDE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(overrides, indent=2))
        tmp.rename(OVERRIDE_FILE)
    except Exception as e:
        log(f"Override save error: {e}")
        raise


def _load_log() -> list:
    """Load audit log."""
    if OVERRIDE_LOG.exists():
        try:
            return json.loads(OVERRIDE_LOG.read_text())
        except Exception:
            pass
    return []


def _save_log(entries: list):
    """Save audit log atomically."""
    tmp = OVERRIDE_LOG.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(entries, indent=2))
        tmp.rename(OVERRIDE_LOG)
    except Exception as e:
        log(f"Audit log save error: {e}")


def load_overrides() -> dict:
    """Public: load all overrides."""
    return _load_overrides()


def set_override(
    email: str,
    action: str,
    reason: str,
    user: str = "system",
    source_tab: str = "",
    extra_data: Optional[dict] = None,
) -> dict:
    """
    Set a manual override. THIS IS AUTHORITATIVE — never overwritten by automation.
    
    Args:
        email:      Customer email
        action:     accept | reject | pending
        reason:     Why this override was set
        user:       Who set it (username/email)
        source_tab: Which tab (FREE/STRIPE/FIRST_UPLOAD)
        extra_data: Any additional context
    
    Returns:
        The override record
    """
    if action not in VALID_ACTIONS:
        raise ValueError(f"Invalid action '{action}'. Must be: {list(VALID_ACTIONS.keys())}")

    norm = normalize_email(email)
    if not norm:
        raise ValueError("Email cannot be empty")

    overrides = _load_overrides()
    audit_log = _load_log()

    # Previous state for audit trail
    previous = overrides.get(norm, {})
    previous_status = previous.get("action", "none")

    # Build override record
    now = datetime.utcnow().isoformat()
    record = {
        "email":            norm,
        "action":           action,
        "final_status":     VALID_ACTIONS[action]["final_status"],
        "category":         VALID_ACTIONS[action]["category"],
        "reason":           reason,
        "override_user":    user,
        "override_timestamp": now,
        "source_tab":       source_tab,
        "is_manual":        True,
        "authoritative":    True,  # Must never be overwritten by automation
        "extra":            extra_data or {},
    }

    overrides[norm] = record

    # Audit log entry
    audit_entry = {
        "timestamp":        now,
        "email":            norm,
        "action":           action,
        "previous_action":  previous_status,
        "previous_status":  previous.get("final_status", "none"),
        "new_status":       VALID_ACTIONS[action]["final_status"],
        "reason":           reason,
        "user":             user,
        "source_tab":       source_tab,
        "change_type":      "CREATE" if not previous else "UPDATE",
    }
    audit_log.append(audit_entry)

    _save_overrides(overrides)
    _save_log(audit_log)

    log(f"Override SET: {norm} → {action} by {user} (was: {previous_status})")
    return record


def remove_override(email: str, user: str = "system", reason: str = "") -> bool:
    """Remove an override (restore to automated processing)."""
    norm = normalize_email(email)
    overrides = _load_overrides()
    audit_log = _load_log()

    if norm not in overrides:
        return False

    previous = overrides.pop(norm)

    audit_entry = {
        "timestamp":       datetime.utcnow().isoformat(),
        "email":           norm,
        "action":          "REMOVED",
        "previous_action": previous.get("action", "none"),
        "previous_status": previous.get("final_status", "none"),
        "new_status":      "AUTOMATED",
        "reason":          reason or "Override removed — returning to automated processing",
        "user":            user,
        "change_type":     "REMOVE",
    }
    audit_log.append(audit_entry)

    _save_overrides(overrides)
    _save_log(audit_log)

    log(f"Override REMOVED: {norm} by {user}")
    return True


def get_override(email: str) -> Optional[dict]:
    """Get override for specific email. Returns None if not overridden."""
    norm = normalize_email(email)
    return _load_overrides().get(norm)


def get_audit_log(email: str = None, limit: int = 100) -> list:
    """Get audit log, optionally filtered by email."""
    entries = _load_log()
    if email:
        norm = normalize_email(email)
        entries = [e for e in entries if e.get("email") == norm]
    return sorted(entries, key=lambda x: x.get("timestamp", ""), reverse=True)[:limit]


def apply_overrides_to_rows(rows: list, source_tab: str = "") -> list:
    """
    Apply manual overrides to a list of rows.
    AUTHORITATIVE — manual override ALWAYS wins.
    Automation NEVER overwrites this.
    """
    overrides = _load_overrides()
    if not overrides:
        return rows

    applied = 0
    result = []
    for row in rows:
        r = dict(row)

        # Find email
        email = ""
        for ek in ("Email", "email", "__email_normalized__", "Email Address"):
            val = r.get(ek, "")
            if val and "@" in str(val):
                email = str(val).strip().lower()
                break

        norm = normalize_email(email) if email else ""

        if norm and norm in overrides:
            ov = overrides[norm]
            # Apply override — AUTHORITATIVE
            r["final_status"]         = ov["final_status"]
            r["category"]             = ov["category"]
            r["__override_applied__"] = True
            r["__override_action__"]  = ov["action"]
            r["__override_user__"]    = ov.get("override_user", "")
            r["__override_reason__"]  = ov.get("reason", "")
            r["__override_timestamp__"] = ov.get("override_timestamp", "")
            applied += 1

        result.append(r)

    if applied:
        log(f"Applied {applied} overrides to {len(rows)} rows [{source_tab}]")

    return result


def get_override_summary() -> dict:
    """Summary of all current overrides."""
    overrides = _load_overrides()
    audit_log = _load_log()

    accepted = [e for e in overrides.values() if e.get("action") == "accept"]
    rejected = [e for e in overrides.values() if e.get("action") == "reject"]
    pending  = [e for e in overrides.values() if e.get("action") == "pending"]

    return {
        "total":            len(overrides),
        "accepted":         len(accepted),
        "rejected":         len(rejected),
        "pending":          len(pending),
        "audit_log_entries": len(audit_log),
        "last_change":      audit_log[-1].get("timestamp") if audit_log else None,
        "overrides":        list(overrides.values()),
    }


if __name__ == "__main__":
    print("Override Engine — Test")
    print(json.dumps(get_override_summary(), indent=2))
