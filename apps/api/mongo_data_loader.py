"""
mongo_data_loader.py
Replaces: mongo_data_loader.py + Google Sheets reads
Single source for all data loading from local MongoDB.
"""
import os
import pandas as pd
from datetime import datetime, date
from mongo_client import (
    get_db, find_all, find_one, count_docs,
    count_accepted, upsert_many, get_mongo_status
)

def get_active_overrides():
    return find_all("manual_overrides", {"is_active": True})

def load_daily_kpis():
    rows = find_all("daily_kpis", sort=[("date", 1)])
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.drop(columns=[c for c in ["_id","_migrated_at","_updated_at",
                                       "_inserted_at"] if c in df.columns],
                 errors="ignore")
    return df

def load_signups(final_status=None):
    filters = {}
    if final_status:
        filters["final_status"] = final_status
    rows = find_all("signups", filters)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.drop(columns=[c for c in ["_id","_migrated_at","_updated_at",
                                       "_inserted_at"] if c in df.columns],
                 errors="ignore")
    return df

def load_uploads(final_status=None):
    filters = {}
    if final_status:
        filters["final_status"] = final_status
    rows = find_all("uploads", filters)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.drop(columns=[c for c in ["_id","_migrated_at","_updated_at",
                                       "_inserted_at"] if c in df.columns],
                 errors="ignore")
    return df

def load_payments(final_status=None):
    filters = {}
    if final_status:
        filters["final_status"] = final_status
    rows = find_all("payments", filters)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.drop(columns=[c for c in ["_id","_migrated_at","_updated_at",
                                       "_inserted_at"] if c in df.columns],
                 errors="ignore")
    return df

def get_kpi_counts(period_start=None, period_end=None, since_upload_start=None):
    today = date.today().isoformat()
    month_start = date.today().replace(day=1).isoformat()
    result = {
        "signups_today":    count_accepted("signups",  "signup_date",        date_gte=today),
        "uploads_today":    count_accepted("uploads",  "upload_date",        date_gte=today),
        "payments_today":   count_accepted("payments", "first_payment_date", date_gte=today),
        "signups_month":    count_accepted("signups",  "signup_date",        date_gte=month_start),
        "uploads_month":    count_accepted("uploads",  "upload_date",        date_gte=month_start),
        "payments_month":   count_accepted("payments", "first_payment_date", date_gte=month_start),
        "signups_total":    count_accepted("signups",  "signup_date"),
        "payments_total":   count_accepted("payments", "first_payment_date"),
        "active_overrides": count_docs("manual_overrides", {"is_active": True}),
        "source": "mongodb",
    }
    if since_upload_start:
        result["signups_since_start"]  = count_accepted("signups",  "signup_date",        date_gte=since_upload_start)
        result["uploads_since_start"]  = count_accepted("uploads",  "upload_date",        date_gte=since_upload_start)
        result["payments_since_start"] = count_accepted("payments", "first_payment_date", date_gte=since_upload_start)
    if period_start and period_end:
        result["signups_period"]  = count_accepted("signups",  "signup_date",        date_gte=period_start, date_lte=period_end)
        result["uploads_period"]  = count_accepted("uploads",  "upload_date",        date_gte=period_start, date_lte=period_end)
        result["payments_period"] = count_accepted("payments", "first_payment_date", date_gte=period_start, date_lte=period_end)
    return result

def get_earliest_upload_date():
    rows = find_all(
        "uploads",
        filters={"final_status": "ACCEPTED"},
        projection={"upload_date": 1},
        sort=[("upload_date", 1)],
        limit=1
    )
    if rows and rows[0].get("upload_date"):
        return str(rows[0]["upload_date"])[:10]
    return None

def load_tab(tab_name):
    mongo_col = f"sheet_{tab_name.lower().replace(' ','_').replace('-','_')}"
    rows = find_all(mongo_col)
    clean = []
    for r in rows:
        clean.append({k: v for k, v in r.items()
                      if k not in ("_id","_migrated_at","_updated_at",
                                   "_sheet_key","_tab_name","_inserted_at")})
    return clean

def read_tab_data(tab_name):
    return load_tab(tab_name)

def load_master_sheet_tab(tab_name):
    return load_tab(tab_name)

def load_ml_training_data(tab_name):
    mongo_col = f"ml_training_{tab_name.lower().replace(' ','_').replace('-','_')}"
    return find_all(mongo_col)

def load_all_ml_training_tabs():
    db = get_db()
    if db is None:
        return {}
    all_cols = db.list_collection_names()
    ml_cols = [c for c in all_cols if c.startswith("ml_training_")]
    result = {}
    for col_name in ml_cols:
        tab_name = col_name.replace("ml_training_", "")
        result[tab_name] = find_all(col_name)
    return result

def load_linkedin_posts(limit=0):
    return find_all("linkedin_posts", sort=[("published_at", -1)], limit=limit)

def load_linkedin_followers_daily():
    return find_all("linkedin_followers_daily", sort=[("date", 1)])

def load_linkedin_posts_daily(post_urn=None, date_gte=None, date_lte=None):
    filters = {}
    if post_urn:
        filters["post_urn"] = post_urn
    if date_gte or date_lte:
        filters["snapshot_date"] = {}
        if date_gte:
            filters["snapshot_date"]["$gte"] = str(date_gte)
        if date_lte:
            filters["snapshot_date"]["$lte"] = str(date_lte)
    return find_all("linkedin_posts_daily", filters, sort=[("snapshot_date", 1)])

def load_linkedin_highlights(date_gte=None, date_lte=None, limit=1):
    filters = {}
    if date_gte or date_lte:
        filters["snapshot_date"] = {}
        if date_gte:
            filters["snapshot_date"]["$gte"] = str(date_gte)
        if date_lte:
            filters["snapshot_date"]["$lte"] = str(date_lte)
    return find_all("linkedin_highlights_daily", filters,
                    sort=[("snapshot_date", -1)], limit=limit)

def sync_daily_kpis(rows):
    return upsert_many("daily_kpis", rows, "date")

def sync_signups(rows):
    return upsert_many("signups", rows, "email_normalized")

def sync_uploads(rows):
    return upsert_many("uploads", rows, "email_normalized")

def sync_payments(rows):
    return upsert_many("payments", rows, "email_normalized")

def get_connection_status():
    return get_mongo_status()

if __name__ == "__main__":
    print(get_connection_status())
    print(f"Daily KPIs: {len(load_daily_kpis())} rows")
    print(f"Signups: {len(load_signups())} rows")
    print(f"Uploads: {len(load_uploads())} rows")
    print(f"Payments: {len(load_payments())} rows")

def load_tab_df(tab_name):
    """Returns pandas DataFrame instead of list. Use when app expects .empty etc."""
    import pandas as pd
    rows = load_tab(tab_name)
    return pd.DataFrame(rows) if rows else pd.DataFrame()
