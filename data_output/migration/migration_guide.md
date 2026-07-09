# SUPABASE MIGRATION GUIDE

STEP 1 - Create Project
  Go to supabase.com
  Create new project named eagle3d-kpi
  Note the URL, anon key, and service role key

STEP 2 - Run Schema
  Supabase Dashboard -> SQL Editor
  Paste contents of schema.sql and click Run

STEP 3 - Install Client
  pip install supabase

STEP 4 - Add Secrets
  File: .streamlit/secrets.toml
  SUPABASE_URL = "https://xxxx.supabase.co"
  SUPABASE_SERVICE_KEY = "eyJ..."
  Also add both to GitHub Secrets

STEP 5 - Migrate Existing Data
  python3 supabase_migrator.py
  This reads daily_counts.json and inserts into daily_kpis
  Reads manual_overrides.json and inserts into manual_overrides
  Reads override_audit_log.json and inserts into override_audit_log

STEP 6 - Architecture After Migration
  Data Sources: Stripe, GA4, YouTube, LinkedIn
    -> process_data.py (validation + categorization)
    -> Supabase PostgreSQL (PRIMARY STORE)
    -> Google Sheets (BACKUP only)
    -> Dashboard reads from Supabase
    -> Telegram and Email reports use validated data only

TABLES IN PRODUCTION (Supabase)
  signups
  uploads
  payments
  manual_overrides (AUTHORITATIVE - permanent)
  override_audit_log (PERMANENT - never delete rows)
  daily_kpis
  analytics_cache
  report_history
  data_coverage

TABLES IN BACKUP (Google Sheets)
  Raw_FREE
  Raw_FIRST_UPLOAD
  Raw_STRIPE
  Verified_FREE
  Verified_FIRST_UPLOAD
  Verified_STRIPE
  Daily_Counts
