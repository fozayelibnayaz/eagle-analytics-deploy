"""
kpi_bridge.py — MIGRATED: Google Sheets → MongoDB
"""
import os
import pandas as pd
from datetime import datetime
from mongo_client import get_db, find_all, count_docs, get_mongo_status
from mongo_data_loader import (
    load_tab, load_daily_kpis, load_signups, load_uploads,
    load_payments, get_kpi_counts, get_connection_status
)

def get_master_sheet_url():
    return "mongodb://localhost:27017/eagle3d"

def get_sheet_client():
    return None

def open_master_sheet():
    return None

def _get_sheet_url():
    return "mongodb://localhost:27017/eagle3d"

def read_tab(tab_name):
    return load_tab(tab_name)

def load_daily_counts():
    return load_tab("daily_counts")

def load_signups_tab():
    return load_tab("signups")

def load_uploads_tab():
    return load_tab("uploads")

def load_stripe_tab():
    return load_tab("verified_stripe")

def get_kpi_summary(period_start=None, period_end=None):
    return get_kpi_counts(period_start=period_start, period_end=period_end)

def get_connection_info():
    return get_connection_status()

def check_sheet_health():
    status = get_connection_status()
    return {
        "connected": status.get("connected", False),
        "source": "mongodb",
        "message": status.get("message", ""),
        "error": None if status.get("connected") else status.get("message")
    }
