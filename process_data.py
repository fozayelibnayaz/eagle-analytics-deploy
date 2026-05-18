"""
process_data.py
Validates ALL rows. Date-aware duplicate detection.
SPECIAL CASE for FIRST UPLOAD: 90-day rule (signup-to-upload gap)
SPECIAL CASE for STRIPE: only check total spend > 0
"""
import csv
import json
import os
import re
from pathlib import Path
from datetime import datetime
from collections import Counter

from sheets_writer import write_tab_data, read_tab_data
from email_validator_engine import (
    check_syntax, check_disposable, check_skip, check_mx,
    DISPOSABLE_DOMAINS, INTERNAL_DOMAINS, INTERNAL_KEYWORDS
)
from dedup_engine import (
    load_old_database_with_dates, is_duplicate_signup,
    normalize_email, parse_date
)
from upload_registry import (
    load_registry, bootstrap_registry, is_truly_first_upload, record_first_upload
)
from ml_intelligence import score_rows, needs_retrain, train_models

DATA_DIR = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)
PROCESS_TS = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [Process] {msg}", flush=True)


def get_email(row):
    for k in ("Email", "email", "EMAIL"):
        if k in row and row[k] and "@" in str(row[k]):
            return str(row[k]).strip().lower()
    return ""


def get_scraped_date(row, source_type):
    """Get the actual date for this row based on source type."""
    if source_type == "FREE":
        return parse_date(row.get("Account Created On", ""))
    elif source_type == "FIRST_UPLOAD":
        return parse_date(row.get("Upload Date", ""))
    elif source_type == "STRIPE":
        for f in ("First payment", "Created"):
            if f in row and row[f]:
                d = parse_date(row[f])
                if d:
                    return d
        return ""
    return ""



def parse_amount(val):
    if not val:
        return 0.0
    s = str(val).strip()
    if not s or s in ("—", "-", "N/A"):
        return 0.0
    s = re.sub(r"[$,€£¥\s]", "", s)
    try:
        return float(s)
    except Exception:
        return 0.0


def categorize_stripe_row(row):
    """STRIPE: only accept if Total spend > 0.
    Prefer the 'First payment' date for attribution; if missing, fall back
    to the customer 'Created' date. This ensures paid customers are counted
    in the month they first paid when available, otherwise in their
    account creation month as a fallback.
    """
    email = get_email(row)
    spend_raw = row.get("Total spend", "") or row.get("total_spend", "")
    amount = parse_amount(spend_raw)

    # Only count this as a paid customer if Total Spend > 0.
    if amount > 0:
        # Prefer First payment, fall back to Created
        first_payment_date = parse_date(row.get("First payment", ""))
        created_date = parse_date(row.get("Created", ""))
        row_date = first_payment_date or created_date
        if row_date:
            return {
                "final_status": "ACCEPTED",
                "category": "ACCEPTED",
                "reason": f"paid_${amount:.2f}",
                "email": email,
                "amount": amount,
                "scraped_date": row_date,
                "row_date_used": row_date
            }
        else:
            # Has spend but no usable date → reject for audit
            return {
                "final_status": "REJECTED",
                "category": "NO_DATE",
                "reason": "total_spend > 0 but no First payment or Created date",
                "email": email,
                "amount": amount,
                "scraped_date": "",
                "row_date_used": ""
            }
    else:
        # Total spend is 0 or empty → not a paid customer
        return {
            "final_status": "REJECTED",
            "category": "ZERO_SPEND",
            "reason": "total_spend = $0 (not paid)",
            "email": email,
            "amount": 0.0,
            "scraped_date": "",
            "row_date_used": ""
        }


def categorize_signup_row(row, check_dns, old_db, seen_in_batch):
    """SIGN-UP validation: full check + date-aware dedup."""
    email = get_email(row)
    if not email:
        return {"final_status": "REJECTED", "category": "NO_EMAIL", "reason": "no email", "email": ""}
    
    ok, reason = check_syntax(email)
    if not ok:
        return {"final_status": "REJECTED", "category": "INVALID_FORMAT", "reason": reason, "email": email}
    
    ok, reason = check_skip(email)
    if not ok:
        cat = "INTERNAL" if "internal" in reason.lower() else "SUSPICIOUS"
        return {"final_status": "REJECTED", "category": cat, "reason": reason, "email": email}
    
    ok, reason = check_disposable(email)
    if not ok:
        return {"final_status": "REJECTED", "category": "DISPOSABLE", "reason": reason, "email": email}
    
    lead_source = ""
    for k, v in row.items():
        if "lead" in k.lower() or "source" in k.lower():
            if v:
                lead_source = str(v).lower()
                break
    
    for kw in ["internal", "test", "demo", "fake", "sample"]:
        if kw in lead_source:
            return {"final_status": "REJECTED", "category": "INTERNAL",
                    "reason": f"lead_source contains '{kw}'", "email": email}
    
    if check_dns:
        domain = email.split("@")[-1]
        ok, reason = check_mx(domain)
        if not ok:
            return {"final_status": "REJECTED", "category": "INVALID_DOMAIN", "reason": reason, "email": email}
    
    scraped_date = get_scraped_date(row, "FREE")
    normalized = normalize_email(email)
    
    if normalized in seen_in_batch:
        return {"final_status": "REJECTED", "category": "DUPLICATE_IN_BATCH",
                "reason": "same email in batch", "email": email}
    
    is_dup, dup_reason = is_duplicate_signup(normalized, scraped_date, old_db)
    if is_dup:
        return {"final_status": "REJECTED", "category": "DUPLICATE_DIFFERENT_DATE",
                "reason": dup_reason, "email": email, "scraped_date": scraped_date}
    
    in_old_db = "yes" if normalized in old_db else "no"
    return {"final_status": "ACCEPTED", "category": "ACCEPTED",
            "reason": dup_reason, "email": email,
            "in_old_db": in_old_db, "scraped_date": scraped_date}


def categorize_upload_row(row, check_dns, old_db, seen_in_batch, upload_history=None):
    """FIRST UPLOAD: validate + check using account-creation vs upload-date logic."""
    email = get_email(row)
    if not email:
        return {"final_status": "REJECTED", "category": "NO_EMAIL", "reason": "no email", "email": ""}
    
    ok, reason = check_syntax(email)
    if not ok:
        return {"final_status": "REJECTED", "category": "INVALID_FORMAT", "reason": reason, "email": email}
    
    ok, reason = check_skip(email)
    if not ok:
        cat = "INTERNAL" if "internal" in reason.lower() else "SUSPICIOUS"
        return {"final_status": "REJECTED", "category": cat, "reason": reason, "email": email}
    
    ok, reason = check_disposable(email)
    if not ok:
        return {"final_status": "REJECTED", "category": "DISPOSABLE", "reason": reason, "email": email}
    
    if check_dns:
        domain = email.split("@")[-1]
        ok, reason = check_mx(domain)
        if not ok:
            return {"final_status": "REJECTED", "category": "INVALID_DOMAIN", "reason": reason, "email": email}
    
    upload_date = get_scraped_date(row, "FIRST_UPLOAD")
    normalized = normalize_email(email)

    if normalized in seen_in_batch:
        return {"final_status": "REJECTED", "category": "DUPLICATE_IN_BATCH",
                "reason": "same email in this scrape", "email": email}

    # Use upload history (one-way ratchet). Prefer the passed-in upload_history
    # registry if provided, otherwise fall back to the old_db registry lookup.
    history_source = upload_history if upload_history is not None else old_db
    is_first, reason = is_truly_first_upload(normalized, upload_date, history_source)

    # If history says this was already counted today, accept it (idempotent).
    if not is_first:
        if reason.startswith("already_counted_today"):
            in_old_db = "yes" if normalized in old_db else "no"
            return {"final_status": "ACCEPTED", "category": "ACCEPTED",
                    "reason": reason, "email": email, "in_old_db": in_old_db, "scraped_date": upload_date}
        category = "NOT_DETERMINED" if reason.startswith("not_determined") else "REPEAT_UPLOAD"
        return {"final_status": "REJECTED", "category": category,
                "reason": reason, "email": email, "scraped_date": upload_date}

    # Record this in registry to prevent double-counting on future runs
    record_first_upload(normalized, upload_date, reason)

    in_old_db = "yes" if normalized in old_db else "no"
    return {"final_status": "ACCEPTED", "category": "ACCEPTED",
            "reason": reason, "email": email,
            "in_old_db": in_old_db, "scraped_date": upload_date}


def process_tab(raw_tab, verified_tab, source_type, old_db, check_dns=True, upload_history=None):
    log("-" * 60)
    log(f"PROCESSING: {raw_tab} -> {verified_tab} (source={source_type})")
    
    source = read_tab_data(raw_tab)
    log(f"  Source rows: {len(source)}")
    
    if not source:
        return {"raw_tab": raw_tab, "source": 0, "accepted": 0, "rejected": 0}
    
    seen_in_batch = set()
    categorized = []
    
    if source_type == "STRIPE":
        log(f"  STRIPE mode: checking total spend > $0")
        for row in source:
            cat = categorize_stripe_row(row)
            enriched = build_enriched(row, cat, source_type)
            categorized.append(enriched)
    
    elif source_type == "FREE":
        log(f"  FREE signup mode: full validation + date-aware dedup")
        for row in source:
            cat = categorize_signup_row(row, check_dns, old_db, seen_in_batch)
            if cat["final_status"] == "ACCEPTED":
                seen_in_batch.add(normalize_email(cat["email"]))
            enriched = build_enriched(row, cat, source_type)
            categorized.append(enriched)
    
    elif source_type == "FIRST_UPLOAD":
        registry = upload_history if upload_history is not None else load_registry()
        if not registry:
            log("  Registry empty - running bootstrap...")
            registry = bootstrap_registry(force=False)
        log(f"  FIRST UPLOAD mode: registry has {len(registry)} known uploaders")
        
        for row in source:
            cat = categorize_upload_row(row, check_dns, old_db, seen_in_batch, upload_history=registry)
            if cat["final_status"] == "ACCEPTED":
                seen_in_batch.add(normalize_email(cat["email"]))
            enriched = build_enriched(row, cat, source_type)
            categorized.append(enriched)
        
        final_registry = load_registry()
        log(f"  Registry now: {len(final_registry)} entries")
    
    cats = Counter(r["category"] for r in categorized)
    log(f"  Categories breakdown:")
    for c, n in cats.most_common():
        log(f"    {c:30s}: {n}")
    
    accepted = [r for r in categorized if r["final_status"] == "ACCEPTED"]
    rejected = [r for r in categorized if r["final_status"] == "REJECTED"]
    
    log(f"  ACCEPTED: {len(accepted)}, REJECTED: {len(rejected)}")
    
    if accepted:
        log(f"  ML scoring {len(accepted)} accepted rows...")
        try:
            accepted = score_rows(accepted)
        except Exception as e:
            log(f"  ML scoring error: {e}")
    
    all_rows = accepted + rejected
    
    if rejected:
        rejected_csv = DATA_DIR / f"Rejected_{verified_tab}.csv"
        try:
            fields = sorted({k for r in rejected for k in r.keys()})
            with open(rejected_csv, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                w.writerows(rejected)
        except Exception as e:
            log(f"  Rejected CSV save: {e}")
    
    log(f"  Writing {len(all_rows)} rows to {verified_tab}...")
    ok = write_tab_data(verified_tab, all_rows)
    log(f"  Sheets write: {'OK' if ok else 'FAILED'}")
    
    return {
        "raw_tab": raw_tab, "verified_tab": verified_tab,
        "source": len(source), "accepted": len(accepted),
        "rejected": len(rejected), "categories": dict(cats),
    }


def build_enriched(row, cat, source_type):
    enriched = dict(row)
    enriched["final_status"]          = cat["final_status"]
    enriched["category"]              = cat["category"]
    enriched["email_verdict"]         = cat["category"]
    enriched["__rejection_reason__"]  = cat.get("reason", "")
    enriched["__email_normalized__"]  = cat.get("email", "")
    enriched["__scraped_date__"]      = cat.get("scraped_date", "")
    enriched["row_date_used"]         = cat.get("row_date_used", "")
    enriched["__processed_at__"]      = PROCESS_TS
    if source_type == "STRIPE":
        enriched["__amount__"] = cat.get("amount", 0.0)
    enriched["__in_old_db__"] = cat.get("in_old_db", "")
    enriched["__validation_status__"] = (
        "verified" if cat["final_status"] == "ACCEPTED" else "rejected"
    )
    return enriched


def main():
    log("=" * 60)
    log(f"PROCESS DATA - {PROCESS_TS}")
    log("=" * 60)
    
    if needs_retrain():
        log("Models need retraining...")
        try:
            train_models()
        except Exception as e:
            log(f"Training failed: {e}")
    
    log("Loading old database (both tabs)...")
    old_db = load_old_database_with_dates()
    log(f"Old DB: {len(old_db)} unique emails")
    
    
    
    TAB_MAP = [
        ("Raw_FREE",         "Verified_FREE",          "FREE"),
        ("Raw_FIRST_UPLOAD", "Verified_FIRST_UPLOAD",  "FIRST_UPLOAD"),
        ("Raw_STRIPE",       "Verified_STRIPE",        "STRIPE"),
    ]
    
    check_mx_for = {"Raw_FREE": True, "Raw_FIRST_UPLOAD": False, "Raw_STRIPE": False}
    
    results = []
    # Load upload registry once and pass into processing to keep behavior deterministic
    upload_history = load_registry()
    for raw_tab, verified_tab, source_type in TAB_MAP:
        try:
            r = process_tab(raw_tab, verified_tab, source_type, old_db,
                            check_dns=check_mx_for.get(raw_tab, False),
                            upload_history=upload_history)
            results.append(r)
        except Exception as e:
            log(f"Error processing {raw_tab}: {e}")
            import traceback
            traceback.print_exc()
    
    log("=" * 60)
    log("FINAL SUMMARY")
    log("=" * 60)
    for r in results:
        raw = r.get("raw_tab", "?")
        src = r.get("source", 0)
        acc = r.get("accepted", 0)
        rej = r.get("rejected", 0)
        log(f"  {raw:25s}: {src:>4} src -> {acc:>4} ACCEPTED, {rej:>4} REJECTED")
        for cat, n in (r.get("categories") or {}).items():
            log(f"      {cat:30s}: {n}")
    
    return results


if __name__ == "__main__":
    main()
