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

build_reference_stores.py
Reads the database sheet's two tabs and creates:
  - data_output/historical_accounts.json (from Enterprise-Inbound-Leads)
  - data_output/historical_paid.json (from All Time Data)
"""

import os
import json
import tempfile
from pathlib import Path
from datetime import datetime
from email.utils import parsedate_to_datetime
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


# 
DATA_DIR = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)

DB_SHEET_URL = "https://docs.google.com/spreadsheets/d/1tEaUA2hGxuHw3E9n0TzyaEUz9MIlpQGoZy-WQz0NwSc/edit"

HISTORICAL_ACCOUNTS_FILE = DATA_DIR / "historical_accounts.json"
HISTORICAL_PAID_FILE = DATA_DIR / "historical_paid.json"


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [RefStores] {msg}", flush=True)


def get_creds_file():
    if os.path.exists("google_creds.json"):
        return "google_creds.json"
    raw = os.environ.get("GOOGLE_CREDS_JSON", "")
    if raw:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(raw); tmp.close()
        return tmp.name
    raise FileNotFoundError("No google_creds.json or GOOGLE_CREDS_JSON")


def get_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = None  # MIGRATED: no credentials needed, scopes=scopes)
    return None  # MIGRATED: no sheets client needed


def normalize_email(email):
    e = (email or "").strip().lower()
    if "@" not in e: return ""
    local, domain = e.split("@", 1)
    if "+" in local: local = local.split("+")[0]
    if domain in ("gmail.com", "googlemail.com"):
        local = local.replace(".", "")
    return f"{local}@{domain}"


def parse_date_to_ymd(raw):
    if not raw or str(raw).strip() in ("", "-", "—", "nan", "None"):
        return ""
    s = str(raw).strip()
    try:
        dt = parsedate_to_datetime(s)
        if dt: return dt.strftime("%Y-%m-%d")
    except: pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try: return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except: pass
    return ""


def parse_float(val):
    s = str(val or "").strip()
    if s in ("", "-", "—", "nan", "None"): return 0.0
    try: return float(s.replace(",", ""))
    except: return 0.0


def parse_int(val):
    s = str(val or "").strip()
    if s in ("", "-", "—", "nan", "None"): return 0
    try: return int(float(s))
    except: return 0


def make_unique_headers(headers):
    """Fix duplicate column names by appending _2, _3 etc."""
    out, seen = [], {}
    for i, h in enumerate(headers):
        name = str(h).strip() if h else f"col_{i}"
        if not name: name = f"col_{i}"
        if name in seen:
            seen[name] += 1
            out.append(f"{name}_{seen[name]}")
        else:
            seen[name] = 1
            out.append(name)
    return out


def worksheet_to_dict_rows(ws):
    """Read worksheet bypassing duplicate-header bug in gspread."""
    values = ws.get_all_values()
    if not values: return []
    headers = make_unique_headers(values[0])
    rows = []
    for raw in values[1:]:
        if len(raw) < len(headers):
            raw = raw + [""] * (len(headers) - len(raw))
        elif len(raw) > len(headers):
            raw = raw[:len(headers)]
        rows.append(dict(zip(headers, raw)))
    return rows


def build_historical_accounts(rows):
    out = {}
    for row in rows:
        email = normalize_email(row.get("Email", ""))
        if not email: continue
        created_on = parse_date_to_ymd(row.get("Created on", ""))
        upload_status = str(row.get("App upload status", "")).strip().lower()
        user_name = str(row.get("User name", "")).strip()

        rec = out.setdefault(email, {
            "all_dates": [], "rows_by_date": {},
            "earliest_date": "", "latest_date": "",
        })

        if created_on:
            if created_on not in rec["all_dates"]:
                rec["all_dates"].append(created_on)
                rec["all_dates"].sort()
            if not rec["earliest_date"] or created_on < rec["earliest_date"]:
                rec["earliest_date"] = created_on
            if not rec["latest_date"] or created_on > rec["latest_date"]:
                rec["latest_date"] = created_on

            day = rec["rows_by_date"].setdefault(created_on, {
                "upload_statuses": [], "has_upload_yes": False, "user_names": [],
            })
            if upload_status:
                if upload_status not in day["upload_statuses"]:
                    day["upload_statuses"].append(upload_status)
                if upload_status == "yes":
                    day["has_upload_yes"] = True
            if user_name and user_name not in day["user_names"]:
                day["user_names"].append(user_name)
    return out


def build_historical_paid(rows):
    out = {}
    for row in rows:
        email = normalize_email(row.get("Email", ""))
        if not email: continue
        created = parse_date_to_ymd(row.get("Created (UTC)", ""))
        spend = parse_float(row.get("Total Spend", 0))
        pay_count = parse_int(row.get("Payment Count", 0))

        rec = out.setdefault(email, {
            "stripe_created_utc": "", "all_created_utc": [],
            "total_spend": 0.0, "payment_count": 0,
            "has_paid": False, "customer_ids": [],
        })
        if created:
            if not rec["stripe_created_utc"] or created < rec["stripe_created_utc"]:
                rec["stripe_created_utc"] = created
            if created not in rec["all_created_utc"]:
                rec["all_created_utc"].append(created)
                rec["all_created_utc"].sort()
        rec["total_spend"] = max(rec["total_spend"], spend)
        rec["payment_count"] = max(rec["payment_count"], pay_count)
        rec["has_paid"] = rec["total_spend"] > 0 or rec["payment_count"] > 0
        cid = str(row.get("id", "")).strip()
        if cid and cid not in rec["customer_ids"]:
            rec["customer_ids"].append(cid)
    return out


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def main():
    gc = get_client()
    sh = None  # MIGRATED: use load_tab() from mongo_data_loader

    ws_accounts = sh.worksheet("Enterprise-Inbound-Leads")
    ws_paid = sh.worksheet("All Time Data")

    account_rows = worksheet_to_dict_rows(ws_accounts)
    paid_rows = worksheet_to_dict_rows(ws_paid)

    log(f"Tab 0 rows: {len(account_rows)}")
    log(f"Tab 1 rows: {len(paid_rows)}")

    ha = build_historical_accounts(account_rows)
    hp = build_historical_paid(paid_rows)

    save_json(HISTORICAL_ACCOUNTS_FILE, ha)
    save_json(HISTORICAL_PAID_FILE, hp)

    log(f"historical_accounts: {len(ha)} emails")
    log(f"historical_paid:     {len(hp)} emails")
    log(f"  Tab 0 with upload=Yes anywhere: {sum(1 for v in ha.values() for d,i in v.get('rows_by_date',{}).items() if i.get('has_upload_yes'))}")
    log(f"  Tab 1 has_paid=True: {sum(1 for v in hp.values() if v['has_paid'])}")


if __name__ == "__main__":
    main()
