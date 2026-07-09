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

dedup_engine.py
Loads BOTH old DB tabs:
  - Enterprise-Inbound-Leads (lead source data)
  - All Time Data (Stripe customer master record)

For each email, stores all known dates (signup/created).
Implements 90-day rule for first-upload validation.
"""

import os
import re
import json
from pathlib import Path
from datetime import datetime
from email.utils import parsedate_to_datetime
from collections import defaultdict

from mongo_client import (
    get_db, find_all, find_one, count_docs, count_accepted,
    upsert_many, upsert_one, insert_many, delete_many,
    get_analytics_cache, set_analytics_cache, get_mongo_status
)
from mongo_data_loader import (
    load_daily_kpis, load_signups, load_uploads, load_payments,
    load_tab, read_tab_data, get_kpi_counts, get_earliest_upload_date,
    sync_daily_kpis, sync_signups, sync_uploads, sync_payments,
    load_linkedin_posts, load_linkedin_followers_daily,
    load_linkedin_posts_daily, load_linkedin_highlights,
    get_connection_status, load_all_ml_training_tabs
)

DATA_DIR = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)

OLD_DB_CACHE = DATA_DIR / "old_db_with_dates.json"
OLD_DB_URL = os.environ.get(
    "OLD_DATABASE_SHEET_URL",
    "https://docs.google.com/spreadsheets/d/1tEaUA2hGxuHw3E9n0TzyaEUz9MIlpQGoZy-WQz0NwSc"
)

# How many days between signup and upload to count as legitimate "first upload"
FIRST_UPLOAD_GRACE_DAYS = 90


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [Dedup] {msg}", flush=True)


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


DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%m/%d/%y, %I:%M %p",
    "%m/%d/%Y, %I:%M %p",
    "%a %b %d %Y",
    "%a %b %d %Y %H:%M:%S",
    "%b %d, %Y",
    "%d %b %Y",
    "%d/%m/%Y",
]


def parse_date(raw):
    """Parse any date format. Returns YYYY-MM-DD or empty."""
    if not raw or not str(raw).strip():
        return ""
    raw = str(raw).strip()
    if raw in ("—", "-", "N/A", "n/a"):
        return ""
    
    try:
        dt = parsedate_to_datetime(raw)
        if dt:
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except Exception:
            pass
    
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


def load_old_database_with_dates(force_refresh=False):
    """
    Load old DB. Returns {email: {"dates": [list], "earliest": "YYYY-MM-DD"}}.
    Loads both Enterprise + All Time Data tabs.
    Cached for 7 days.
    """
    if not force_refresh and OLD_DB_CACHE.exists():
        try:
            age_hours = (datetime.now().timestamp() - OLD_DB_CACHE.stat().st_mtime) / 3600
            if age_hours < 24 * 7:
                with open(OLD_DB_CACHE) as f:
                    cache = json.load(f)
                log(f"Using cached old DB: {len(cache)} unique emails")
                return cache
        except Exception as e:
            log(f"Cache read error: {e}")
    
    log(f"Fetching old DB from {OLD_DB_URL[:60]}...")
    
    # email -> set of dates
    email_dates = defaultdict(set)
    
    try:
        from sheets_writer import _get_client
        gc, _ = _get_client()
        ss = None  # MIGRATED: use load_tab() from mongo_data_loader
        
        for ws in ss.worksheets():
            log(f"  Reading tab: {ws.title}")
            try:
                all_values = ws.get_all_values()
                if not all_values:
                    log(f"    Empty")
                    continue
                
                headers = all_values[0]
                data_rows = all_values[1:]
                
                # Find email + date columns
                email_col_idx = None
                date_col_idx = None
                
                for i, h in enumerate(headers):
                    h_lower = (h or "").lower().strip()
                    if email_col_idx is None and h_lower == "email":
                        email_col_idx = i
                    if date_col_idx is None:
                        # All Time Data: "Created (UTC)"
                        # Enterprise: "Created on"
                        if any(k in h_lower for k in ["created on", "created (utc)", "created"]):
                            if "called" not in h_lower:
                                date_col_idx = i
                
                if email_col_idx is None:
                    log(f"    No email column - skipping")
                    continue
                
                log(f"    Email col: {email_col_idx} ('{headers[email_col_idx]}')")
                if date_col_idx is not None:
                    log(f"    Date col: {date_col_idx} ('{headers[date_col_idx]}')")
                
                tab_added = 0
                for row in data_rows:
                    if email_col_idx >= len(row):
                        continue
                    raw_email = row[email_col_idx]
                    if not raw_email or "@" not in str(raw_email):
                        continue
                    
                    email = normalize_email(raw_email)
                    if not email:
                        continue
                    
                    date_str = ""
                    if date_col_idx is not None and date_col_idx < len(row):
                        raw_date = row[date_col_idx]
                        date_str = parse_date(raw_date)
                    
                    if date_str:
                        email_dates[email].add(date_str)
                    else:
                        email_dates[email].add("__no_date__")
                    
                    tab_added += 1
                
                log(f"    Added {tab_added} entries from {ws.title}")
            
            except Exception as e:
                log(f"    Tab error: {e}")
        
        # Build final structure: {email: {"dates": [list], "earliest": str}}
        result = {}
        for email, dates in email_dates.items():
            real_dates = sorted([d for d in dates if d != "__no_date__"])
            result[email] = {
                "dates": sorted(list(dates)),
                "earliest": real_dates[0] if real_dates else "",
            }
        
        try:
            with open(OLD_DB_CACHE, "w") as f:
                json.dump(result, f, indent=2)
            log(f"Cached to {OLD_DB_CACHE}")
        except Exception as e:
            log(f"Cache save error: {e}")
        
        log(f"Total old DB: {len(result)} unique emails")
        return result
    
    except Exception as e:
        log(f"Old DB fetch failed: {e}")
        if OLD_DB_CACHE.exists():
            try:
                with open(OLD_DB_CACHE) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}


def is_duplicate_signup(email, scraped_date, old_db):
    """
    For SIGN-UPS:
    Returns (is_duplicate, reason)
    
    Rules:
      - Email NOT in old DB                          -> NEW
      - Email in old DB, scraped_date matches one    -> SAME (not dup)
      - Email in old DB, different date              -> DUPLICATE
    """
    norm = normalize_email(email)
    if not norm:
        return False, "no_email"
    
    if norm not in old_db:
        return False, "new_email"
    
    entry = old_db[norm]
    old_dates = entry.get("dates", [])
    
    if not scraped_date:
        return False, "no_scrape_date"
    
    if scraped_date in old_dates:
        return False, "same_date_match"
    
    real_dates = [d for d in old_dates if d != "__no_date__"]
    if not real_dates:
        return False, "old_db_has_no_real_dates"
    
    return True, f"existed_on:{','.join(real_dates[:3])}"


def is_legitimate_first_upload(email, upload_date, old_db, grace_days=FIRST_UPLOAD_GRACE_DAYS):
    """
    For FIRST UPLOAD:
    Returns (is_legitimate, reason)
    
    Rules:
      - Email NOT in old DB                          -> LEGITIMATE (truly new user)
      - Email in old DB, signup < 90 days ago       -> LEGITIMATE (within grace period)
      - Email in old DB, signup > 90 days ago       -> NOT LEGITIMATE (re-upload)
    """
    norm = normalize_email(email)
    if not norm:
        return True, "no_email"
    
    if not upload_date:
        return True, "no_upload_date"
    
    if norm not in old_db:
        return True, "new_user_no_history"
    
    entry = old_db[norm]
    earliest_signup = entry.get("earliest", "")
    
    if not earliest_signup:
        return True, "in_old_db_but_no_date"
    
    # Calculate days between earliest signup and upload
    try:
        signup_dt = datetime.strptime(earliest_signup, "%Y-%m-%d")
        upload_dt = datetime.strptime(upload_date, "%Y-%m-%d")
        days_between = (upload_dt - signup_dt).days
        
        if days_between > grace_days:
            return False, f"signed_up_{days_between}d_ago_>{grace_days}d_grace"
        else:
            return True, f"signed_up_{days_between}d_ago_within_grace"
    
    except Exception as e:
        return True, f"date_compare_error:{e}"


# Backward compatibility
def load_old_database_emails():
    full = load_old_database_with_dates()
    return {email: True for email in full.keys()}


def is_duplicate_different_date(email, scraped_date, old_db):
    """Backward compatible - calls is_duplicate_signup."""
    return is_duplicate_signup(email, scraped_date, old_db)


def deduplicate(rows, old_db_emails=None, scraped_date_field=None):
    """Backward compatible - basic dedup for existing code."""
    if old_db_emails is None:
        old_db_emails = {}
    
    seen_in_batch = set()
    unique = []
    duplicates = []
    
    for row in rows:
        email = ""
        for k in ("Email", "email", "EMAIL", "__email_normalized__"):
            if k in row and row[k] and "@" in str(row[k]):
                email = str(row[k]).strip()
                break
        
        if not email:
            duplicates.append({**row, "__dedup_status__": "NO_EMAIL"})
            continue
        
        normalized = normalize_email(email)
        scraped_date = ""
        if scraped_date_field and scraped_date_field in row:
            scraped_date = parse_date(row[scraped_date_field])
        
        if normalized in seen_in_batch:
            duplicates.append({**row, "__dedup_status__": "DUPLICATE_IN_BATCH"})
            continue
        
        seen_in_batch.add(normalized)
        
        is_dup, reason = is_duplicate_signup(normalized, scraped_date, old_db_emails)
        if is_dup:
            duplicates.append({**row, "__dedup_status__": "DUPLICATE_DIFFERENT_DATE",
                               "__dup_reason__": reason})
        else:
            unique.append({**row, "__dedup_status__": "NEW",
                           "__dedup_reason__": reason})
    
    return unique, duplicates


if __name__ == "__main__":
    log("Loading old DB with dates from BOTH tabs...")
    db = load_old_database_with_dates(force_refresh=True)
    log(f"\nTotal: {len(db)} emails")
    
    # Test specific cases
    test_emails = [
        "wolfgang.bernecker@tridonic.com",
        "eirik.murbraech@ramboll.no",
    ]
    
    for email in test_emails:
        norm = normalize_email(email)
        if norm in db:
            entry = db[norm]
            log(f"\n{email}:")
            log(f"  Dates: {entry['dates']}")
            log(f"  Earliest: {entry['earliest']}")
        else:
            log(f"\n{email}: NOT in old DB")
