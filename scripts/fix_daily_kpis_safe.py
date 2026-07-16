from pathlib import Path
from datetime import datetime, date
import json
import glob
import re
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


def as_float(v):
    try:
        if v is None or str(v).strip() == "":
            return 0.0
        return float(v)
    except Exception:
        return 0.0


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
    candidates += glob.glob(str(ROOT / "backups" / "linkedin_export_reset_*" / "daily_kpis.json"))
    candidates += glob.glob(str(ROOT / "backups" / "linkedin_reimport_reset_*" / "daily_kpis.json"))

    if not candidates:
        return None

    candidates.sort(reverse=True)
    return Path(candidates[0])


def load_base_daily_kpis():
    backup = latest_daily_kpis_backup()
    if backup and backup.exists():
        print(f"Using daily_kpis backup as base: {backup}")
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

    print("No daily_kpis backup found. Falling back to raw signups/uploads collections.")
    daymap = {}

    def ensure_day(d):
        if d not in daymap:
            daymap[d] = {
                "date": d,
                "_signup_emails": set(),
                "_upload_emails": set(),
            }
        return daymap[d]

    for s in find_all("signups", {}):
        if not is_accepted(s):
            continue
        d = pick_date(s, ["signup_date", "account_created_on", "created_date", "date"])
        if not d:
            continue
        email = norm_email(s.get("email") or s.get("email_normalized"))
        if email:
            ensure_day(d)["_signup_emails"].add(email)

    for u in find_all("uploads", {}):
        if not is_accepted(u):
            continue
        d = pick_date(u, ["upload_date", "first_upload_date", "created_date", "date"])
        if not d:
            continue
        email = norm_email(u.get("email") or u.get("email_normalized"))
        if email:
            ensure_day(d)["_upload_emails"].add(email)

    final = {}
    for d, b in daymap.items():
        final[d] = {
            "date": d,
            "signups": len(b["_signup_emails"]),
            "uploads": len(b["_upload_emails"]),
            "first_uploads": len(b["_upload_emails"]),
        }
    return final


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

    def add_day(mapper, d, email):
        mapper.setdefault(d, set()).add(email)

    for r in rows:
        d = r["date"]
        email = r["email"]
        if r["customer_type"] == "NEW_CUSTOMER":
            add_day(new_by_day, d, email)
        elif r["customer_type"] == "RECURRING":
            add_day(recurring_by_day, d, email)
        else:
            if first_payment_by_email.get(email) == d or r["payment_count"] == 1:
                add_day(new_by_day, d, email)
            else:
                add_day(recurring_by_day, d, email)

    # Best-effort stopped recurring logic from status fields
    stop_statuses = {
        "cancelled", "canceled", "expired", "inactive", "past_due", "unpaid", "stopped"
    }
    stopped_by_day = {}
    for r in rows:
        if r["status"] in stop_statuses and r["payment_count"] > 1:
            add_day(stopped_by_day, r["date"], r["email"])

    return new_by_day, recurring_by_day, stopped_by_day


def main():
    db = get_raw_db()
    if db is None:
        raise SystemExit("❌ MongoDB/Atlas not available")

    base = load_base_daily_kpis()
    new_by_day, recurring_by_day, stopped_by_day = build_payment_maps()

    all_dates = set(base.keys()) | set(new_by_day.keys()) | set(recurring_by_day.keys()) | set(stopped_by_day.keys())
    rows = []

    for d in sorted(all_dates):
        b = base.get(d, {"date": d, "signups": 0, "uploads": 0, "first_uploads": 0})
        new_count = len(new_by_day.get(d, set()))
        recurring_count = len(recurring_by_day.get(d, set()))
        stopped_count = len(stopped_by_day.get(d, set()))

        rows.append({
            "date": d,
            "signups": as_int(b.get("signups", 0)),
            "uploads": as_int(b.get("uploads", b.get("first_uploads", 0))),
            "first_uploads": as_int(b.get("first_uploads", b.get("uploads", 0))),
            "paid_customers": new_count,               # existing UI should use this
            "new_paid_customers": new_count,
            "recurring_customers": recurring_count,
            "stopped_recurring_customers": stopped_count,
            "payments": new_count,
            "source": "daily_kpis_safe_fix",
            "rebuilt_at": datetime.utcnow().isoformat(),
        })

    backup_path = ROOT / "backups" / f"daily_kpis.safe_fix_before_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    current_docs = list(db["daily_kpis"].find({}, {"_id": 0}))
    backup_path.write_text(json.dumps(current_docs, indent=2, default=str), encoding="utf-8")
    print(f"BACKUP: current daily_kpis -> {backup_path} ({len(current_docs)} rows)")

    db["daily_kpis"].delete_many({})
    if rows:
        db["daily_kpis"].insert_many(rows)

    month_rows = [r for r in rows if MONTH_START <= r["date"] <= TODAY]
    print("\n== THIS MONTH KPI TOTALS ==")
    print("signups =", sum(as_int(r["signups"]) for r in month_rows))
    print("first_uploads =", sum(as_int(r["first_uploads"]) for r in month_rows))
    print("new_paid_customers =", sum(as_int(r["new_paid_customers"]) for r in month_rows))
    print("recurring_customers =", sum(as_int(r["recurring_customers"]) for r in month_rows))
    print("stopped_recurring_customers =", sum(as_int(r["stopped_recurring_customers"]) for r in month_rows))

    print("\nLatest 10 rows:")
    for r in rows[-10:]:
        print(r)

    print("\n✅ daily_kpis rebuilt safely with preserved signup/upload counts and corrected paid logic")


if __name__ == "__main__":
    main()
