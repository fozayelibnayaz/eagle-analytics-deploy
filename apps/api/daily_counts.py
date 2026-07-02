"""
daily_counts.py
Counts ONLY final_status=ACCEPTED rows, grouped by actual event date.
Writes Daily_Counts and Monthly_Counts to Sheets.
"""
from collections import defaultdict
from datetime import datetime
from email.utils import parsedate_to_datetime
import re

from sheets_writer import read_tab_data, write_tab_data


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [DailyCounts] {msg}", flush=True)


DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%m/%d/%y, %I:%M %p",
    "%m/%d/%Y, %I:%M %p",
    "%m/%d/%y %I:%M %p",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%y",
    "%m/%d/%Y",
    "%a %b %d %Y",
    "%a %b %d %Y %H:%M:%S",
    "%b %d, %Y",
    "%d %b %Y",
    "%a, %d %b %Y %H:%M:%S %Z",
    "%a, %d %b %Y %H:%M:%S GMT",
]


def parse_date(raw):
    """Parse any date string to YYYY-MM-DD. Returns '' on failure."""
    if not raw or not str(raw).strip():
        return ""
    raw = str(raw).strip()
    if raw in ("—", "-", "N/A", "nan", "None"):
        return ""

    # Try RFC 2822 (used by KPI dashboard "Account Created On")
    try:
        dt = parsedate_to_datetime(raw)
        if dt:
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass

    # Try known formats
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue

    # Regex: YYYY-MM-DD anywhere in string
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except Exception:
            pass

    # Regex: MM/DD/YY or MM/DD/YYYY
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", raw)
    if m:
        try:
            month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if year < 100:
                year += 2000
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except Exception:
            pass

    return ""


def is_accepted(row):
    """Return True only if row is explicitly ACCEPTED."""
    status = str(row.get("final_status", "")).strip().upper()
    return status == "ACCEPTED"


def get_email(row):
    for k in ("Email", "email", "EMAIL", "__email_normalized__", "normalized_email"):
        v = row.get(k, "")
        if v and "@" in str(v):
            return str(v).strip()
    return ""


def get_display(row, source_type):
    """Build display string like 'Username <email>'."""
    email = get_email(row)
    if source_type == "FREE":
        name = row.get("Username", "") or row.get("username", "")
    elif source_type == "UPLOAD":
        name = row.get("Username", "") or row.get("App Name", "")
    else:
        name = row.get("Customer", "") or row.get("customer", "")
    if name and email:
        return f"{name} <{email}>"
    return email or name or "?"


def group_accepted_by_date(rows, date_field, source_type, fallback_field="__scraped_date__"):
    """
    Group ACCEPTED-only rows by date.
    Returns (grouped dict, stats dict)
    """
    grouped = defaultdict(list)
    stats = {"accepted": 0, "rejected": 0, "no_date": 0, "fallback_used": 0}

    for r in rows:
        # ONLY process accepted rows
        if not is_accepted(r):
            stats["rejected"] += 1
            continue
        stats["accepted"] += 1

        # Try primary date field
        date_str = parse_date(r.get(date_field, ""))

        if not date_str:
            # Try row_date_used (set by process_data)
            date_str = parse_date(r.get("row_date_used", ""))

        if not date_str:
            # Try scraped_date fallback
            date_str = parse_date(r.get(fallback_field, ""))

        if not date_str:
            # Try __scraped_at__
            date_str = parse_date(r.get("__scraped_at__", ""))

        if date_str:
            grouped[date_str].append(r)
            if not parse_date(r.get(date_field, "")):
                stats["fallback_used"] += 1
        else:
            stats["no_date"] += 1
            log(f"  WARNING: No date for {get_email(r)} (fields checked: {date_field}, row_date_used, {fallback_field})")

    return grouped, stats


def emails_display(rows, source_type):
    """Build semicolon-joined display string."""
    parts = []
    seen = set()
    for r in rows:
        e = get_email(r)
        if e and e not in seen:
            seen.add(e)
            parts.append(get_display(r, source_type))
    return "; ".join(sorted(parts))


def build_daily_counts_table():
    log("=" * 60)
    log("Building Daily_Counts and Monthly_Counts")
    log("=" * 60)

    # Read verified tabs
    free_rows   = read_tab_data("Verified_FREE")
    upload_rows = read_tab_data("Verified_FIRST_UPLOAD")
    stripe_rows = read_tab_data("Verified_STRIPE")

    log(f"Loaded: free={len(free_rows)}, upload={len(upload_rows)}, stripe={len(stripe_rows)}")

    # Count accepted vs rejected before grouping
    free_acc   = sum(1 for r in free_rows   if is_accepted(r))
    upload_acc = sum(1 for r in upload_rows if is_accepted(r))
    stripe_acc = sum(1 for r in stripe_rows if is_accepted(r))
    log(f"ACCEPTED: free={free_acc}, upload={upload_acc}, stripe={stripe_acc}")

    # Group by date (ACCEPTED only)
    # FREE: primary=Signup_Date (from KPI scraper, normalized), fallback=Account Created On (legacy)
    free_by_date,   free_stats   = group_accepted_by_date(free_rows,   "Signup_Date", "FREE", fallback_field="Account Created On")
    upload_by_date, upload_stats = group_accepted_by_date(upload_rows, "First_Upload_Date",        "UPLOAD", fallback_field="Upload Date")
    # For Stripe: primary=Payment_Date (from Stripe scraper), fallback=First payment/Created
    stripe_by_date, stripe_stats = group_accepted_by_date(stripe_rows, "Payment_Date",            "STRIPE", fallback_field="First payment")

    log(f"Free grouping:   {dict(free_stats)}")
    log(f"Upload grouping: {dict(upload_stats)}")
    log(f"Stripe grouping: {dict(stripe_stats)}")
    log(f"Free dates:   {sorted(free_by_date.keys())}")
    log(f"Upload dates: {sorted(upload_by_date.keys())}")
    log(f"Stripe dates: {sorted(stripe_by_date.keys())}")

    # Union of all dates
    all_dates = sorted({
        d for d in (
            list(free_by_date.keys())
            + list(upload_by_date.keys())
            + list(stripe_by_date.keys())
        )
        if d
    })

    log(f"Total unique dates: {len(all_dates)}")

    # Build daily rows
    daily_dicts = []
    for date in all_dates:
        fr = free_by_date.get(date, [])
        up = upload_by_date.get(date, [])
        st = stripe_by_date.get(date, [])

        daily_dicts.append({
            "Date":                     date,
            "Year":                     date[:4],
            "Month":                    date[:7],
            "SignUps_Accepted":         len(fr),
            "FirstUploads_Accepted":    len(up),
            "PaidSubscribers_Accepted": len(st),
            "SignUp_Details":           emails_display(fr, "FREE"),
            "Upload_Details":           emails_display(up, "UPLOAD"),
            "Paid_Details":             emails_display(st, "STRIPE"),
            "LastUpdated":              datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    log(f"Daily_Counts rows: {len(daily_dicts)}")
    if daily_dicts:
        # Sanity check totals
        t_s = sum(d["SignUps_Accepted"] for d in daily_dicts)
        t_u = sum(d["FirstUploads_Accepted"] for d in daily_dicts)
        t_p = sum(d["PaidSubscribers_Accepted"] for d in daily_dicts)
        log(f"TOTALS CHECK: signups={t_s}, uploads={t_u}, paid={t_p}")
        log(f"  (Should match ACCEPTED counts: free={free_acc}, upload={upload_acc}, stripe={stripe_acc})")

    ok1 = write_tab_data("Daily_Counts", daily_dicts)
    log(f"Daily_Counts write: {'OK' if ok1 else 'FAILED'}")

    # Save local JSON backup for Telegram/alert fallback when Sheets is unavailable
    try:
        import json as _json
        from pathlib import Path as _P
        _P("data_output").mkdir(exist_ok=True)
        (_P("data_output") / "daily_counts.json").write_text(
            _json.dumps(daily_dicts, indent=2, default=str)
        )
        log("Local backup: data_output/daily_counts.json saved")
    except Exception as e:
        log(f"Local backup failed: {e}")

    # Build monthly rollup
    monthly = defaultdict(lambda: {"s": 0, "u": 0, "p": 0})
    for d in daily_dicts:
        m = d["Date"][:7]
        monthly[m]["s"] += d["SignUps_Accepted"]
        monthly[m]["u"] += d["FirstUploads_Accepted"]
        monthly[m]["p"] += d["PaidSubscribers_Accepted"]

    monthly_dicts = []
    for m in sorted(monthly.keys()):
        v = monthly[m]
        monthly_dicts.append({
            "Month":                    m,
            "SignUps_Accepted":         v["s"],
            "FirstUploads_Accepted":    v["u"],
            "PaidSubscribers_Accepted": v["p"],
        })

    log(f"Monthly_Counts rows: {len(monthly_dicts)}")
    ok2 = write_tab_data("Monthly_Counts", monthly_dicts)
    log(f"Monthly_Counts write: {'OK' if ok2 else 'FAILED'}")

    log("Done.")
    return {
        "daily_rows":     len(daily_dicts),
        "monthly_rows":   len(monthly_dicts),
        "free_accepted":  free_acc,
        "upload_accepted": upload_acc,
        "stripe_accepted": stripe_acc,
    }


if __name__ == "__main__":
    result = build_daily_counts_table()
    print(f"\nResult: {result}")
