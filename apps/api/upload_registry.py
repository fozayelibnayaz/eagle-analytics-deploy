"""
upload_registry.py
SIMPLE rule: upload month must match signup month for TRUE first upload.

Logic:
  Get upload_date and signup_date (from old DB)
  
  Email NOT in old DB                   -> TRUE FIRST (brand new user)
  Same month/year (upload vs signup)    -> TRUE FIRST (legitimate first upload)
  Different month or year                -> REPEAT (uploaded before, re-uploaded)

Local registry tracks emails we've already counted to prevent double-counting
across daily runs.
"""
import json
from pathlib import Path
from datetime import datetime
from dedup_engine import normalize_email, parse_date

DATA_DIR = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)

REGISTRY_FILE = DATA_DIR / "upload_registry.json"


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [Registry] {msg}", flush=True)


def load_registry():
    if not REGISTRY_FILE.exists():
        return {}
    try:
        with open(REGISTRY_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_registry(registry):
    try:
        with open(REGISTRY_FILE, "w") as f:
            json.dump(registry, f, indent=2, sort_keys=True)
    except Exception as e:
        log(f"Save error: {e}")


def is_in_registry(email):
    norm = normalize_email(email)
    if not norm:
        return False
    return norm in load_registry()


def is_truly_first_upload(email, upload_date, old_db=None):
    """
    Returns (is_first, reason).
    
    Rules:
      1. Already in our registry      -> REPEAT (already counted before)
      2. No upload date               -> FIRST (default conservative)
      3. Email NOT in old DB          -> FIRST (brand new user)
      4. Email in old DB:
         - Same month/year as signup  -> FIRST (legitimate)
         - Different month/year       -> REPEAT (re-upload after delete)
    """
    norm = normalize_email(email)
    if not norm:
        return True, "no_email_skip_check"
    
    # Check our local registry first - prevents double-counting same upload
    registry = load_registry()
    if norm in registry:
        first_seen = registry[norm].get("first_seen", "?")
        return False, f"already_counted_in_registry_on_{first_seen}"
    
    if not upload_date:
        return True, "no_upload_date_default_first"
    
    if old_db is None:
        old_db = {}
    
    if norm not in old_db:
        return True, "not_in_old_db_brand_new_user"
    
    entry = old_db[norm]
    signup_date = entry.get("earliest", "")
    
    if not signup_date or signup_date == "__no_date__":
        return True, "in_old_db_but_no_signup_date_default_first"
    
    # Compare months
    try:
        signup_month = signup_date[:7]    # YYYY-MM
        upload_month = upload_date[:7]    # YYYY-MM
        
        if signup_month == upload_month:
            return True, f"same_month_signup_and_upload_{signup_month}"
        else:
            return False, f"signup_{signup_month}_vs_upload_{upload_month}_different_months"
    except Exception as e:
        return True, f"month_compare_error:{e}"


def record_first_upload(email, upload_date, reason=""):
    """Add to registry after counting as first upload."""
    norm = normalize_email(email)
    if not norm:
        return False
    
    registry = load_registry()
    
    if norm in registry:
        if upload_date and upload_date not in registry[norm].get("all_dates_observed", []):
            registry[norm].setdefault("all_dates_observed", []).append(upload_date)
            registry[norm]["all_dates_observed"].sort()
            save_registry(registry)
        return False
    
    registry[norm] = {
        "first_seen": upload_date or datetime.now().strftime("%Y-%m-%d"),
        "added_at": datetime.now().isoformat(),
        "all_dates_observed": [upload_date] if upload_date else [],
        "reason_accepted": reason,
        "source": "live_scrape",
    }
    save_registry(registry)
    return True


def add_to_registry(email, source, date_str=None, notes=""):
    norm = normalize_email(email)
    if not norm:
        return False
    
    registry = load_registry()
    if norm in registry:
        return False
    
    registry[norm] = {
        "first_seen": date_str or datetime.now().strftime("%Y-%m-%d"),
        "source": source,
        "added_at": datetime.now().isoformat(),
        "all_dates_observed": [date_str] if date_str else [],
        "notes": notes,
    }
    save_registry(registry)
    return True


def reset_registry():
    if REGISTRY_FILE.exists():
        REGISTRY_FILE.unlink()
    log("Registry RESET")


def bootstrap_registry(force=False):
    """Compatibility shim. Returns current registry."""
    if force:
        reset_registry()
    return load_registry()


if __name__ == "__main__":
    log("=" * 60)
    log("REGISTRY TEST - Simple Month Comparison")
    log("=" * 60)
    
    log("\nResetting registry for fresh test...")
    reset_registry()
    
    from dedup_engine import load_old_database_with_dates
    old_db = load_old_database_with_dates()
    log(f"Old DB loaded: {len(old_db)} emails")
    
    test_cases = [
        # (email, upload_date, expected_verdict, description)
        ("isak@adapt.se", "2026-04-10", "FIRST", "Signed up + uploaded same month"),
        ("isak@adapt.se", "2026-05-12", "REPEAT", "Re-upload month later (different month from signup)"),
        ("wolfgang.bernecker@tridonic.com", "2026-05-10", "REPEAT", "Signed up 2024, upload 2026"),
        ("eirik.murbraech@ramboll.no", "2026-05-13", "REPEAT", "Old user re-uploading"),
        ("brand.new.user@nowhere.com", "2026-05-14", "FIRST", "Not in old DB"),
    ]
    
    print()
    print("=" * 60)
    print("TEST CASES")
    print("=" * 60)
    
    for email, upload_date, expected, desc in test_cases:
        norm = normalize_email(email)
        signup = old_db.get(norm, {}).get("earliest", "N/A")
        
        is_first, reason = is_truly_first_upload(email, upload_date, old_db)
        actual = "FIRST" if is_first else "REPEAT"
        match = "✓" if actual == expected else "✗ MISMATCH"
        
        print(f"  {match} {email}")
        print(f"      Description: {desc}")
        print(f"      Upload: {upload_date}, Signup: {signup}")
        print(f"      Expected: {expected}, Actual: {actual}")
        print(f"      Reason: {reason}")
        print()
