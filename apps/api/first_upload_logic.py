"""
first_upload_logic.py — v4 ACCURACY FIX
Core rules for deciding TRUE first project upload.

KEY FIX in v4:
  "Paid customer" exception REMOVED from window bypass.
  
  Reason: A paid customer like unreal@molotovcocktail.tv who:
    - Signed up June 2024 (earliest = 2024-06-17)
    - Has paid $16,386 across 48 payments
    - Has dates in old_db: 2024-06-17, 2025-05-09, 2026-04-08
    - Uploads a project May 2026
  
  This is clearly a REPEAT UPLOAD from an existing user.
  Being a paid customer does NOT mean it is a first upload.
  Being a paid customer means they are a REAL email (not fake).
  
  Corrected rule:
    - Paid customer with dates in old_db → check dates normally
    - If gap > 60 days AND in old_db → REPEAT_UPLOAD
    - If brand new (not in old_db at all) → ACCEPTED regardless of paid status
    - "Paid" only bypasses email validation (confirms email is real)
    
GATE ORDER:
  1. Email intelligence (disposable/SMTP/MX)
  2. No upload date → reject
  3. Rejected as signup (unless paid = confirmed real email)
  4. Ledger check (idempotent re-runs)
  5. Historical upload_status=yes → REPEAT
  6. Determine signup_date from accepted_signups OR historical DB
  7. Historical dates older than signup_date → REPEAT (old account)
  8. Window check: 0-60 days → ACCEPTED, >60 days → REPEAT
  9. NOT_DETERMINED emails → flag for review
"""

import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from email_intelligence import verify_email

DATA_DIR     = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)

LEDGER_FILE  = DATA_DIR / "first_upload_ledger.json"
HIST_ACCT    = DATA_DIR / "historical_accounts.json"
HIST_PAID    = DATA_DIR / "historical_paid.json"

# Max days between signup and first upload to count as legitimate
# 0-60 days = new user uploading soon after signup = TRUE FIRST UPLOAD
# >60 days  = old account re-uploading = REPEAT UPLOAD
# NOTE: This is a FLEXIBLE window. Additional checks below handle:
#   - Users who sign up, upload, delete, re-upload (REPEAT regardless of window)
#   - Users with historical data from old_db (REPEAT if any prior activity)
#   - Users whose signup date is clearly old (e.g., 2024 signup, 2026 upload)
FIRST_UPLOAD_WINDOW_DAYS = 60

_HIST_ACCT_CACHE = None
_HIST_PAID_CACHE = None


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [FirstUpload] {msg}", flush=True)


def reset_caches():
    global _HIST_ACCT_CACHE, _HIST_PAID_CACHE
    _HIST_ACCT_CACHE = None
    _HIST_PAID_CACHE = None


def load_historical_accounts():
    global _HIST_ACCT_CACHE
    if _HIST_ACCT_CACHE is not None:
        return _HIST_ACCT_CACHE
    if HIST_ACCT.exists():
        try:
            _HIST_ACCT_CACHE = json.loads(HIST_ACCT.read_text())
            return _HIST_ACCT_CACHE
        except Exception:
            pass
    _HIST_ACCT_CACHE = {}
    return _HIST_ACCT_CACHE


def load_historical_paid():
    global _HIST_PAID_CACHE
    if _HIST_PAID_CACHE is not None:
        return _HIST_PAID_CACHE
    if HIST_PAID.exists():
        try:
            _HIST_PAID_CACHE = json.loads(HIST_PAID.read_text())
            return _HIST_PAID_CACHE
        except Exception:
            pass
    _HIST_PAID_CACHE = {}
    return _HIST_PAID_CACHE


def load_ledger():
    if not LEDGER_FILE.exists():
        return {}
    try:
        return json.loads(LEDGER_FILE.read_text())
    except Exception:
        return {}


def save_ledger(ledger):
    try:
        LEDGER_FILE.write_text(json.dumps(ledger, indent=2, sort_keys=True))
    except Exception as e:
        log(f"Ledger save error: {e}")


def record_first_upload_in_ledger(email_norm, upload_ymd, ledger):
    """Add to ledger dict in-place. Caller must call save_ledger()."""
    if not email_norm or not upload_ymd:
        return
    if email_norm not in ledger:
        ledger[email_norm] = {
            "first_upload_date": upload_ymd,
            "recorded_at":       datetime.now().isoformat(),
        }


def normalize_email(email):
    if not email:
        return ""
    e = str(email).strip().lower()
    if "@" not in e:
        return ""
    local, domain = e.split("@", 1)
    if "+" in local:
        local = local.split("+")[0]
    if domain in ("gmail.com", "googlemail.com"):
        local = local.replace(".", "")
    return f"{local}@{domain}"


def parse_date_to_ymd(raw):
    """Return YYYY-MM-DD or empty string."""
    if not raw or str(raw).strip() in ("", "—", "-", "nan", "None"):
        return ""
    s = str(raw).strip()
    from email.utils import parsedate_to_datetime
    import re
    try:
        return parsedate_to_datetime(s).strftime("%Y-%m-%d")
    except Exception:
        pass
    formats = [
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
        "%m/%d/%Y", "%m/%d/%y",
        "%a %b %d %Y", "%a %b %d %Y %H:%M:%S",
        "%b %d, %Y", "%d %b %Y",
    ]
    m = re.match(
        r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\w+)\s+(\d+)\s+(\d{4})',
        s, re.IGNORECASE
    )
    if m:
        try:
            return datetime.strptime(
                f"{m.group(1)} {m.group(2)} {m.group(3)}", "%b %d %Y"
            ).strftime("%Y-%m-%d")
        except Exception:
            pass
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try:
            return datetime(
                int(m.group(1)), int(m.group(2)), int(m.group(3))
            ).strftime("%Y-%m-%d")
        except Exception:
            pass
    return ""


def build_signup_maps(verified_free_rows):
    """
    Build two dicts from Verified_FREE rows:
      accepted_signups: {email_norm -> signup_date_ymd}
      rejected_signups: {email_norm -> True}
    """
    accepted = {}
    rejected = {}
    for r in verified_free_rows:
        email = ""
        for k in ("Email", "email", "EMAIL", "__email_normalized__"):
            if k in r and r[k] and "@" in str(r[k]):
                email = str(r[k]).strip().lower()
                break
        norm = normalize_email(email)
        if not norm:
            continue
        status = str(r.get("final_status", "")).strip().upper()
        if status == "ACCEPTED":
            date_raw = (r.get("Account Created On", "") or
                        r.get("scraped_date", "") or
                        r.get("row_date_used", ""))
            accepted[norm] = parse_date_to_ymd(date_raw)
        else:
            rejected[norm] = True
    return accepted, rejected


def is_paid_customer(email_norm):
    """
    Check if email is a CONFIRMED paid customer.
    Used ONLY to confirm email is real (not fake).
    Does NOT bypass upload history or date window checks.
    """
    hp = load_historical_paid()
    entry = hp.get(email_norm, {})
    return entry.get("has_paid", False) or entry.get("total_spend", 0) > 0


def has_any_historical_dates(email_norm):
    """
    Returns True if the email has ANY dated records in old_db or historical.
    Used to detect old accounts re-uploading.
    """
    # Check historical paid
    hp = load_historical_paid()
    if email_norm in hp:
        dates = hp[email_norm].get("all_created_utc", [])
        real_dates = [d for d in dates if d and d != "__no_date__"]
        if real_dates:
            return True, min(real_dates)

    # Check historical accounts
    ha = load_historical_accounts()
    if email_norm in ha:
        dates = ha[email_norm].get("all_dates", [])
        real_dates = [d for d in dates if d and d != "__no_date__"]
        if real_dates:
            return True, min(real_dates)

    return False, ""


def has_upload_status_yes(email_norm):
    """Check historical_accounts for upload_status=yes."""
    ha = load_historical_accounts()
    if email_norm not in ha:
        return False, ""
    for date, info in ha[email_norm].get("rows_by_date", {}).items():
        if info.get("has_upload_yes"):
            return True, date
    return False, ""


def get_all_historical_dates(email_norm):
    """Get all known dates from BOTH historical sources."""
    dates = set()

    ha = load_historical_accounts()
    if email_norm in ha:
        for d in ha[email_norm].get("all_dates", []):
            if d and d != "__no_date__":
                dates.add(d)

    hp = load_historical_paid()
    if email_norm in hp:
        for d in hp[email_norm].get("all_created_utc", []):
            if d and d != "__no_date__":
                dates.add(d)

    return sorted(dates)


def get_earliest_historical_date(email_norm):
    """Get the earliest known date for this email across all sources."""
    dates = get_all_historical_dates(email_norm)
    return dates[0] if dates else ""


def decide(email_raw, upload_date_raw, accepted_signups, rejected_signups,
           ledger, use_smtp=True):
    """
    Returns:
      (is_accepted, category, reason, normalized_email, upload_ymd, signals)

    Categories:
      ACCEPTED          — true first upload
      REPEAT_UPLOAD     — uploaded before, old account
      NO_EMAIL          — no email
      NO_UPLOAD_DATE    — cannot parse upload date
      REJECTED_AS_SIGNUP — fake/disposable email
      INTERNAL          — eagle3d internal
      DISPOSABLE        — disposable domain
      NO_MX             — no MX record
      SMTP_REJECTED     — SMTP rejected
      NOT_DETERMINED    — borderline, needs review
      NO_SIGNUP_DATA    — not in signups and not in historical DB
      DATE_ANOMALY      — upload before signup
      ALREADY_COUNTED   — in ledger from prior day (still accepted)
    """
    email_norm = normalize_email(email_raw)
    upload_ymd = parse_date_to_ymd(upload_date_raw)

    if not email_norm:
        return False, "NO_EMAIL", "no_email", "", upload_ymd, {}

    # ── GATE 1: Email intelligence ────────────────────────────────
    verify = verify_email(email_norm, use_smtp=use_smtp)
    signals = {
        "verify_verdict":  verify["verdict"],
        "verify_category": verify["category"],
        "verify_reason":   verify["reason"],
        "verify_score":    verify["score"],
    }

    if verify["verdict"] == "INVALID":
        # Hard fail: disposable, no MX, SMTP reject, internal
        # EXCEPTION: if confirmed paid customer with significant spend,
        # email domain is clearly real even if our checks fail
        # (e.g. company domains with strict SMTP)
        # BUT disposable domains are NEVER overridden - they are fake by definition
        if is_paid_customer(email_norm):
            hp = load_historical_paid()
            entry = hp.get(email_norm, {})
            spend = entry.get("total_spend", 0)
            if spend > 100:  # significant paid customer
                # Override INVALID only for non-disposable, non-internal failures
                # Disposable domains are NEVER overridden - they are fake by definition
                if verify["category"] not in ("DISPOSABLE", "INTERNAL"):
                    # Let it through email gate but still check dates
                    signals["email_gate_overridden"] = (
                        f"paid_customer_spend_{spend}_override"
                    )
                else:
                    return (False, verify["category"], verify["reason"],
                            email_norm, upload_ymd, signals)
            else:
                return (False, verify["category"], verify["reason"],
                        email_norm, upload_ymd, signals)
        else:
            return (False, verify["category"], verify["reason"],
                    email_norm, upload_ymd, signals)

    # ── GATE 2: Upload date required ─────────────────────────────
    if not upload_ymd:
        return False, "NO_UPLOAD_DATE", "cannot_parse_upload_date", email_norm, upload_ymd, signals

    # ── GATE 3: Rejected as signup ────────────────────────────────
    if email_norm in rejected_signups:
        # Paid customers can still be first uploads even if signup was rejected
        # (signup might have been rejected due to duplicate in current batch)
        if not is_paid_customer(email_norm):
            return (False, "REJECTED_AS_SIGNUP",
                    "email_rejected_during_signup_validation",
                    email_norm, upload_ymd, signals)

    # ── GATE 4: Ledger check ──────────────────────────────────────
    if email_norm in ledger:
        prior = ledger[email_norm].get("first_upload_date", "")
        if prior == upload_ymd:
            # Same event seen again (idempotent re-run)
            return True, "ACCEPTED", f"ledger_same_event_{prior}", email_norm, upload_ymd, signals
        if prior and prior < upload_ymd:
            # We already counted an earlier upload — this is repeat
            return False, "REPEAT_UPLOAD", f"prior_upload_in_ledger_{prior}", email_norm, upload_ymd, signals
        if prior and prior > upload_ymd:
            # This is an earlier event than what we recorded
            return True, "ACCEPTED", f"earlier_event_than_ledger_{prior}", email_norm, upload_ymd, signals
        # prior empty
        return True, "ALREADY_COUNTED", f"in_ledger_no_date", email_norm, upload_ymd, signals

    # ── GATE 5: Historical upload_status=yes ─────────────────────
    # Check BEFORE anything else — this is the strongest signal
    has_yes, yes_date = has_upload_status_yes(email_norm)
    if has_yes:
        return (False, "REPEAT_UPLOAD",
                f"historical_upload_yes_on_{yes_date}",
                email_norm, upload_ymd, signals)

    # ── GATE 5b: Upload registry check (delete & re-upload) ─────
    try:
        from upload_registry import is_in_registry
        if is_in_registry(email_norm):
            return (False, "REPEAT_UPLOAD",
                    "already_in_upload_registry_delete_reupload",
                    email_norm, upload_ymd, signals)
    except ImportError:
        pass

    # ── GATE 5c: Upload history file check ──────────────────────
    try:
        from upload_history import load_history
        uh = load_history()
        if email_norm in uh:
            first_seen = uh[email_norm].get("first_seen", "?")
            return (False, "REPEAT_UPLOAD",
                    f"in_upload_history_first_seen_{first_seen}",
                    email_norm, upload_ymd, signals)
    except Exception:
        pass

    # ── GATE 5d: Cross-check with old_db for prior activity ────
    try:
        from dedup_engine import load_old_database_with_dates as _load_old_db
        _old_db = _load_old_db()
        if email_norm in _old_db:
            _entry = _old_db[email_norm]
            _dates = [d for d in _entry.get("dates", []) if d and d != "__no_date__"]
            if _dates:
                _earliest = min(_dates)
                try:
                    _e_dt = datetime.strptime(_earliest, "%Y-%m-%d").date()
                    _u_dt = datetime.strptime(upload_ymd, "%Y-%m-%d").date()
                    _gap = (_u_dt - _e_dt).days
                    if _gap > FIRST_UPLOAD_WINDOW_DAYS:
                        return (False, "REPEAT_UPLOAD",
                                f"old_db_user_earliest_{_earliest}_upload_{upload_ymd}_gap_{_gap}d",
                                email_norm, upload_ymd, signals)
                except Exception:
                    pass
    except Exception:
        pass

    # ── GATE 6: Old account detection ────────────────────────────
    # If email has dates in historical DB that are MUCH older than upload,
    # this is an existing user — not a new first upload.
    # This catches cases like unreal@molotovcocktail.tv:
    #   earliest date = 2024-06-17, upload = 2026-05-18 = 700+ days gap
    earliest_hist = get_earliest_historical_date(email_norm)
    if earliest_hist:
        try:
            earliest_dt = datetime.strptime(earliest_hist, "%Y-%m-%d").date()
            upload_dt   = datetime.strptime(upload_ymd, "%Y-%m-%d").date()
            hist_gap    = (upload_dt - earliest_dt).days

            if hist_gap > FIRST_UPLOAD_WINDOW_DAYS:
                # Old account — this is a repeat upload regardless of paid status
                return (
                    False, "REPEAT_UPLOAD",
                    f"old_account_earliest_date_{earliest_hist}_upload_{upload_ymd}_gap_{hist_gap}d",
                    email_norm, upload_ymd, signals
                )
            elif hist_gap >= 0:
                # Within window — could be first upload
                # Continue to further checks
                signals["hist_gap_days"] = hist_gap
            else:
                # Upload before earliest known date — data anomaly, very small negative OK
                if hist_gap < -3:
                    return (
                        False, "DATE_ANOMALY",
                        f"upload_{upload_ymd}_before_earliest_hist_{earliest_hist}",
                        email_norm, upload_ymd, signals
                    )

        except Exception as ex:
            signals["hist_date_error"] = str(ex)

    # ── GATE 7: Determine signup_date ────────────────────────────
    signup_date = accepted_signups.get(email_norm, "")

    if not signup_date:
        # Not in current run signups
        # Check historical accounts for signup date
        ha = load_historical_accounts()
        if email_norm in ha:
            acct_dates = [
                d for d in ha[email_norm].get("all_dates", [])
                if d and d != "__no_date__"
            ]
            if acct_dates:
                signup_date = min(acct_dates)

        # If still no signup date, check historical paid
        if not signup_date:
            hp = load_historical_paid()
            if email_norm in hp:
                stripe_date = hp[email_norm].get("stripe_created_utc", "")
                if stripe_date:
                    signup_date = stripe_date

        if not signup_date:
            # Truly not in any DB = brand new user = accept
            if verify["verdict"] == "NOT_DETERMINED":
                # Flag for manual review - brand new but uncertain
                signals["needs_review"] = True
                signals["review_reason"] = "brand_new_email_but_uncertain"
                return (
                    False, "NOT_DETERMINED",
                    f"brand_new_email_but_uncertain_score_{verify['score']}",
                    email_norm, upload_ymd, signals
                )
            return (
                True, "ACCEPTED",
                "brand_new_user_not_in_any_historical_db",
                email_norm, upload_ymd, signals
            )

    # ── GATE 8: Signup-to-upload window check ────────────────────
    try:
        sd  = datetime.strptime(signup_date, "%Y-%m-%d").date()
        ud  = datetime.strptime(upload_ymd, "%Y-%m-%d").date()
        gap = (ud - sd).days
    except Exception as ex:
        return False, "DATE_ANOMALY", f"date_parse_fail:{ex}", email_norm, upload_ymd, signals

    if gap < -3:
        # Upload significantly before signup = data anomaly
        return False, "DATE_ANOMALY", f"upload_{gap}d_before_signup", email_norm, upload_ymd, signals

    if gap < 0:
        gap = 0  # timezone tolerance

    if gap > FIRST_UPLOAD_WINDOW_DAYS:
        # Gap too large
        # NOTE: paid customer status does NOT override this check
        # A paid customer uploading 200 days after signup = old user re-uploading
        return (
            False, "REPEAT_UPLOAD",
            f"signup_{signup_date}_upload_{upload_ymd}_gap_{gap}d_exceeds_{FIRST_UPLOAD_WINDOW_DAYS}d_window",
            email_norm, upload_ymd, signals
        )

    # ── GATE 9: NOT_DETERMINED emails ────────────────────────────
    if verify["verdict"] == "NOT_DETERMINED":
        signals["needs_review"] = True
        signals["review_reason"] = f"email_uncertain_score_{verify['score']}_gap_{gap}d"
        return (
            False, "NOT_DETERMINED",
            f"email_uncertain_score_{verify['score']}_gap_{gap}d",
            email_norm, upload_ymd, signals
        )

    # ── ALL GATES PASSED → TRUE FIRST UPLOAD ─────────────────────
    return (
        True, "ACCEPTED",
        f"signup_{signup_date}_upload_{upload_ymd}_gap_{gap}d_score_{verify['score']}",
        email_norm, upload_ymd, signals
    )


if __name__ == "__main__":
    log(f"first_upload_logic.py v4 — FIRST_UPLOAD_WINDOW_DAYS={FIRST_UPLOAD_WINDOW_DAYS}")
    log("Key fix: paid customer status does NOT bypass date window check")
    log("Old accounts (earliest_hist > 60d before upload) = REPEAT_UPLOAD")
