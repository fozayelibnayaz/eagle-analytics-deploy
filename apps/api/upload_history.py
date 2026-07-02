"""
upload_history.py
Persistent first-upload registry. One-way ratchet.

Logic for is_truly_first_upload:
  1. Check upload_history.json → if email exists = REPEAT
  2. Check old_db project_dates → if any project date exists before upload_date = REPEAT
  3. Check old_db signup_dates:
     - If signup is MORE than 30 days before upload_date = REPEAT (old user finally uploading)
     - If signup is within 30 days of upload_date = could be FIRST
     - If no signup in old_db = brand new = FIRST
  4. If FIRST → record in upload_history.json permanently
"""
import json
from pathlib import Path
from datetime import datetime, timedelta

DATA_DIR = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)

HISTORY_FILE = DATA_DIR / "upload_history.json"

# Days between signup and first upload to still count as "first upload".
# Typical users upload within the same week/month; use 30 days to be more
# permissive while avoiding counting long-delayed uploads from old accounts.
FIRST_UPLOAD_WINDOW_DAYS = 30


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [UploadHistory] {msg}", flush=True)


def load_history():
    """Load upload history from disk. Returns dict keyed by normalized_email."""
    if not HISTORY_FILE.exists():
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"Load error: {e}")
        return {}


def save_history(history):
    """Save upload history to disk."""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, sort_keys=True)
    except Exception as e:
        log(f"Save error: {e}")


def _parse_date_str(s):
    """Parse YYYY-MM-DD string to date object. Returns None on failure."""
    if not s or str(s).strip() in ("", "—", "-", "nan", "None"):
        return None
    s = str(s).strip()
    # Try YYYY-MM-DD
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        pass
    return None


def is_truly_first_upload(normalized_email, upload_date_str, history):
    """
    Returns (is_first: bool, reason: str).

    Rules:
    1. Already in upload_history → REPEAT
    2. Has project_dates in old_db before upload_date → REPEAT
    3. Has signup_date more than FIRST_UPLOAD_WINDOW_DAYS before upload → REPEAT
       (old account = not a new user doing their first upload)
    4. Otherwise → FIRST
    """
    email = normalized_email.strip().lower() if normalized_email else ""
    if not email:
        return False, "no_email"

    # Rule 1: Already tracked
    if email in history:
        first = history[email].get("first_seen", "?")
        return False, f"repeat_already_in_history_since_{first}"

    upload_date = _parse_date_str(upload_date_str)

    # If no upload date, we can't determine — default to checking old_db only
    if not upload_date:
        return True, "no_upload_date_assume_first"

    # Load old_db to cross-check
    try:
        from dedup_engine import load_old_database_with_dates
        old_db = load_old_database_with_dates()
        entry = old_db.get(email)
    except Exception:
        entry = None

    if entry is None:
        # Not in old_db at all = brand new user
        return True, "not_in_old_db_brand_new"

    # Rule 2: Check project_dates (prior uploads in DB)
    project_dates = entry.get("project_dates", [])
    for pd_str in project_dates:
        pd = _parse_date_str(pd_str)
        if pd and pd < upload_date:
            return False, f"prior_project_upload_found_{pd_str}"

    # Rule 3: Check signup_dates
    signup_dates = entry.get("signup_dates", [])
    earliest_signup = None
    for sd_str in signup_dates:
        sd = _parse_date_str(sd_str)
        if sd:
            if earliest_signup is None or sd < earliest_signup:
                earliest_signup = sd

    if earliest_signup:
        days_diff = (upload_date - earliest_signup).days
        if days_diff > FIRST_UPLOAD_WINDOW_DAYS:
            return False, (
                f"old_account_signed_up_{earliest_signup}_upload_{upload_date}"
                f"_{days_diff}days_gap_exceeds_{FIRST_UPLOAD_WINDOW_DAYS}day_window"
            )
        elif days_diff >= 0:
            # Signed up recently = likely first upload
            return True, f"signed_up_{earliest_signup}_uploaded_{upload_date}_{days_diff}days_gap_within_window"
        else:
            # Upload date BEFORE signup date = data anomaly, default FIRST
            return True, f"upload_before_signup_anomaly_{earliest_signup}_vs_{upload_date}"

    # In old_db but no signup dates and no project dates = treat as FIRST
    # If the email exists in old_db but we have no dated evidence (only
    # placeholder/no-date rows), we cannot safely assume this is a true first
    # upload. Mark as not-determined so it can be manually inspected rather
    # than being automatically counted.
    return False, "not_determined_in_old_db_no_dates"


def record_upload(normalized_email, upload_date_str, history):
    """
    Record a confirmed first upload into history dict (in-place).
    Caller must call save_history() after processing all rows.
    """
    email = normalized_email.strip().lower() if normalized_email else ""
    if not email:
        return

    if email in history:
        # Already exists — add date to all_dates if new
        existing_dates = history[email].get("all_dates", [])
        if upload_date_str and upload_date_str not in existing_dates:
            existing_dates.append(upload_date_str)
            existing_dates.sort()
            history[email]["all_dates"] = existing_dates
        return

    history[email] = {
        "first_seen": upload_date_str or datetime.now().strftime("%Y-%m-%d"),
        "first_recorded_at": datetime.now().isoformat(),
        "all_dates": [upload_date_str] if upload_date_str else [],
    }


def bootstrap_from_existing(force=False):
    """
    Load existing upload_history.json.
    If force=True, rebuild from old_db project_dates.
    Returns history dict.
    """
    if not force and HISTORY_FILE.exists():
        history = load_history()
        log(f"Loaded existing history: {len(history)} emails")
        return history

    # Rebuild from old_db project_dates
    log("Bootstrapping upload history from old_db project_dates...")
    try:
        from dedup_engine import load_old_database_with_dates
        old_db = load_old_database_with_dates()
    except Exception as e:
        log(f"Cannot load old_db: {e}")
        return {}

    history = {}
    for email, entry in old_db.items():
        project_dates = entry.get("project_dates", [])
        if project_dates:
            valid_dates = sorted([d for d in project_dates if d and d != "__no_date__"])
            if valid_dates:
                history[email] = {
                    "first_seen": valid_dates[0],
                    "first_recorded_at": datetime.now().isoformat(),
                    "all_dates": valid_dates,
                    "source": "bootstrapped_from_old_db",
                }

    save_history(history)
    log(f"Bootstrap complete: {len(history)} emails with project history")
    return history


if __name__ == "__main__":
    log("Testing upload history logic...")
    history = load_history()
    log(f"Current history size: {len(history)}")

    # Test cases
    test = [
        ("eagledemo@invicara.com",      "2026-05-15", "REPEAT - old account 2024"),
        ("brand.new.user@test.com",     "2026-05-15", "FIRST - not in any DB"),
        ("djcm16@gmail.com",            "2026-05-11", "check based on signup date"),
        ("jara@libelium.com",           "2026-05-11", "check - signed up May 8"),
    ]

    print("\nTest Results:")
    for email, upload_date, description in test:
        is_first, reason = is_truly_first_upload(email, upload_date, history)
        verdict = "FIRST" if is_first else "REPEAT"
        print(f"  {verdict}: {email} | {description}")
        print(f"           Reason: {reason}")
