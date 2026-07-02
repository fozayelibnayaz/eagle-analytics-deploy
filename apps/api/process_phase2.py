"""
from mongo_client import (
    get_db, find_all, find_one, count_docs, count_accepted,
    upsert_many, upsert_one, insert_many, delete_many,
    get_analytics_cache, set_analytics_cache, get_mongo_status
)
from mongo_data_loader import (
    load_daily_kpis, load_signups, load_uploads, load_payments,
    load_tab, read_tab_data, load_master_sheet_tab,
    load_ml_training_data, load_all_ml_training_tabs,
    get_kpi_counts, get_earliest_upload_date,
    sync_daily_kpis, sync_signups, sync_uploads, sync_payments,
    load_linkedin_posts, load_linkedin_followers_daily,
    load_linkedin_posts_daily, load_linkedin_highlights,
    get_connection_status
)

PHASE 2 ORCHESTRATOR v2
- Skips internal Eagle3D emails
- Skips rows where Lead Source contains 'internal', 'test', etc.
- Robust column detection (works even if headers row got lost)
"""
# import pandas as pd
from datetime import datetime

from config import (
    GOOGLE_CREDS_FILE, MASTER_SHEET_URL,
    INTERNAL_EMAIL_DOMAINS, SKIP_LEAD_SOURCE_KEYWORDS,
)
from email_validator_engine import validate_batch, normalize_email
from dedup_engine import fetch_historical_emails

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

RUN_TS = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _client():
    creds = None  # MIGRATED: no credentials needed, scopes=SCOPES)
    return None  # MIGRATED: no sheets client needed


def get_or_create_ws(sh, title, rows=2000, cols=25):
    try:
        return sh.worksheet(title)
    except gspread.WorksheetNotFound:
        return sh.add_worksheet(title=title, rows=rows, cols=cols)


def detect_columns(headers, rows):
    """
    Find email and lead source columns. Returns dict of column indices.
    If headers look bad, also tries to detect the email column by content.
    """
    info = {"email": -1, "lead_source": -1, "username": -1, "phone": -1, "created": -1}

    # Try by header name first
    for i, h in enumerate(headers):
        h_low = (h or "").strip().lower()
        if "email" in h_low and info["email"] == -1:
            info["email"] = i
        elif "lead" in h_low and "source" in h_low:
            info["lead_source"] = i
        elif "user" in h_low or "name" in h_low:
            info["username"] = i
        elif "phone" in h_low:
            info["phone"] = i
        elif "created" in h_low or "account" in h_low or "date" in h_low:
            info["created"] = i

    # Fallback: if no email column found via header, scan first 5 rows for any
    # column that has @ in its values
    if info["email"] == -1 and rows:
        n_cols = max(len(r) for r in rows[:5])
        for col_idx in range(n_cols):
            sample = [r[col_idx] for r in rows[:10] if col_idx < len(r)]
            at_count = sum(1 for s in sample if "@" in s)
            if at_count >= 2:
                info["email"] = col_idx
                log(f"   (Auto-detected email column at index {col_idx})")
                break

    return info


def should_skip_internal(email, lead_source):
    """Return (skip, reason)."""
    email_low = (email or "").strip().lower()
    for d in INTERNAL_EMAIL_DOMAINS:
        if email_low.endswith("@" + d.lower()):
            return True, f"Internal domain ({d})"

    ls_low = (lead_source or "").strip().lower()
    for kw in SKIP_LEAD_SOURCE_KEYWORDS:
        if kw.lower() in ls_low:
            return True, f"Lead source contains '{kw}'"

    return False, ""


def process_tab(sh, raw_tab_name, history):
    log("=" * 60)
    log(f"Processing: {raw_tab_name}")
    log("=" * 60)

    try:
        ws = sh.worksheet(raw_tab_name)
    except gspread.WorksheetNotFound:
        log(f"   Tab '{raw_tab_name}' not found. Skipping.")
        return None

    data = ws.get_all_values()
    if not data or len(data) < 1:
        log(f"   No data in '{raw_tab_name}'.")
        return None

    headers = data[0]
    rows = data[1:] if len(data) > 1 else []
    log(f"   Loaded {len(rows)} raw rows.")
    log(f"   Headers: {headers}")

    cols = detect_columns(headers, rows)
    log(f"   Detected columns: {cols}")

    if cols["email"] == -1:
        log(f"   Could not find email column even after auto-detect. Skipping.")
        return None

    email_idx = cols["email"]
    lead_idx = cols["lead_source"]

    # Filter & dedup
    seen_norms = {}
    skipped_internal = 0
    skip_reasons = {}

    for row in rows:
        if email_idx >= len(row):
            continue
        email = row[email_idx].strip()
        if not email or "@" not in email:
            continue

        lead_source = row[lead_idx].strip() if (lead_idx != -1 and lead_idx < len(row)) else ""

        skip, reason = should_skip_internal(email, lead_source)
        if skip:
            skipped_internal += 1
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue

        norm = normalize_email(email)
        seen_norms[norm] = row

    log(f"   Skipped (internal/test): {skipped_internal}")
    for r, c in skip_reasons.items():
        log(f"      - {r}: {c}")

    deduped_rows = list(seen_norms.values())
    log(f"   After in-sheet dedup: {len(deduped_rows)} unique emails to validate.")

    if not deduped_rows:
        log("   Nothing to validate.")
        return {"tab": raw_tab_name, "total": 0, "accepted": 0, "disposable": 0,
                "fake_domain": 0, "duplicates": 0, "internal_skipped": skipped_internal,
                "suspicious": 0}

    emails = [r[email_idx] for r in deduped_rows]
    validation_results = validate_batch(emails)

    enriched = []
    for raw_row, vres in zip(deduped_rows, validation_results):
        padded = raw_row + [""] * (len(headers) - len(raw_row))
        norm = vres["normalized"]
        is_first = norm not in history if norm else False

        row_dict = {headers[i] if i < len(headers) else f"col_{i}": padded[i]
                    for i in range(len(padded))}
        row_dict["normalized_email"] = norm
        row_dict["valid_syntax"] = vres["valid_syntax"]
        row_dict["is_disposable"] = vres["is_disposable"]
        row_dict["is_free_provider"] = vres["is_free_provider"]
        row_dict["has_mx"] = vres["has_mx"]
        row_dict["is_suspicious"] = vres.get("is_suspicious", False)
        row_dict["email_verdict"] = vres["verdict"]
        row_dict["verdict_reason"] = vres["reason"]
        row_dict["is_first_time_ever"] = is_first

        if vres["verdict"] == "VALID" and is_first:
            row_dict["final_status"] = "ACCEPTED"
            row_dict["rejection_reason"] = ""
        else:
            row_dict["final_status"] = "REJECTED"
            if vres["verdict"] != "VALID":
                row_dict["rejection_reason"] = vres["reason"]
            else:
                row_dict["rejection_reason"] = "Already in old database"
        row_dict["processed_at"] = RUN_TS
        enriched.append(row_dict)

    accepted = [e for e in enriched if e["final_status"] == "ACCEPTED"]
    disposable = [e for e in enriched if e["is_disposable"]]
    fake_domain = [e for e in enriched if e["email_verdict"] == "FAKE_DOMAIN"]
    suspicious = [e for e in enriched if e["email_verdict"] == "SUSPICIOUS"]
    rejected_dup = [e for e in enriched if e["email_verdict"] == "VALID" and not e["is_first_time_ever"]]
    bad_syntax = [e for e in enriched if not e["valid_syntax"]]

    log("")
    log(f"   📊 Results for {raw_tab_name}:")
    log(f"      Internal/test skipped:  {skipped_internal}")
    log(f"      Total validated:        {len(enriched)}")
    log(f"      ✅ ACCEPTED (new):      {len(accepted)}")
    log(f"      ❌ Disposable:          {len(disposable)}")
    log(f"      ❌ Suspicious pattern:  {len(suspicious)}")
    log(f"      ❌ Fake domain (no MX): {len(fake_domain)}")
    log(f"      ❌ Bad syntax:          {len(bad_syntax)}")
    log(f"      ❌ Already in DB:       {len(rejected_dup)}")

    # Show a few accepted samples
    if accepted:
        log(f"   Sample accepted: {[e['normalized_email'] for e in accepted[:5]]}")
    if disposable:
        log(f"   Sample disposable: {[e['normalized_email'] for e in disposable[:5]]}")

    verified_name = raw_tab_name.replace("Raw_", "Verified_")
    vws = get_or_create_ws(sh, verified_name, rows=max(2000, len(enriched) + 100))
    vws.clear()

    if enriched:
        df = pd.DataFrame(enriched)
        values = [df.columns.tolist()] + df.astype(str).values.tolist()
        vws.update(range_name="A1", values=values, value_input_option="USER_ENTERED")
        log(f"   💾 Wrote {len(enriched)} rows to '{verified_name}'.")

    return {
        "tab": raw_tab_name,
        "total": len(enriched),
        "accepted": len(accepted),
        "disposable": len(disposable),
        "fake_domain": len(fake_domain),
        "suspicious": len(suspicious),
        "duplicates": len(rejected_dup),
        "internal_skipped": skipped_internal,
    }


def write_phase2_summary(sh, results):
    ws = get_or_create_ws(sh, "Phase2_Summary", rows=2000, cols=15)
    existing = ws.get_all_values()
    if not existing:
        ws.update(range_name="A1", values=[[
            "Timestamp", "Tab", "Total_Validated", "Accepted_New",
            "Disposable", "Suspicious", "Fake_Domain", "Duplicate_In_DB", "Internal_Skipped"
        ]])
    rows = []
    for r in results:
        if r is None:
            continue
        rows.append([
            RUN_TS, r["tab"], r["total"], r["accepted"],
            r["disposable"], r.get("suspicious", 0), r["fake_domain"],
            r["duplicates"], r.get("internal_skipped", 0),
        ])
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        log("💾 Summary appended to 'Phase2_Summary'.")


def main():
    log("=" * 65)
    log("  PHASE 2 v2 - Email Validation + Deduplication + Filters")
    log("=" * 65)

    gc = _client()
    sh = None  # MIGRATED: use load_tab() from mongo_data_loader
    log(f"✅ Opened master sheet: '{sh.title}'")

    history = fetch_historical_emails()

    PRIORITY_TABS = ["Raw_FREE", "Raw_FIRST_UPLOAD", "Raw_STRIPE", "Raw_PAID", "Raw_500_MIN"]

    results = []
    for raw_tab in PRIORITY_TABS:
        try:
            r = process_tab(sh, raw_tab, history)
            results.append(r)
        except Exception as e:
            log(f"❌ Error processing {raw_tab}: {e}")
            import traceback
            traceback.print_exc()

    write_phase2_summary(sh, results)

    log("=" * 65)
    log("✅ PHASE 2 COMPLETE")
    log("=" * 65)


if __name__ == "__main__":
    main()
