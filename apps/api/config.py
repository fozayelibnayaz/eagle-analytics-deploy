from pathlib import Path

# ─────────────────────────────────────────────────────────────────
#  PATHS
# ─────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
BROWSER_SESSION_DIR = PROJECT_ROOT / "browser_session"
STRIPE_SESSION_DIR = PROJECT_ROOT / "stripe_session"
DATA_DIR = PROJECT_ROOT / "data"
DEBUG_DIR = DATA_DIR / "debug"
MODEL_DIR = PROJECT_ROOT / "models"
MODEL_FILE = MODEL_DIR / "lead_quality_model.joblib"

DATA_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────────
#  STRICT ZERO-CSV ENFORCEMENT
# ─────────────────────────────────────────────────────────────────
ALSO_SAVE_CSV = False

# ─────────────────────────────────────────────────────────────────
#  URLS
# ─────────────────────────────────────────────────────────────────
KPI_URL = "https://kpidashboard.eagle3dstreaming.com/"
STRIPE_CUSTOMERS_URL = "https://dashboard.stripe.com/acct_1J7M5XIKrnGFhGm1/customers?has_subscription=true"
STRIPE_SUBSCRIPTIONS_URL = "https://dashboard.stripe.com/acct_1J7M5XIKrnGFhGm1/subscriptions"

# ─────────────────────────────────────────────────────────────────
#  GOOGLE SHEETS
# ─────────────────────────────────────────────────────────────────
GOOGLE_CREDS_FILE = PROJECT_ROOT / "google_creds.json"
MASTER_SHEET_URL = "https://docs.google.com/spreadsheets/d/1E5PI3-m7mTMKRQ4Cy-WqpVCo5dQjbICcA2EnrC9ORE4/edit?gid=0#gid=0"
OLD_DATABASE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1tEaUA2hGxuHw3E9n0TzyaEUz9MIlpQGoZy-WQz0NwSc/edit"
ACCURATE_DATA_SHEET_URL = "https://docs.google.com/spreadsheets/d/1lwffyXWOa7Q7xim2EX9i4AdIs7dtkjOPyKYVBtPpfgY/edit"

# ─────────────────────────────────────────────────────────────────
#  SCRAPER BEHAVIOR
# ─────────────────────────────────────────────────────────────────
import os as _os
HEADLESS = _os.environ.get("HEADLESS_MODE", "false").lower() == "true"
SLOW_MO_MS = 100
TABS = ["FREE", "PAID", "500 MIN", "FIRST UPLOAD"]
MONTH_FILTER = "All Time"
DROPDOWN_ENABLE_TIMEOUT = 180
DATA_REFRESH_WAIT = 60

# ─────────────────────────────────────────────────────────────────
#  STRIPE
# ─────────────────────────────────────────────────────────────────
STRIPE_PAGE_LOAD_WAIT = 12
STRIPE_MAX_PAGES = 50
STRIPE_SCRAPE_MODE = "customers"

# ─────────────────────────────────────────────────────────────────
#  EMAIL VALIDATION
# ─────────────────────────────────────────────────────────────────
CHECK_MX_RECORDS = True
MX_TIMEOUT_SECONDS = 5
DISPOSABLE_DOMAINS_URL = "https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/master/disposable_email_blocklist.conf"

CUSTOM_DISPOSABLE_DOMAINS = [
    "heywhatsoup.com", "deapad.com", "deapad.net", "tempmail.com",
    "tempmail.net", "10minutemail.com", "guerrillamail.com",
    "mailinator.com", "throwawaymail.com", "trashmail.com",
    "yopmail.com", "fakeinbox.com", "getnada.com", "maildrop.cc",
    "tempinbox.com", "dispostable.com", "sharklasers.com",
    "spam4.me", "mailnesia.com",
]

SUSPICIOUS_LOCAL_PATTERNS = [
    r"^test\\d*$",
    r"^asdf+\\d*$",
    r"^qwerty+\\d*$",
    r"^abc+\\d*$",
    r"^xxx+\\d*$",
    r"^\\d{6,}$",
]

# ─────────────────────────────────────────────────────────────────
#  FILTERS
# ─────────────────────────────────────────────────────────────────
INTERNAL_EMAIL_KEYWORDS = ["eagle"]
INTERNAL_EMAIL_DOMAINS = ["eagle3dstreaming.com", "eagle3d.com"]
SKIP_LEAD_SOURCE_KEYWORDS = ["internal", "test", "staff", "team", "employee"]
OLD_SHEET_EMAIL_COLUMN_HINTS = ["email", "e-mail", "mail"]

# ─────────────────────────────────────────────────────────────────
#  NOTIFICATIONS (optional)
# ─────────────────────────────────────────────────────────────────
NOTIFY_EMAIL_TO = ""
NOTIFY_EMAIL_FROM = ""
NOTIFY_EMAIL_APP_PASSWORD = ""
SLACK_WEBHOOK_URL = ""

# ─────────────────────────────────────────────────────────────────
#  SCHEDULER
# ─────────────────────────────────────────────────────────────────
DAILY_RUN_HOUR = 9
DAILY_RUN_MINUTE = 0

# ─────────────────────────────────────────────────────────────────
#  DASHBOARD
# ─────────────────────────────────────────────────────────────────
DASHBOARD_PORT = 8501


# ── Added by fix script ──
KPI_USERNAME = ""  # Set via environment variable / GitHub Secret  # UPDATE THIS
KPI_PASSWORD = ""  # Set via environment variable / GitHub Secret  # UPDATE THIS
