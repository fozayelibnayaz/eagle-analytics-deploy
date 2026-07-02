"""
sheets_writer.py — MIGRATED: MongoDB only
"""
import os
import pandas as pd
from mongo_client import (
    get_db, find_all, upsert_many, upsert_one,
    insert_many, delete_many, get_mongo_status
)
from mongo_data_loader import (
    load_tab, get_connection_status, sync_daily_kpis,
    sync_signups, sync_uploads, sync_payments
)

def _get_sb():
    return get_db()

def _get_client():
    return None, None

def read_tab_data(tab_name):
    return load_tab(tab_name)

def fetch_all(collection_name, filters=None, limit=0):
    return find_all(collection_name, filters, limit=limit)

def write_tab(tab_name, rows, conflict_field=None):
    mongo_col = f"sheet_{tab_name.lower().replace(' ','_').replace('-','_')}"
    if conflict_field:
        return upsert_many(mongo_col, rows, conflict_field)
    else:
        db = get_db()
        if db is not None:
            db[mongo_col].drop()
            return insert_many(mongo_col, rows)
        return 0

def upsert_to_collection(table, rows, on_conflict):
    return upsert_many(table, rows, on_conflict)

def get_connection_status():
    return get_mongo_status()
