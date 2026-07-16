from pathlib import Path
from datetime import datetime
import textwrap
import re

ROOT = Path.cwd()
BACKUPS = ROOT / "backups"
BACKUPS.mkdir(exist_ok=True)

def backup(path: Path):
    if path.exists():
        b = BACKUPS / f"{path.name}.mega_stabilize.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
        b.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        print(f"BACKUP: {path} -> {b}")

# -------------------------------------------------------------------
# 1) start_streamlit_render.sh
# -------------------------------------------------------------------
ss = ROOT / "scripts" / "start_streamlit_render.sh"
backup(ss) if ss.exists() else None
ss.write_text("""#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mkdir -p .streamlit

cat > .streamlit/secrets.toml <<SECRETS
APP_PASSWORD = "${APP_PASSWORD:-}"
MONGO_URI = "${MONGO_URI:-}"
MONGO_DB = "${MONGO_DB:-eagle3d}"
TELEGRAM_BOT_TOKEN = "${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID = "${TELEGRAM_CHAT_ID:-}"
YOUTUBE_API_KEY = "${YOUTUBE_API_KEY:-}"
YOUTUBE_CHANNEL_ID = "${YOUTUBE_CHANNEL_ID:-}"
WEBHOOK_API_KEY = "${WEBHOOK_API_KEY:-}"
GA4_PROPERTY_ID = "${GA4_PROPERTY_ID:-}"
SECRETS

if [ -n "${GA4_SERVICE_ACCOUNT_JSON:-}" ]; then
python3 - <<'PY'
import json
import os
from pathlib import Path

raw = os.environ.get("GA4_SERVICE_ACCOUNT_JSON", "").strip()
if not raw:
    raise SystemExit(0)

try:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("GA4_SERVICE_ACCOUNT_JSON is not a JSON object")
except Exception as e:
    print(f"WARNING: invalid GA4_SERVICE_ACCOUNT_JSON, skipping injection: {e}")
    raise SystemExit(0)

p = Path(".streamlit/secrets.toml")
text = p.read_text(encoding="utf-8")
text += "\\n[ga4_service_account]\\n"
for k, v in data.items():
    if isinstance(v, str):
        text += f'{k} = "{v.replace(chr(34), chr(92)+chr(34))}"\\n'
    elif isinstance(v, bool):
        text += f"{k} = {'true' if v else 'false'}\\n"
    else:
        text += f"{k} = {json.dumps(v)}\\n"
p.write_text(text, encoding="utf-8")
print("GA4 service account written to secrets.toml")
PY
fi

echo "== Render Streamlit startup =="
echo "APP_PASSWORD_PRESENT=$([ -n "${APP_PASSWORD:-}" ] && echo yes || echo no)"
echo "MONGO_URI_PRESENT=$([ -n "${MONGO_URI:-}" ] && echo yes || echo no)"
echo "GA4_PROPERTY_ID_PRESENT=$([ -n "${GA4_PROPERTY_ID:-}" ] && echo yes || echo no)"
echo "GA4_SERVICE_ACCOUNT_JSON_PRESENT=$([ -n "${GA4_SERVICE_ACCOUNT_JSON:-}" ] && echo yes || echo no)"

exec streamlit run app.py \
  --server.port "$PORT" \
  --server.address 0.0.0.0 \
  --server.headless true \
  --browser.gatherUsageStats false
""", encoding="utf-8")
ss.chmod(0o755)
print("✅ scripts/start_streamlit_render.sh rewritten")

# -------------------------------------------------------------------
# 2) install_linkedin_cookies_full.py with GitHub Secret fallback
# -------------------------------------------------------------------
lic = ROOT / "scripts" / "install_linkedin_cookies_full.py"
backup(lic) if lic.exists() else None
lic.write_text(textwrap.dedent("""\
from __future__ import annotations

import json
import html
import re
import os
from pathlib import Path
from urllib.parse import urlparse

INPUTS = [
    Path("data/linkedin_cookies.json"),
    Path("data_output/linkedin_cookies.json"),
    Path.home() / "Downloads" / "linkedin_cookies.json",
    Path("linkedin_cookies.json"),
]

OUTS = [
    Path("data/linkedin_cookies.json"),
    Path("data_output/linkedin_cookies.json"),
]

IMPORTANT = ["li_at", "JSESSIONID", "bcookie", "bscookie", "PLAY_SESSION", "fptctx2"]

def unesc(v):
    return html.unescape(str(v or "")).strip()

def extract_host(raw: str) -> str:
    s = unesc(raw).strip('"').strip("'")
    m = re.search(r'((?:www\\.)?linkedin\\.com)\\b', s, re.I)
    if m:
        return m.group(1).lower()
    if s.startswith("http://") or s.startswith("https://"):
        try:
            p = urlparse(s)
            if p.netloc:
                return p.netloc.lower()
        except Exception:
            pass
    return s.strip("/").lstrip(".").lower()

def clean_obj(obj):
    if isinstance(obj, dict):
        return {k: clean_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_obj(x) for x in obj]
    if isinstance(obj, str):
        return html.unescape(obj)
    return obj

def normalize_cookie(c):
    c = clean_obj(c)
    name = unesc(c.get("name"))
    value = unesc(c.get("value"))
    if not name:
        return None

    domain = extract_host(c.get("domain", ""))
    if not domain:
        return None

    fixed = dict(c)
    fixed["name"] = name
    fixed["value"] = value

    if c.get("hostOnly", False):
        fixed["domain"] = domain
    else:
        fixed["domain"] = "." + domain.lstrip(".")

    fixed["path"] = unesc(c.get("path") or "/") or "/"

    ss = unesc(c.get("sameSite"))
    if ss.lower() in ("no_restriction", "none", "no restriction"):
        fixed["sameSite"] = "no_restriction"
    elif ss.lower() in ("lax", "strict"):
        fixed["sameSite"] = ss.lower()
    else:
        fixed["sameSite"] = None

    return fixed

def main():
    raw_secret = os.environ.get("LINKEDIN_COOKIES_JSON", "").strip()
    if raw_secret:
        Path("data").mkdir(exist_ok=True)
        Path("data_output").mkdir(exist_ok=True)
        Path("data/linkedin_cookies.json").write_text(raw_secret, encoding="utf-8")
        Path("data_output/linkedin_cookies.json").write_text(raw_secret, encoding="utf-8")

    src = next((p for p in INPUTS if p.exists()), None)
    if src is None:
        print("❌ Could not find input cookie file.")
        for p in INPUTS:
            print(" -", p)
        raise SystemExit(1)

    raw = src.read_text(encoding="utf-8", errors="ignore").strip()
    if not raw:
        print(f"❌ Input file is empty: {src}")
        raise SystemExit(1)

    data = json.loads(raw)
    if isinstance(data, str):
        data = json.loads(data)

    if not isinstance(data, list):
        print("❌ Cookie file is not a JSON list")
        raise SystemExit(1)

    cleaned = []
    for item in data:
        if isinstance(item, dict):
            norm = normalize_cookie(item)
            if norm:
                cleaned.append(norm)

    if not cleaned:
        print("❌ No valid cookies after normalization")
        raise SystemExit(1)

    names = {c.get("name") for c in cleaned}

    for out in OUTS:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
        print(f"OK: wrote full sanitized cookies -> {out}")

    print(f"Full cookie count: {len(cleaned)}")
    for k in IMPORTANT:
        print(f"{k}: {'PRESENT' if k in names else 'MISSING'}")

if __name__ == "__main__":
    main()
"""), encoding="utf-8")
print("✅ scripts/install_linkedin_cookies_full.py rewritten")

# -------------------------------------------------------------------
# 3) send_telegram_test.py
# -------------------------------------------------------------------
tst = ROOT / "scripts" / "send_telegram_test.py"
tst.write_text(textwrap.dedent("""\
import json
import os
import urllib.request

token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

if not token or not chat_id:
    raise SystemExit("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")

payload = json.dumps({
    "chat_id": chat_id,
    "text": "✅ GitHub manual workflow heartbeat reached Telegram.",
    "parse_mode": "Markdown",
}).encode("utf-8")

req = urllib.request.Request(
    f"https://api.telegram.org/bot{token}/sendMessage",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)

with urllib.request.urlopen(req, timeout=15) as resp:
    body = json.loads(resp.read().decode())
    print(body)
    if not body.get("ok"):
        raise SystemExit("Telegram send failed")
"""), encoding="utf-8")
print("✅ scripts/send_telegram_test.py written")

# -------------------------------------------------------------------
# 4) fix_daily_kpis_safe.py in scripts path for workflow
# -------------------------------------------------------------------
kpi_script = ROOT / "scripts" / "fix_daily_kpis_safe.py"
if not kpi_script.exists():
    kpi_script.write_text(textwrap.dedent("""\
from pathlib import Path
from datetime import datetime, date
import json
import glob
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mongo_client import find_all, get_raw_db

TODAY = date.today().isoformat()
MONTH_START = date.today().replace(day=1).isoformat()

def norm_email(v):
    return str(v or "").strip().lower()

def as_int(v):
    try:
        if v is None or str(v).strip() == "":
            return 0
        return int(float(v))
    except Exception:
        return 0

def is_accepted(doc):
    return str(doc.get("final_status", "")).strip().upper() == "ACCEPTED"

def pick_date(doc, keys):
    for k in keys:
        v = str(doc.get(k, "") or "").strip()
        if v:
            return v[:10]
    return ""

def load_base_daily_kpis():
    rows = find_all("daily_kpis", sort=[("date", 1)], limit=10000)
    daymap = {}
    for r in rows:
        d = str(r.get("date", "")).strip()[:10]
        if not d:
            continue
        daymap[d] = {
            "date": d,
            "signups": as_int(r.get("signups", 0)),
            "uploads": as_int(r.get("uploads", r.get("first_uploads", 0))),
            "first_uploads": as_int(r.get("first_uploads", r.get("uploads", 0))),
        }
    return daymap

def build_payment_maps():
    payments = [p for p in find_all("payments", {}) if is_accepted(p)]
    rows = []
    for p in payments:
        d = pick_date(p, ["first_payment_date", "payment_date", "created_date", "date"])
        email = norm_email(p.get("email") or p.get("email_normalized"))
        if not d or not email:
            continue
        rows.append({
            "date": d,
            "email": email,
            "payment_count": as_int(p.get("payment_count", 0)),
            "customer_type": str(p.get("customer_type", "")).strip().upper(),
            "status": str(
                p.get("subscription_status")
                or p.get("status")
                or p.get("plan_status")
                or p.get("customer_status")
                or ""
            ).strip().lower(),
        })

    rows.sort(key=lambda x: (x["date"], x["email"]))
    first_payment_by_email = {}
    for r in rows:
        first_payment_by_email.setdefault(r["email"], r["date"])

    new_by_day = {}
    recurring_by_day = {}
    stopped_by_day = {}

    def add_day(mapper, d, email):
        mapper.setdefault(d, set()).add(email)

    stop_statuses = {"cancelled", "canceled", "expired", "inactive", "past_due", "unpaid", "stopped"}

    for r in rows:
        d = r["date"]
        email = r["email"]

        if r["customer_type"] == "NEW_CUSTOMER" or r["payment_count"] == 1 or first_payment_by_email.get(email) == d:
            add_day(new_by_day, d, email)
        else:
            add_day(recurring_by_day, d, email)

        if r["status"] in stop_statuses and r["payment_count"] > 1:
            add_day(stopped_by_day, d, email)

    return new_by_day, recurring_by_day, stopped_by_day

def main():
    db = get_raw_db()
    if db is None:
        raise SystemExit("MongoDB not available")

    base = load_base_daily_kpis()
    new_by_day, recurring_by_day, stopped_by_day = build_payment_maps()

    all_dates = set(base.keys()) | set(new_by_day.keys()) | set(recurring_by_day.keys()) | set(stopped_by_day.keys())
    rows = []

    for d in sorted(all_dates):
        b = base.get(d, {"date": d, "signups": 0, "uploads": 0, "first_uploads": 0})
        rows.append({
            "date": d,
            "signups": as_int(b.get("signups", 0)),
            "uploads": as_int(b.get("uploads", b.get("first_uploads", 0))),
            "first_uploads": as_int(b.get("first_uploads", b.get("uploads", 0))),
            "paid_customers": len(new_by_day.get(d, set())),
            "new_paid_customers": len(new_by_day.get(d, set())),
            "recurring_customers": len(recurring_by_day.get(d, set())),
            "stopped_recurring_customers": len(stopped_by_day.get(d, set())),
            "payments": len(new_by_day.get(d, set())),
            "source": "daily_kpis_safe_fix",
            "rebuilt_at": datetime.utcnow().isoformat(),
        })

    db["daily_kpis"].delete_many({})
    if rows:
        db["daily_kpis"].insert_many(rows)

    print(json.dumps({
        "month_signups": sum(as_int(r["signups"]) for r in rows if MONTH_START <= r["date"] <= TODAY),
        "month_first_uploads": sum(as_int(r["first_uploads"]) for r in rows if MONTH_START <= r["date"] <= TODAY),
        "month_new_paid_customers": sum(as_int(r["new_paid_customers"]) for r in rows if MONTH_START <= r["date"] <= TODAY),
        "month_recurring_customers": sum(as_int(r["recurring_customers"]) for r in rows if MONTH_START <= r["date"] <= TODAY),
        "month_stopped_recurring_customers": sum(as_int(r["stopped_recurring_customers"]) for r in rows if MONTH_START <= r["date"] <= TODAY),
    }, indent=2))

if __name__ == "__main__":
    main()
"""), encoding="utf-8")
    print("✅ scripts/fix_daily_kpis_safe.py created")

# -------------------------------------------------------------------
# 5) Workflows
# -------------------------------------------------------------------
kpi = ROOT / ".github" / "workflows" / "kpi-rebuild.yml"
kpi.write_text(textwrap.dedent("""\
name: KPI Rebuild

on:
  workflow_dispatch:
  schedule:
    - cron: "15 * * * *"

jobs:
  rebuild:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    env:
      MONGO_URI: ${{ secrets.MONGO_URI }}
      MONGO_DB: ${{ secrets.MONGO_DB }}
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Rebuild daily_kpis
        run: |
          python scripts/fix_daily_kpis_safe.py
"""), encoding="utf-8")
print("✅ .github/workflows/kpi-rebuild.yml written")

eaw = ROOT / ".github" / "workflows" / "engagement-alerts.yml"
backup(eaw) if eaw.exists() else None
eaw.write_text(textwrap.dedent("""\
name: Engagement Alerts

on:
  workflow_dispatch:
  schedule:
    - cron: "*/15 * * * *"

jobs:
  alerts:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    env:
      MONGO_URI: ${{ secrets.MONGO_URI }}
      MONGO_DB: ${{ secrets.MONGO_DB }}
      TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
      TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
      YOUTUBE_API_KEY: ${{ secrets.YOUTUBE_API_KEY }}
      YOUTUBE_CHANNEL_ID: ${{ secrets.YOUTUBE_CHANNEL_ID }}
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install python-calamine xlrd lxml html5lib beautifulsoup4

      - name: Telegram heartbeat on manual dispatch
        if: github.event_name == 'workflow_dispatch'
        run: |
          python scripts/send_telegram_test.py

      - name: Run engagement alerts
        run: |
          python engagement_alerts.py
"""), encoding="utf-8")
print("✅ .github/workflows/engagement-alerts.yml written")

liw = ROOT / ".github" / "workflows" / "linkedin-export-sync.yml"
backup(liw) if liw.exists() else None
liw.write_text(textwrap.dedent("""\
name: LinkedIn Export Sync

on:
  workflow_dispatch:
  schedule:
    - cron: "0 */12 * * *"

jobs:
  sync-linkedin:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    env:
      MONGO_URI: ${{ secrets.MONGO_URI }}
      MONGO_DB: ${{ secrets.MONGO_DB }}
      TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
      TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
      LINKEDIN_COOKIES_JSON: ${{ secrets.LINKEDIN_COOKIES_JSON }}
      LINKEDIN_HEADLESS: "true"
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install system deps
        run: |
          sudo apt-get update
          sudo apt-get install -y xvfb

      - name: Install Python deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install python-calamine xlrd lxml html5lib beautifulsoup4

      - name: Install Playwright Chromium
        run: |
          python -m playwright install chromium

      - name: Install/sanitize cookies
        run: |
          python scripts/install_linkedin_cookies_full.py

      - name: Seed persistent profile from cookies
        run: |
          xvfb-run -a python scripts/seed_linkedin_profile_from_cookies.py

      - name: Run LinkedIn export sync
        run: |
          xvfb-run -a bash scripts/run_linkedin_export_sync.sh

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: linkedin-export-sync
          path: |
            downloads/linkedin_exports
            data_output/linkedin_exports_json
            logs/linkedin_export_sync.out.log
            logs/linkedin_export_sync.err.log
"""), encoding="utf-8")
print("✅ .github/workflows/linkedin-export-sync.yml written")

# -------------------------------------------------------------------
# 6) app.py and pages_registry.py safe global fixes
# -------------------------------------------------------------------
for path_name in ["app.py", "pages_registry.py"]:
    path = ROOT / path_name
    if not path.exists():
        continue
    backup(path)
    txt = path.read_text(encoding="utf-8", errors="ignore")
    txt = txt.replace("_route(current_page, user_email)", "route(current_page, user_email)")
    txt = txt.replace("def _route(page: str, user_email: str) -> None:", "def route(page: str, user_email: str) -> None:")
    txt = txt.replace("signups_accepted", "signups")
    txt = txt.replace("uploads_accepted", "first_uploads")
    txt = txt.replace("paid_accepted", "new_paid_customers")
    txt = txt.replace("New New Paying Customers", "New Paying Customers")
    txt = txt.replace("💳 Paid", "💳 New Paying Customers")
    txt = re.sub(r'.*Recurring Customers.*\\n', '', txt)
    txt = re.sub(r'.*Stopped Recurring.*\\n', '', txt)
    path.write_text(txt, encoding="utf-8")
    print(f"✅ {path_name} stabilized")

# -------------------------------------------------------------------
# 7) kpi_pattern_analyzer safe fallback for DOMAIN_COUNTRY
# -------------------------------------------------------------------
kpa = ROOT / "kpi_pattern_analyzer.py"
if kpa.exists():
    backup(kpa)
    txt = kpa.read_text(encoding="utf-8", errors="ignore")
    if "DOMAIN_COUNTRY =" not in txt:
        insert = 'DOMAIN_COUNTRY = globals().get("DOMAIN_COUNTRY", {})\n\n'
        # after imports
        m = re.search(r'^(from .* import .*|import .*)$', txt, flags=re.M)
        if m:
            idx = m.end()
            txt = txt[:idx] + "\n" + insert + txt[idx:]
        else:
            txt = insert + txt
        kpa.write_text(txt, encoding="utf-8")
        print("✅ kpi_pattern_analyzer.py patched with DOMAIN_COUNTRY fallback")
    else:
        print("ℹ️ kpi_pattern_analyzer.py already defines DOMAIN_COUNTRY")

print("✅ mega cloud stabilization complete")
