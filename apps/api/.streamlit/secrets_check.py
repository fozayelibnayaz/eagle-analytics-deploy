# This file is just for local verification - not deployed
# Confirms what secrets are needed in Streamlit Cloud
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

secrets_needed = [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY", 
    "MASTER_SHEET_URL",
    "GA4_PROPERTY_ID",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
]
print("Required secrets in Streamlit Cloud:")
for s in secrets_needed:
    print(f"  {s}")
