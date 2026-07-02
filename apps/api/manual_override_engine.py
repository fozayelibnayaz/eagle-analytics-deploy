"""
manual_override_engine.py
Handles manual label overrides set from the dashboard.
Stored in data_output/manual_overrides.json
Applied automatically during every process_data run.

Override structure:
{
  "email@example.com": {
    "action": "accept" | "reject" | "disposable" | "duplicate" | "not_determined",
    "target_tab": "Verified_FREE" | "Verified_FIRST_UPLOAD" | "Verified_STRIPE" | "ALL",
    "reason": "why you overrode it",
    "overridden_at": "2026-05-20T10:00:00",
    "original_category": "NOT_DETERMINED"
  }
}
"""
import json
from pathlib import Path
from datetime import datetime

OVERRIDE_FILE = Path("data_output/manual_overrides.json")

ACTION_TO_STATUS = {
    "accept":         {"final_status": "ACCEPTED", "category": "MANUAL_ACCEPTED"},
    "reject":         {"final_status": "REJECTED", "category": "MANUAL_REJECTED"},
    "disposable":     {"final_status": "REJECTED", "category": "DISPOSABLE"},
    "duplicate":      {"final_status": "REJECTED", "category": "DUPLICATE_MANUAL"},
    "not_determined": {"final_status": "REJECTED", "category": "NOT_DETERMINED"},
    "repeat_upload":  {"final_status": "REJECTED", "category": "REPEAT_UPLOAD"},
}


def normalize_email(email: str) -> str:
    e = str(email or "").strip().lower()
    if "@" not in e:
        return ""
    local, domain = e.split("@", 1)
    if "+" in local:
        local = local.split("+")[0]
    if domain in ("gmail.com", "googlemail.com"):
        local = local.replace(".", "")
    return f"{local}@{domain}"


def load_overrides() -> dict:
    if not OVERRIDE_FILE.exists():
        return {}
    try:
        return json.loads(OVERRIDE_FILE.read_text())
    except Exception:
        return {}


def save_overrides(overrides: dict):
    OVERRIDE_FILE.parent.mkdir(exist_ok=True)
    OVERRIDE_FILE.write_text(json.dumps(overrides, indent=2, sort_keys=True))


def apply_override(email: str, action: str, target_tab: str,
                   reason: str = "", original_category: str = "") -> bool:
    """Save a manual override. Returns True if successful."""
    norm = normalize_email(email)
    if not norm or action not in ACTION_TO_STATUS:
        return False
    overrides = load_overrides()
    overrides[norm] = {
        "action":            action,
        "target_tab":        target_tab,
        "reason":            reason or f"Manual override: {action}",
        "overridden_at":     datetime.now().isoformat(),
        "original_category": original_category,
    }
    save_overrides(overrides)
    return True


def apply_bulk_overrides(emails: list, action: str, target_tab: str,
                         reason: str = "") -> int:
    """Apply same override to multiple emails. Returns count saved."""
    count     = 0
    overrides = load_overrides()
    for email in emails:
        norm = normalize_email(email)
        if not norm:
            continue
        overrides[norm] = {
            "action":        action,
            "target_tab":    target_tab,
            "reason":        reason or f"Bulk override: {action}",
            "overridden_at": datetime.now().isoformat(),
        }
        count += 1
    save_overrides(overrides)
    return count


def remove_override(email: str) -> bool:
    """Remove a manual override. Returns True if it existed."""
    norm      = normalize_email(email)
    overrides = load_overrides()
    if norm in overrides:
        del overrides[norm]
        save_overrides(overrides)
        return True
    return False


def get_override(email: str) -> dict:
    """Get override for a single email, or empty dict."""
    norm = normalize_email(email)
    return load_overrides().get(norm, {})


def apply_overrides_to_rows(rows: list, tab_name: str) -> list:
    """
    Apply stored overrides to a list of verified rows.
    Called by process_data after each processing stage.
    """
    overrides = load_overrides()
    if not overrides:
        return rows

    applied = 0
    result  = []

    for row in rows:
        email = ""
        for k in ("Email", "email", "__email_normalized__"):
            if k in row and row[k] and "@" in str(row[k]):
                email = str(row[k]).strip().lower()
                break
        norm = normalize_email(email)

        if norm and norm in overrides:
            override = overrides[norm]
            ov_tab   = override.get("target_tab", "ALL")

            if ov_tab in ("ALL", tab_name):
                action  = override.get("action", "")
                mapping = ACTION_TO_STATUS.get(action, {})

                if mapping:
                    row                          = dict(row)
                    row["__original_status__"]   = row.get("final_status", "")
                    row["__original_category__"] = row.get("category", "")
                    row["final_status"]          = mapping["final_status"]
                    row["category"]              = mapping["category"]
                    row["email_verdict"]         = mapping["category"]
                    row["__manual_override__"]   = action
                    row["__override_reason__"]   = override.get("reason", "")
                    row["__override_at__"]       = override.get("overridden_at", "")
                    applied += 1

        result.append(row)

    if applied:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] [Override] "
            f"Applied {applied} manual overrides to {tab_name}",
            flush=True
        )
    return result


def get_override_summary() -> dict:
    """Return summary of all current overrides."""
    overrides = load_overrides()
    by_action = {}
    for data in overrides.values():
        action = data.get("action", "unknown")
        by_action[action] = by_action.get(action, 0) + 1
    return {
        "total":     len(overrides),
        "by_action": by_action,
        "emails":    list(overrides.keys()),
    }


if __name__ == "__main__":
    s = get_override_summary()
    print(f"Current overrides: {s['total']}")
    print(f"By action: {s['by_action']}")
