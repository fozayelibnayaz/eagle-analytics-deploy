"""
process_data.py — Eagle 3D Streaming Analytics Hub
====================================================
Reads raw scraped data from sheet_* collections in MongoDB,
validates each row, dedupes, and saves clean records to:
  - signups   (from sheet_raw_free)
  - uploads   (from sheet_raw_first_upload)
  - payments  (from sheet_raw_stripe)

Also mirrors to sheet_verified_* for backward compat.

Applies:
  - Email validation (email_validator_engine)
  - First-upload dedup (first_upload_logic)
  - Payment "must have > 0 spend" filter
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from mongo_client import find_all, upsert_many
from email_validator_engine import validate as validate_email
from first_upload_logic import bulk_register


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [process_data] {msg}", flush=True)


def _pick_email(row: Dict[str, Any]) -> str:
    for k in ("mail", "Email", "email", "e-mail", "Mail", "EMAIL"):
        v = row.get(k)
        if v:
            return str(v).strip().lower()
    return ""


# All date formats seen in raw data
_DATE_FORMATS = (
    "%m/%d/%y",              # "7/1/26"
    "%m/%d/%y, %I:%M %p",    # "7/1/26, 10:34 AM"
    "%m/%d/%Y, %I:%M %p",    # "7/1/2026, 10:34 AM"

    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%m/%d/%Y %H:%M",
    "%b %d, %Y",
    "%B %d, %Y",
    "%a %b %d %Y",           # "Sun May 31 2026"
    "%a %b %d %Y %H:%M:%S",  # "Sun May 31 2026 12:34:56"
    "%d-%m-%Y",
    "%Y/%m/%d",
)


def _parse_date_string(s: str) -> Optional[str]:
    """Return YYYY-MM-DD or None."""
    if not s:
        return None
    s = str(s).strip()
    if not s or s.lower() in ("nan", "none", "—", "-", "null", "n/a", "na", "-"):
        return None

    # ── Try RFC 2822 first (e.g. "Thu, 09 Jul 2026 04:43:05 GMT") ──
    # Python has email.utils.parsedate for this format
    try:
        from email.utils import parsedate_to_datetime
        d = parsedate_to_datetime(s)
        if d:
            return d.strftime("%Y-%m-%d")
    except Exception:
        pass

    # ── Try dateutil parser (handles many JS date formats) ──
    try:
        from dateutil import parser as _dp
        d = _dp.parse(s, fuzzy=True)
        if d and 2000 < d.year < 2100:
            return d.strftime("%Y-%m-%d")
    except Exception:
        pass

    # Strip 'GMT+xxxx (...)' junk
    s = re.sub(r"\s+GMT[+\-]\d{2,4}.*$", "", s)
    s = s.strip()

    for fmt in _DATE_FORMATS:
        try:
            d = datetime.strptime(s[:len(fmt) + 10], fmt)
            return d.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue

    # Try ISO first 10 chars
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]

    # Try MM/DD/YYYY prefix
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        try:
            mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return f"{yy:04d}-{mm:02d}-{dd:02d}"
        except Exception:
            pass

    # Try M/D/YY (2-digit year — Stripe uses this)
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2})(?:\D|$)", s)
    if m:
        try:
            mm, dd, yy_short = int(m.group(1)), int(m.group(2)), int(m.group(3))
            yy = 2000 + yy_short if yy_short < 70 else 1900 + yy_short
            return f"{yy:04d}-{mm:02d}-{dd:02d}"
        except Exception:
            pass

    return None


def _pick_date(row: Dict[str, Any], keys: List[str]) -> str:
    """Try each key in order; return first parseable date as YYYY-MM-DD."""
    for k in keys:
        v = row.get(k)
        if v is None:
            continue
        d = _parse_date_string(str(v))
        if d:
            return d
    return ""


def _parse_money(val: Any) -> float:
    """Handles '$29.00', '$29.00\nUSD', '29.00 USD', '$1,469.99', etc."""
    if val is None:
        return 0.0
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "—", "-", "n/a"):
        return 0.0
    # Extract first number pattern (handles $29.00\nUSD, 29.00 USD, $1,469.99)
    m = re.search(r"[-+]?\$?\s*([\d,]+(?:\.\d+)?)", s)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except (ValueError, TypeError):
            return 0.0
    return 0.0


def _parse_int(val: Any) -> int:
    if val is None:
        return 0
    try:
        return int(float(str(val).replace(",", "").strip() or 0))
    except (ValueError, TypeError):
        return 0


# ─────────────────────────────────────────────────────────────────
# COLUMN NAME MAPPINGS (all variants seen in raw sheet data)
# ─────────────────────────────────────────────────────────────────
SIGNUP_DATE_COLS = [
    "createdOn",                                    # NEW scraper field
    "Account Created On", "Account_Created_On",
    "Signup Date", "Signup_Date",
    "Created", "Created On", "Created Date",
    "Date", "signup_date",
]

UPLOAD_DATE_COLS = [
    "date",                                          # NEW scraper field (JS toString)
    "First_Upload_Date", "First Upload Date",       # both variants
    "Upload Date", "Upload_Date",
    "First Upload", "first_upload",
    "Date", "upload_date",
    "__scrape_date__",   # fallback
]

STRIPE_CREATED_COLS = [
    "Created", "Created On", "Account Created", "Account_Created",
    "Signup Date", "signup_date",
]

STRIPE_FIRST_PAY_COLS = [
    "Payment_Date", "Payment Date",
    "First payment", "First Payment", "First_Payment",
    "First payment date", "First Payment Date",
    "first_payment_date", "First Charge",
]

STRIPE_MONEY_COLS = ["Total spend", "Total Spend", "total_spend",
                     "Amount", "Lifetime spend", "Total"]

STRIPE_COUNT_COLS = ["Payment count", "Payment Count", "payment_count",
                     "Payments"]


# ─────────────────────────────────────────────────────────────────
# STAGE 1: SIGNUPS (from sheet_raw_free)
# ─────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────
# STRICT VALIDATION HELPERS
# ─────────────────────────────────────────────────────────────────
INTERNAL_DOMAINS = ("eagle3dstreaming.com", "eagle3d.com")


def _is_internal_email(email: str) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.split("@")[-1].strip().lower()
    return any(domain == d or domain.endswith("." + d) for d in INTERNAL_DOMAINS)


def _lookup_signup(email_normalized: str):
    """Find existing signup by normalized email. Returns doc or None."""
    from mongo_client import find_one
    return find_one("signups", {
        "email_normalized": email_normalized,
        "final_status":     "ACCEPTED",
    })


def _days_between(iso1: str, iso2: str) -> int:
    """Return days between two ISO dates (iso2 - iso1). None if unparseable."""
    if not iso1 or not iso2:
        return None
    try:
        from datetime import date as _d
        d1 = _d.fromisoformat(iso1[:10])
        d2 = _d.fromisoformat(iso2[:10])
        return (d2 - d1).days
    except Exception:
        return None

def process_signups() -> Dict[str, Any]:
    raw = find_all("sheet_raw_free")
    if not raw:
        log("No sheet_raw_free rows to process")
        return {"total": 0, "accepted": 0, "rejected": 0}

    seen: set = set()
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    reject_reasons_count = {}

    for row in raw:
        email = _pick_email(row)
        if not email:
            continue
        if email in seen:
            continue
        seen.add(email)

        signup_date = _pick_date(row, SIGNUP_DATE_COLS)
        lead_source = str(row.get("leadSource", "")
                          or row.get("Lead Source", "")
                          or row.get("lead_source", "")).strip()

        base = {
            "email":            row.get("mail") or row.get("Email") or email,
            "email_normalized": email,
            "signup_date":      signup_date,
            "lead_source":      lead_source or "Unknown",
            "raw_data":         {k: val for k, val in row.items()
                                  if not k.startswith("_")},
            "processed_at":     datetime.utcnow().isoformat(),
        }

        # ── STRICT VALIDATION RULES (in order) ──
        reason = None

        # Rule 1: Missing date
        if not signup_date:
            reason = "missing signup date"

        # Rule 2: Internal email
        elif _is_internal_email(email):
            reason = f"internal email domain (@{email.split('@')[-1]})"

        # Rule 3: Email validation (syntax/MX/disposable)
        else:
            v = validate_email(email)
            if not v["valid"]:
                reason = f"invalid email: {v['reason']}"

        # ── Decide ──
        if reason:
            base["final_status"]     = "REJECTED"
            base["reason"]           = reason
            base["rejection_reason"] = reason
            rejected.append(base)
            reject_reasons_count[reason.split(":")[0]] = reject_reasons_count.get(reason.split(":")[0], 0) + 1
        else:
            base["final_status"] = "ACCEPTED"
            base["reason"]       = ""
            accepted.append(base)

    all_rows = accepted + rejected
    upsert_many("signups", all_rows, "email_normalized")
    upsert_many("sheet_verified_free", all_rows, "email_normalized")

    log(f"Signups: total={len(all_rows)}, accepted={len(accepted)}, rejected={len(rejected)}")
    for reason, count in sorted(reject_reasons_count.items(), key=lambda x: -x[1]):
        log(f"   Rejected [{reason}]: {count}")
    return {"total": len(all_rows), "accepted": len(accepted),
             "rejected": len(rejected), "reject_breakdown": reject_reasons_count}


# ─────────────────────────────────────────────────────────────────
# STAGE 2: UPLOADS (from sheet_raw_first_upload)
# ─────────────────────────────────────────────────────────────────
def process_uploads() -> Dict[str, Any]:
    raw = find_all("sheet_raw_first_upload")
    if not raw:
        log("No sheet_raw_first_upload rows to process")
        return {"total": 0, "accepted": 0, "rejected": 0}

    # Max acceptable gap between signup and upload (business rule)
    MAX_GAP_DAYS = 30

    seen: set = set()
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    reject_reasons_count = {}

    for row in raw:
        email = _pick_email(row)
        if not email:
            continue
        if email in seen:
            continue
        seen.add(email)

        upload_date = _pick_date(row, UPLOAD_DATE_COLS)

        base = {
            "email":            row.get("mail") or row.get("Email") or email,
            "email_normalized": email,
            "upload_date":      upload_date,
            "raw_data":         {k: val for k, val in row.items()
                                  if not k.startswith("_")},
            "processed_at":     datetime.utcnow().isoformat(),
        }

        # ── STRICT VALIDATION (in order) ──
        reason = None

        # Rule 1: Missing date
        if not upload_date:
            reason = "missing upload date"

        # Rule 2: Internal email
        elif _is_internal_email(email):
            reason = f"internal email domain (@{email.split('@')[-1]})"

        # Rule 3: Email validation
        else:
            v = validate_email(email)
            if not v["valid"]:
                reason = f"invalid email: {v['reason']}"

        # Rule 4: Must have matching signup
        if not reason:
            signup = _lookup_signup(email)
            if not signup:
                reason = "no matching signup found"
            else:
                signup_date = signup.get("signup_date", "")
                base["signup_date"] = signup_date
                base["signup_lead_source"] = signup.get("lead_source", "")

                # Use upload_history for the ORIGINAL upload date.
                # If user deleted+re-uploaded, KPI dashboard shows the
                # LATEST date, but we always track from the FIRST time
                # we ever saw this email in an upload scrape.
                from mongo_client import find_one, upsert_one
                hist = find_one("upload_history_ledger", {"email_normalized": email})
                if hist:
                    original_upload = hist.get("first_ever_upload_date", upload_date)
                    base["original_upload_date"] = original_upload
                    base["is_repeat_upload"] = True
                    # Use ORIGINAL date for validation (not the scraped one)
                    effective_upload_date = original_upload
                else:
                    effective_upload_date = upload_date
                    base["original_upload_date"] = upload_date
                    base["is_repeat_upload"] = False
                    # Record in history (never overwrite once set)
                    upsert_one("upload_history_ledger", {
                        "email_normalized":       email,
                        "first_ever_upload_date": upload_date,
                        "app_name":               row.get("appname", ""),
                        "recorded_at":            datetime.utcnow().isoformat(),
                    }, ["email_normalized"])

                # Rule 5: Upload must be AFTER signup
                gap = _days_between(signup_date, effective_upload_date)
                if gap is not None:
                    base["days_signup_to_upload"] = gap
                    if gap < 0:
                        reason = f"upload {abs(gap)}d BEFORE signup (impossible)"
                    # Rule 6: Upload must be within MAX_GAP_DAYS of signup
                    elif gap > MAX_GAP_DAYS:
                        reason = f"upload {gap}d after signup (>{MAX_GAP_DAYS}d gap, likely re-upload after delete)"

        # ── Decide ──
        if reason:
            base["final_status"]     = "REJECTED"
            base["reason"]           = reason
            base["rejection_reason"] = reason
            rejected.append(base)
            key = reason.split(":")[0].split("(")[0].strip()
            reject_reasons_count[key] = reject_reasons_count.get(key, 0) + 1
        else:
            base["final_status"] = "ACCEPTED"
            base["reason"]       = ""
            accepted.append(base)

    all_rows = accepted + rejected
    upsert_many("uploads", all_rows, "email_normalized")
    upsert_many("sheet_verified_first_upload", all_rows, "email_normalized")

    if accepted:
        reg = bulk_register(accepted)
        log(f"Upload registry: {reg}")

    log(f"Uploads: total={len(all_rows)}, accepted={len(accepted)}, rejected={len(rejected)}")
    for reason, count in sorted(reject_reasons_count.items(), key=lambda x: -x[1]):
        log(f"   Rejected [{reason}]: {count}")
    return {"total": len(all_rows), "accepted": len(accepted),
             "rejected": len(rejected), "reject_breakdown": reject_reasons_count}


# ─────────────────────────────────────────────────────────────────
# STAGE 3: PAYMENTS (from sheet_raw_stripe)
# ─────────────────────────────────────────────────────────────────
def process_payments() -> Dict[str, Any]:
    raw = find_all("sheet_raw_stripe")
    if not raw:
        log("No sheet_raw_stripe rows to process")
        return {"total": 0, "accepted": 0, "rejected": 0}

    seen: set = set()
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    for row in raw:
        email = _pick_email(row)
        if not email:
            continue

        created_date  = _pick_date(row, STRIPE_CREATED_COLS)
        first_pay     = _pick_date(row, STRIPE_FIRST_PAY_COLS)
        total_spend   = _parse_money(
            row.get("Total spend") or row.get("Total Spend")
            or row.get("total_spend") or row.get("Amount")
            or row.get("Lifetime spend") or row.get("Total")
        )
        payment_count = _parse_int(
            row.get("Payment count") or row.get("Payment Count")
            or row.get("payment_count") or row.get("Payments")
        )

        if email in seen:
            continue
        seen.add(email)

        v = validate_email(email)
        base = {
            "email":              row.get("Email") or email,
            "email_normalized":   email,
            "created_date":       created_date,
            "first_payment_date": first_pay or created_date,
            "total_spend":        total_spend,
            "payment_count":      payment_count,
            "raw_data":           {k: val for k, val in row.items()
                                    if not k.startswith("_")},
            "processed_at":       datetime.utcnow().isoformat(),
        }

        # Determine customer_type via payment_history collection.
        # KPI/Stripe scrape doesn't reliably give payment_count, so we
        # maintain our OWN historical ledger: first time we see an email
        # in ANY payment scrape = NEW_CUSTOMER. All subsequent = RECURRING.
        from mongo_client import find_one, upsert_one
        prev = find_one("payment_history", {"email_normalized": email})
        if prev:
            base["customer_type"] = "RECURRING"
            base["first_ever_payment_date"] = prev.get("first_ever_payment_date",
                                                        first_pay or created_date)
        else:
            base["customer_type"] = "NEW_CUSTOMER"
            base["first_ever_payment_date"] = first_pay or created_date
            # Record in history (immutable — insert once)
            upsert_one("payment_history", {
                "email_normalized":         email,
                "first_ever_payment_date":  first_pay or created_date,
                "first_ever_amount":        total_spend,
                "recorded_at":              datetime.utcnow().isoformat(),
            }, ["email_normalized"])

        # ── VALIDATION ──
        reason = None
        if _is_internal_email(email):
            reason = f"internal email domain (@{email.split('@')[-1]})"
        elif not v["valid"]:
            reason = f"invalid email: {v['reason']}"
        elif total_spend <= 0:
            reason = "total_spend = $0 (not paid)"

        if reason:
            base["final_status"]     = "REJECTED"
            base["reason"]           = reason
            base["rejection_reason"] = reason
            rejected.append(base)
        else:
            base["final_status"] = "ACCEPTED"
            base["reason"]       = ""
            accepted.append(base)

    all_rows = accepted + rejected
    upsert_many("payments", all_rows, "email_normalized")
    upsert_many("sheet_verified_stripe", all_rows, "email_normalized")

    log(f"Payments processed: total={len(all_rows)}, "
        f"accepted={len(accepted)}, rejected={len(rejected)}")
    return {"total": len(all_rows), "accepted": len(accepted), "rejected": len(rejected)}


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────
def main() -> Dict[str, Any]:
    log("=" * 60)
    log("PROCESS_DATA STARTING")
    log("=" * 60)

    result = {
        "signups":  process_signups(),
        "uploads":  process_uploads(),
        "payments": process_payments(),
    }

    log("=" * 60)
    log("PROCESS_DATA COMPLETE")
    log(f"  Signups:  {result['signups']}")
    log(f"  Uploads:  {result['uploads']}")
    log(f"  Payments: {result['payments']}")
    log("=" * 60)
    return result


if __name__ == "__main__":
    import json
    r = main()
    print(json.dumps(r, indent=2))
