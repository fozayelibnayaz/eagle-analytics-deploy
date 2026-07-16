from pathlib import Path
from datetime import datetime
import json
import sys
import re

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mongo_client import get_raw_db, find_all

# ------------------------------------------------------------
# PART A: Hard-fix app.py greeting + route aliases
# ------------------------------------------------------------
app = ROOT / "app.py"
if not app.exists():
    raise SystemExit("❌ app.py not found")

backup_app = ROOT / "backups" / f"app.py.greeting_paid_fix.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
backup_app.write_text(app.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")

text = app.read_text(encoding="utf-8", errors="ignore")

# Ensure datetime import exists
if "from datetime import datetime" not in text and "import datetime" not in text:
    text = "from datetime import datetime\n" + text

# Force stable aliases and fallback greeting before main()
alias_block = """
# --- stable runtime fallbacks ---
def _greeting():
    try:
        h = datetime.now().hour
        return "Good morning" if h < 12 else ("Good afternoon" if h < 18 else "Good evening")
    except Exception:
        return "Hello"

try:
    route
except NameError:
    try:
        route = _route
    except NameError:
        pass

try:
    render_dashboard
except NameError:
    try:
        render_dashboard = _render_dashboard
    except NameError:
        try:
            render_dashboard = render_dashboard_preview
        except NameError:
            pass
"""

if "stable runtime fallbacks" not in text:
    idx = text.rfind("\nmain()")
    if idx != -1:
        text = text[:idx] + "\n\n" + alias_block + "\n" + text[idx:]
    else:
        text += "\n\n" + alias_block + "\n"

# fix route call if old alias still used
text = text.replace("_route(current_page, user_email)", "route(current_page, user_email)")

# strip the weird recurring UI references if present
text = re.sub(r'.*Recurring Customers.*\n', '', text)
text = re.sub(r'.*Stopped Recurring.*\n', '', text)

# normalize labels
text = text.replace("New New Paying Customers", "New Paying Customers")
text = text.replace("💳 Paid", "💳 New Paying Customers")
text = text.replace("Paying Customers", "New Paying Customers")

app.write_text(text, encoding="utf-8")
print(f"✅ app.py patched (backup -> {backup_app})")

# ------------------------------------------------------------
# PART B: Replace KPI rebuild logic with first-ever-payment logic
# ------------------------------------------------------------
script = ROOT / "scripts" / "fix_daily_kpis_safe.py"
backup_script = ROOT / "backups" / f"fix_daily_kpis_safe.py.first_ever_logic.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
if script.exists():
    backup_script.write_text(script.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")

script.write_text(
'''from pathlib import Path
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

def latest_daily_kpis_backup():
    candidates = []
    candidates += glob.glob(str(ROOT / "backups" / "daily_kpis.before_paid_logic_fix.*.json"))
    candidates += glob.glob(str(ROOT / "backups" / "daily_kpis.safe_fix_before_*.json"))
    candidates.sort(reverse=True)
    return Path(candidates[0]) if candidates else None

def load_base_daily_kpis():
    backup = latest_daily_kpis_backup()
    if backup and backup.exists():
        rows = json.loads(backup.read_text(encoding="utf-8"))
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

    # fallback if no backup exists
    daymap = {}
    def ensure_day(d):
        if d not in daymap:
            daymap[d] = {"date": d, "_s": set(), "_u": set()}
        return daymap[d]

    for s in find_all("signups", {}):
        if not is_accepted(s):
            continue
        d = pick_date(s, ["signup_date", "account_created_on", "created_date", "date"])
        e = norm_email(s.get("email") or s.get("email_normalized"))
        if d and e:
            ensure_day(d)["_s"].add(e)

    for u in find_all("uploads", {}):
        if not is_accepted(u):
            continue
        d = pick_date(u, ["upload_date", "first_upload_date", "created_date", "date"])
        e = norm_email(u.get("email") or u.get("email_normalized"))
        if d and e:
            ensure_day(d)["_u"].add(e)

    final = {}
    for d, b in daymap.items():
        final[d] = {
            "date": d,
            "signups": len(b["_s"]),
            "uploads": len(b["_u"]),
            "first_uploads": len(b["_u"]),
        }
    return final

def build_payment_maps():
    payments = [p for p in find_all("payments", {}) if is_accepted(p)]

    # build event rows
    rows = []
    for p in payments:
        d = pick_date(p, ["first_payment_date", "payment_date", "created_date", "date"])
        email = norm_email(p.get("email") or p.get("email_normalized"))
        if not d or not email:
            continue
        rows.append({
            "date": d,
            "email": email,
            "status": str(
                p.get("subscription_status")
                or p.get("status")
                or p.get("plan_status")
                or p.get("customer_status")
                or ""
            ).strip().lower(),
        })

    rows.sort(key=lambda x: (x["date"], x["email"]))

    # first-ever accepted payment date per email
    first_paid = {}
    for r in rows:
        if r["email"] not in first_paid:
            first_paid[r["email"]] = r["date"]

    new_by_day = {}
    recurring_by_day = {}
    stopped_by_day = {}

    def add(mapper, d, email):
        mapper.setdefault(d, set()).add(email)

    stop_statuses = {"cancelled", "canceled", "expired", "inactive", "past_due", "unpaid", "stopped"}

    for r in rows:
        d = r["date"]
        email = r["email"]

        if first_paid[email] == d:
            add(new_by_day, d, email)
        else:
            add(recurring_by_day, d, email)

        if r["status"] in stop_statuses:
            # only meaningful if not first-ever payer
            if first_paid[email] < d:
                add(stopped_by_day, d, email)

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
            "total_paying_customers": len(new_by_day.get(d, set())) + len(recurring_by_day.get(d, set())),
            "payments": len(new_by_day.get(d, set())),
            "source": "daily_kpis_safe_fix_first_ever_payment_logic",
            "rebuilt_at": datetime.utcnow().isoformat(),
        })

    db["daily_kpis"].delete_many({})
    if rows:
        db["daily_kpis"].insert_many(rows)

    month_rows = [r for r in rows if MONTH_START <= r["date"] <= TODAY]
    print(json.dumps({
        "month_signups": sum(as_int(r["signups"]) for r in month_rows),
        "month_first_uploads": sum(as_int(r["first_uploads"]) for r in month_rows),
        "month_new_paid_customers": sum(as_int(r["new_paid_customers"]) for r in month_rows),
        "month_recurring_customers": sum(as_int(r["recurring_customers"]) for r in month_rows),
        "month_stopped_recurring_customers": sum(as_int(r["stopped_recurring_customers"]) for r in month_rows),
        "month_total_paying_customers": sum(as_int(r["total_paying_customers"]) for r in month_rows),
    }, indent=2))

if __name__ == "__main__":
    main()
''',
encoding="utf-8")
print(f"✅ scripts/fix_daily_kpis_safe.py rewritten (backup -> {backup_script})")

print("✅ greeting + paid logic fix bundle complete")
