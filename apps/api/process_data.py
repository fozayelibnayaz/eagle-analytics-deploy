"""process_data.py — uses email_intelligence + first_upload_logic v3"""
import os
import re
from pathlib import Path
from datetime import datetime
from collections import Counter

from sheets_writer import write_tab_data, read_tab_data
from email_intelligence import verify_email, fetch_disposable_lists
from dedup_engine import (
    load_old_database_with_dates, is_duplicate_signup,
    normalize_email, parse_date,
)
from first_upload_logic import (
    decide as decide_first_upload,
    build_signup_maps, parse_date_to_ymd,
    load_ledger, save_ledger, record_first_upload_in_ledger,
    reset_caches,
)
from ml_intelligence import score_rows, needs_retrain, train_models

DATA_DIR   = Path("data_output")
PROCESS_TS = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# Categories that count as ACCEPTED in daily counts
ACCEPTED_CATEGORIES = {"ACCEPTED", "ALREADY_COUNTED"}


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [Process] {msg}", flush=True)


def get_email(row):
    for k in ("Email", "email", "EMAIL"):
        if k in row and row[k] and "@" in str(row[k]):
            return str(row[k]).strip().lower()
    return ""


def get_scraped_date(row, source):
    if source == "FREE":
        # Try normalized name first, then legacy
        for f in ("Account Created On", "Signup_Date"):
            if f in row and row[f]:
                d = parse_date(row[f])
                if d:
                    return d
        return ""
    if source == "FIRST_UPLOAD":
        for f in ("Upload Date", "First_Upload_Date"):
            if f in row and row[f]:
                d = parse_date(row[f])
                if d:
                    return d
        return ""
    if source == "STRIPE":
        for f in ("First payment", "Created", "Created (UTC)", "Payment_Date"):
            if f in row and row[f]:
                d = parse_date(row[f])
                if d:
                    return d
        return ""
    return ""


def parse_amount(val):
    if not val:
        return 0.0
    s = re.sub(r"[$,€£¥\s]", "", str(val).strip())
    if not s or s in ("—", "-"):
        return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0


def categorize_stripe(row):
    email  = get_email(row)
    spend  = parse_amount(row.get("Total spend", "") or row.get("Total Spend", ""))
    fp     = parse_date(row.get("First payment", "") or row.get("Payment_Date", ""))
    cr     = parse_date(row.get("Created", "") or row.get("Created (UTC)", ""))
    d      = fp or cr

    # Check Payment Count — customers with payment_count >= 1 are verified paying customers
    pc_raw = row.get("Payment Count", "") or row.get("payment_count", "")
    payment_count = 0
    if pc_raw:
        try:
            payment_count = int(str(pc_raw).strip())
        except (ValueError, TypeError):
            pass

    # ── ACCEPTED: Any customer with a First payment date is a paying customer ──
    # The Stripe URL filters for payment_count>=1, so if we have a First payment
    # date, this customer has genuinely paid, even if Total spend is $0 (refunds,
    # pending, or display issue). The First payment date is the most reliable signal.
    if fp:
        return {
            "final_status": "ACCEPTED", "category": "ACCEPTED",
            "reason": f"paid_${spend:.2f}" if spend > 0 else "has_first_payment",
            "email": email,
            "amount": spend, "scraped_date": fp, "row_date_used": fp,
        }

    # ── ACCEPTED: Has Payment Count >= 1 and any date ──
    # Some rows might have payment count but missing First payment date
    if payment_count >= 1 and d:
        return {
            "final_status": "ACCEPTED", "category": "ACCEPTED",
            "reason": f"payment_count_{payment_count}", "email": email,
            "amount": spend, "scraped_date": d, "row_date_used": d,
        }

    # ── ACCEPTED: Has spend > 0 and any parseable date ──
    if spend > 0 and d:
        return {
            "final_status": "ACCEPTED", "category": "ACCEPTED",
            "reason": f"paid_${spend:.2f}", "email": email,
            "amount": spend, "scraped_date": d, "row_date_used": d,
        }

    # ── ACCEPTED: Has spend > 0 but no date — try harder to find a date ──
    # Check additional fields that might contain a date
    if spend > 0:
        for _df_name in ("Created", "Created (UTC)", "__scraped_at__", "__first_seen__", "__scrape_date__"):
            _d = parse_date(row.get(_df_name, ""))
            if _d:
                return {
                    "final_status": "ACCEPTED", "category": "ACCEPTED",
                    "reason": f"paid_${spend:.2f}_date_fallback", "email": email,
                    "amount": spend, "scraped_date": _d, "row_date_used": _d,
                }
        return {
            "final_status": "REJECTED", "category": "NO_DATE",
            "reason": "spend_no_date", "email": email,
            "amount": spend, "scraped_date": "", "row_date_used": "",
        }

    # ── REJECTED: Zero spend, no First payment date, no payment count ──
    return {
        "final_status": "REJECTED", "category": "ZERO_SPEND",
        "reason": "total_spend_zero", "email": email,
        "amount": 0.0, "scraped_date": "", "row_date_used": "",
    }


def categorize_signup(row, old_db, seen, use_smtp=True):
    email = get_email(row)
    if not email:
        return {"final_status": "REJECTED", "category": "NO_EMAIL",
                "reason": "no_email", "email": ""}

    verify = verify_email(email, use_smtp=use_smtp)
    if verify["verdict"] == "INVALID":
        return {
            "final_status": "REJECTED", "category": verify["category"],
            "reason": verify["reason"], "email": email,
            "verify_score": verify["score"],
        }

    # Lead source internal check
    lead = ""
    for k, v in row.items():
        if ("lead" in k.lower() or "source" in k.lower()) and v:
            lead = str(v).lower()
            break
    for kw in ("internal", "test", "demo", "fake", "sample"):
        if kw in lead:
            return {"final_status": "REJECTED", "category": "INTERNAL",
                    "reason": f"lead_source contains '{kw}'", "email": email}

    scraped = get_scraped_date(row, "FREE")
    norm    = normalize_email(email)

    if norm in seen:
        return {"final_status": "REJECTED", "category": "DUPLICATE_IN_BATCH",
                "reason": "same_email_in_batch", "email": email}

    is_dup, dup_reason = is_duplicate_signup(norm, scraped, old_db)
    if is_dup:
        return {"final_status": "REJECTED", "category": "DUPLICATE_DIFFERENT_DATE",
                "reason": dup_reason, "email": email, "scraped_date": scraped}

    if verify["verdict"] == "NOT_DETERMINED":
        return {"final_status": "REJECTED", "category": "NOT_DETERMINED",
                "reason": verify["reason"], "email": email,
                "scraped_date": scraped, "verify_score": verify["score"]}

    return {
        "final_status": "ACCEPTED", "category": "ACCEPTED",
        "reason": "validated_unique", "email": email,
        "in_old_db": "yes" if norm in old_db else "no",
        "scraped_date": scraped, "verify_score": verify["score"],
    }


def build_enriched(row, cat, source):
    e = dict(row)
    # ALREADY_COUNTED is treated as ACCEPTED for counting purposes
    is_counted = cat["category"] in ACCEPTED_CATEGORIES
    e["final_status"]         = "ACCEPTED" if is_counted else "REJECTED"
    e["category"]             = cat["category"]
    e["email_verdict"]        = cat["category"]
    e["verdict_reason"]       = cat.get("reason", "")
    e["__rejection_reason__"] = cat.get("reason", "")
    e["__email_normalized__"] = cat.get("email", "")
    e["__scraped_date__"]     = cat.get("scraped_date", "")
    e["row_date_used"]        = cat.get("row_date_used", "") or cat.get("scraped_date", "")
    e["__processed_at__"]     = PROCESS_TS
    e["__verify_score__"]     = cat.get("verify_score", "")
    if source == "STRIPE":
        e["__amount__"] = cat.get("amount", 0.0)
    e["__in_old_db__"]          = cat.get("in_old_db", "")
    e["__validation_status__"]  = "verified" if is_counted else "rejected"
    return e


def process_free(old_db, use_smtp=True):
    log("=" * 60)
    log("STAGE 1: FREE")
    rows = read_tab_data("Raw_FREE")
    log(f"  Source: {len(rows)}")
    seen = set()
    out  = []

    for i, r in enumerate(rows):
        c = categorize_signup(r, old_db, seen, use_smtp=use_smtp)
        if c["final_status"] == "ACCEPTED":
            seen.add(normalize_email(c["email"]))
        out.append(build_enriched(r, c, "FREE"))
        if (i + 1) % 50 == 0:
            log(f"  Processed {i+1}/{len(rows)}")

    cats     = Counter(r["category"] for r in out)
    accepted = [r for r in out if r["final_status"] == "ACCEPTED"]
    rejected = [r for r in out if r["final_status"] != "ACCEPTED"]

    log(f"  Categories: {dict(cats)}")

    if accepted:
        try:
            accepted = score_rows(accepted)
        except Exception as e:
            log(f"  ML err: {e}")

    all_rows = accepted + rejected
    write_tab_data("Verified_FREE", all_rows)
    log(f"  Wrote {len(all_rows)} ({len(accepted)} A, {len(rejected)} R)")
    return all_rows


def process_uploads(verified_free, use_smtp=True):
    log("=" * 60)
    log("STAGE 2: FIRST_UPLOAD")

    acc, rej = build_signup_maps(verified_free)
    log(f"  Accepted signups: {len(acc)}, Rejected: {len(rej)}")

    ledger = load_ledger()
    log(f"  Ledger: {len(ledger)}")

    rows = read_tab_data("Raw_FIRST_UPLOAD")
    log(f"  Source: {len(rows)}")

    seen = set()
    out  = []

    for i, r in enumerate(rows):
        email = get_email(r)
        norm  = normalize_email(email)

        if norm in seen:
            cat = {
                "final_status": "REJECTED",
                "category":     "DUPLICATE_IN_BATCH",
                "reason":       "same_email_in_batch",
                "email":        email,
                "scraped_date": parse_date_to_ymd(r.get("Upload Date", "")),
            }
        else:
            is_ok, category, reason, e_n, up_ymd, sig = decide_first_upload(
                email, r.get("Upload Date", ""),
                acc, rej, ledger,
                use_smtp=use_smtp,
            )

            # ACCEPTED and ALREADY_COUNTED both count — record in ledger
            if is_ok or category == "ALREADY_COUNTED":
                if e_n and up_ymd and category != "ALREADY_COUNTED":
                    record_first_upload_in_ledger(e_n, up_ymd, ledger)
                seen.add(e_n)

            cat = {
                "final_status": "ACCEPTED" if (is_ok or category == "ALREADY_COUNTED") else "REJECTED",
                "category":     category,
                "reason":       reason,
                "email":        e_n,
                "scraped_date": up_ymd,
                "row_date_used": up_ymd,
                "verify_score": sig.get("verify_score", ""),
            }

        out.append(build_enriched(r, cat, "FIRST_UPLOAD"))

        if (i + 1) % 50 == 0:
            log(f"  Processed {i+1}/{len(rows)}")

    save_ledger(ledger)
    log(f"  Ledger after: {len(ledger)}")

    cats     = Counter(r["category"] for r in out)
    accepted = [r for r in out if r["final_status"] == "ACCEPTED"]
    rejected = [r for r in out if r["final_status"] != "ACCEPTED"]

    log(f"  Categories: {dict(cats)}")

    if accepted:
        try:
            accepted = score_rows(accepted)
        except Exception as e:
            log(f"  ML err: {e}")

    all_rows = accepted + rejected
    write_tab_data("Verified_FIRST_UPLOAD", all_rows)
    log(f"  Wrote {len(all_rows)} ({len(accepted)} A, {len(rejected)} R)")


def process_stripe():
    log("=" * 60)
    log("STAGE 3: STRIPE")
    rows = read_tab_data("Raw_STRIPE")
    log(f"  Source: {len(rows)}")

    out = [build_enriched(r, categorize_stripe(r), "STRIPE") for r in rows]

    cats     = Counter(r["category"] for r in out)
    accepted = [r for r in out if r["final_status"] == "ACCEPTED"]
    rejected = [r for r in out if r["final_status"] != "ACCEPTED"]

    log(f"  Categories: {dict(cats)}")

    if accepted:
        try:
            accepted = score_rows(accepted)
        except Exception as e:
            log(f"  ML err: {e}")

    all_rows = accepted + rejected
    write_tab_data("Verified_STRIPE", all_rows)
    log(f"  Wrote {len(all_rows)} ({len(accepted)} A, {len(rejected)} R)")


def main():
    log("=" * 60)
    log(f"PROCESS DATA v3 — {PROCESS_TS}")
    log("=" * 60)

    use_smtp = os.environ.get("ENABLE_SMTP_VERIFY", "1") == "1"
    log(f"SMTP verification: {'ON' if use_smtp else 'OFF'}")

    reset_caches()
    fetch_disposable_lists()

    if needs_retrain():
        log("Models retraining...")
        try:
            train_models()
        except Exception as e:
            log(f"Train fail: {e}")

    old_db = load_old_database_with_dates()
    log(f"Old DB: {len(old_db)}")

    free = process_free(old_db, use_smtp=use_smtp)
    process_uploads(free, use_smtp=use_smtp)
    process_stripe()

    log("DONE")


if __name__ == "__main__":
    main()
