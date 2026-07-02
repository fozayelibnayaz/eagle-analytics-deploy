#!/usr/bin/env python3
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

Setup Streamlit Cloud Secrets — Run this on your Mac
=====================================================
This script reads your local google_creds.json and prints
the exact text to paste into Streamlit Cloud secrets.

Usage:
  cd /Users/macbookair/eagle3d-kpi-automation
  python3 setup_secrets.py

Then:
  1. Copy the output
  2. Go to https://share.streamlit.io
  3. Click your app → Settings → Secrets
  4. Paste and save
  5. Reboot the app
"""


import json
import os

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

print("🦅 Eagle3D KPI — Streamlit Cloud Secrets Setup")
print("=" * 60)

# 1. Google Credentials
if os.path.exists("google_creds.json"):
    with open("google_creds.json", "r") as f:
        creds = json.load(f)
    print("\n✅ Found google_creds.json")
    print(f"   Project: {creds.get('project_id')}")
    print(f"   Email: {creds.get('client_email')}")
    
    creds_json = json.dumps(creds, indent=2)
else:
    print("\n❌ google_creds.json NOT found!")
    print("   Make sure you're in the eagle3d-kpi-automation directory")
    exit(1)

# 2. Check for API keys in local secrets
groq_key = ""
gemini_key = ""
try:
    import tomllib
    with open(".streamlit/secrets.toml", "rb") as f:
        secrets = tomllib.load(f)
    groq_key = secrets.get("GROQ_API_KEY", "")
    gemini_key = secrets.get("GEMINI_API_KEY", "")
except Exception:
    # Try reading as text
    try:
        with open(".streamlit/secrets.toml", "r") as f:
            content = f.read()
        for line in content.split("\n"):
            if "GROQ_API_KEY" in line and "=" in line:
                groq_key = line.split("=", 1)[1].strip().strip('"').strip("'")
            if "GEMINI_API_KEY" in line and "=" in line:
                gemini_key = line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass

print(f"\n{'✅' if groq_key else '❌'} GROQ_API_KEY: {'found' if groq_key else 'NOT found'}")
print(f"{'✅' if gemini_key else '❌'} GEMINI_API_KEY: {'found' if gemini_key else 'NOT found'}")

# 3. Build the secrets TOML
print("\n" + "=" * 60)
print("COPY EVERYTHING BELOW INTO STREAMLIT CLOUD SECRETS")
print("Go to: https://share.streamlit.io → Settings → Secrets")
print("=" * 60)
print()
print('GOOGLE_CREDS_JSON = """')
print(creds_json)
print('"""')
print()
print('MASTER_SHEET_URL = "https://docs.google.com/spreadsheets/d/1E5PI3-m7mTMKRQ4Cy-WqpVCo5dQjbICcA2EnrC9ORE4/edit"')
print()
if groq_key:
    print(f'GROQ_API_KEY = "{groq_key}"')
if gemini_key:
    print(f'GEMINI_API_KEY = "{gemini_key}"')
print()
print("=" * 60)
print("After pasting → Click Save → Reboot app (⋮ menu)")
print("=" * 60)
