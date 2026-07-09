"""
config.py — Eagle 3D Streaming Analytics Hub
Static config, paths, and behavior toggles. Secrets come from
.streamlit/secrets.toml or environment variables (never here).
"""

import os
from pathlib import Path

# ─────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────
PROJECT_ROOT        = Path(__file__).parent
BROWSER_SESSION_DIR = PROJECT_ROOT / "browser_session"
STRIPE_SESSION_DIR  = PROJECT_ROOT / "stripe_session"
DATA_DIR            = PROJECT_ROOT / "data"
DATA_OUTPUT_DIR     = PROJECT_ROOT / "data_output"
DEBUG_DIR           = DATA_DIR / "debug"
MODEL_DIR           = PROJECT_ROOT / "models"
STATIC_DIR          = PROJECT_ROOT / "static"

MODEL_FILE = MODEL_DIR / "lead_quality_model.joblib"

for _d in (DATA_DIR, DEBUG_DIR, MODEL_DIR, DATA_OUTPUT_DIR, STATIC_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────────
# BRAND
# ─────────────────────────────────────────────────────────────────
BRAND_NAME    = "Eagle 3D Streaming"
APP_TITLE     = "Eagle 3D Streaming — Analytics Hub"
LOGO_FILE     = STATIC_DIR / "eagle3d_logo2.png"
LOGO_FALLBACK = STATIC_DIR / "eagle3d_logo.png"

# ─────────────────────────────────────────────────────────────────
# STORAGE (MongoDB only)
# ─────────────────────────────────────────────────────────────────
ALSO_SAVE_CSV = False

# ─────────────────────────────────────────────────────────────────
# EXTERNAL URLS
# ─────────────────────────────────────────────────────────────────
KPI_URL                  = "https://kpidashboard.eagle3dstreaming.com/"
STRIPE_CUSTOMERS_URL     = "https://dashboard.stripe.com/acct_1J7M5XIKrnGFhGm1/customers?has_subscription=true"
STRIPE_SUBSCRIPTIONS_URL = "https://dashboard.stripe.com/acct_1J7M5XIKrnGFhGm1/subscriptions"

# ─────────────────────────────────────────────────────────────────
# GOOGLE SHEETS (legacy read-only backfill)
# ─────────────────────────────────────────────────────────────────
GOOGLE_CREDS_FILE        = PROJECT_ROOT / "google_creds.json"
MASTER_SHEET_URL         = "https://docs.google.com/spreadsheets/d/1E5PI3-m7mTMKRQ4Cy-WqpVCo5dQjbICcA2EnrC9ORE4/edit"
OLD_DATABASE_SHEET_URL   = "https://docs.google.com/spreadsheets/d/1tEaUA2hGxuHw3E9n0TzyaEUz9MIlpQGoZy-WQz0NwSc/edit"
ACCURATE_DATA_SHEET_URL  = "https://docs.google.com/spreadsheets/d/1lwffyXWOa7Q7xim2EX9i4AdIs7dtkjOPyKYVBtPpfgY/edit"
CS_SHEET_URL             = "https://docs.google.com/spreadsheets/d/1sSaJ-4RusYSz8eAbycLeDkCC1LFXPY-4ErffDVQieAU/edit"

# ─────────────────────────────────────────────────────────────────
# SCRAPER BEHAVIOR
# ─────────────────────────────────────────────────────────────────
HEADLESS               = os.environ.get("HEADLESS_MODE", "false").lower() == "true"
SLOW_MO_MS             = 100
TABS                   = ["FREE", "PAID", "500 MIN", "FIRST UPLOAD"]
MONTH_FILTER           = "All Time"
DROPDOWN_ENABLE_TIMEOUT = 180
DATA_REFRESH_WAIT      = 60

STRIPE_PAGE_LOAD_WAIT = 12
STRIPE_MAX_PAGES      = 50
STRIPE_SCRAPE_MODE    = "customers"

# ─────────────────────────────────────────────────────────────────
# EMAIL VALIDATION
# ─────────────────────────────────────────────────────────────────
CHECK_MX_RECORDS         = True
MX_TIMEOUT_SECONDS       = 5
DISPOSABLE_DOMAINS_URL   = "https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/master/disposable_email_blocklist.conf"

CUSTOM_DISPOSABLE_DOMAINS = [
    "heywhatsoup.com", "deapad.com", "deapad.net", "tempmail.com",
    "tempmail.net", "10minutemail.com", "guerrillamail.com",
    "mailinator.com", "throwawaymail.com", "trashmail.com",
    "yopmail.com", "fakeinbox.com", "getnada.com", "maildrop.cc",
    "tempinbox.com", "dispostable.com", "sharklasers.com",
    "spam4.me", "mailnesia.com",
]

SUSPICIOUS_LOCAL_PATTERNS = [
    r"^test\d*$",
    r"^asdf+\d*$",
    r"^qwerty+\d*$",
    r"^abc+\d*$",
    r"^xxx+\d*$",
    r"^\d{6,}$",
]

# ─────────────────────────────────────────────────────────────────
# INTERNAL FILTERS
# ─────────────────────────────────────────────────────────────────
INTERNAL_EMAIL_KEYWORDS      = ["eagle"]
INTERNAL_EMAIL_DOMAINS       = ["eagle3dstreaming.com", "eagle3d.com"]
SKIP_LEAD_SOURCE_KEYWORDS    = ["internal", "test", "staff", "team", "employee"]
OLD_SHEET_EMAIL_COLUMN_HINTS = ["email", "e-mail", "mail"]

# ─────────────────────────────────────────────────────────────────
# NOTIFICATIONS (optional)
# ─────────────────────────────────────────────────────────────────
NOTIFY_EMAIL_TO             = ""
NOTIFY_EMAIL_FROM           = ""
NOTIFY_EMAIL_APP_PASSWORD   = ""
SLACK_WEBHOOK_URL           = ""

# ─────────────────────────────────────────────────────────────────
# SCHEDULER
# ─────────────────────────────────────────────────────────────────
DAILY_RUN_HOUR   = 9
DAILY_RUN_MINUTE = 0

# ─────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────
DASHBOARD_PORT = 8501

# ─────────────────────────────────────────────────────────────────
# LEGACY (kept for backward compat with scrape_kpi.py)
# ─────────────────────────────────────────────────────────────────
KPI_USERNAME = ""
KPI_PASSWORD = ""
