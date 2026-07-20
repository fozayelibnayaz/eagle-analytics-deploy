from __future__ import annotations

from pathlib import Path
from datetime import datetime, date
import json
import glob
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mongo_client import find_all, get_raw_db
from kpi_totals_resolver import _all_payment_events
from source_cutover_resolver import get_cutover_date, is_countable_signup, is_countable_upload

TODAY = date.today().isoformat()
MONTH_START = date.today().replace(day=1).isoformat()

def _as_int(v):
    try:
        if v is None or str(v).strip() == "":
            return 0
        return int(float(v))
    except Exception:
        return 0

def _norm(v):
    import re
    s = str(v or "").strip()
    m = re.search(r'([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})', s)
    return m.group(1).lower() if m else s.lower()

def _pick_date(doc, keys):
    for k in keys:
        v = str(doc.get(k, "") or "").strip()
        if v:
            return v[:10]
    return ""

def _is_accepted(doc):
    return str(doc.get("final_status", "")).strip().upper() == "ACCEPTED"

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
                "signups": _as_int(r.get("signups", 0)),
                "uploads": _as_int(r.get("uploads", r.get("first_uploads", 0))),
                "first_uploads": _as_int(r.get("first_uploads", r.get("uploads", 0))),
            }
        return daymap

    daymap = {}

    def ensure_day(d):
        if d not in daymap:
            daymap[d] = {"date": d, "_s": set(), "_u": set()}
        return daymap[d]

    for s in find_all("signups", {}):
        if not _is_accepted(s):
            continue
        d = _pick_date(s, ["signup_date", "account_created_on", "created_date", "date"])
        e = _norm(s.get("email") or s.get("email_normalized"))
        if d and e and is_countable_signup(s, d):
            ensure_day(d)["_s"].add(e)

    for u in find_all("uploads", {}):
        if not _is_accepted(u):
            continue
        d = _pick_date(u, ["upload_date", "first_upload_date", "created_date", "date"])
        e = _norm(u.get("email") or u.get("email_normalized"))
        if d and e and is_countable_upload(u, d):
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
    events = _all_payment_events()
    stop_statuses = {"cancelled", "canceled", "expired", "inactive", "past_due", "unpaid", "stopped"}

    first_ever = {}
    first_in_month = {}
    stopped_map = {}

    def add(mapper, d, email):
        mapper.setdefault(d, set()).add(email)

    for e in events:
        email = e["email"]
        event_day = e["event_date"]
        candidate_first = min(event_day, e.get("first_ever_date") or event_day)

        prev = first_ever.get(email)
        if prev is None or candidate_first < prev:
            first_ever[email] = candidate_first

        if MONTH_START <= event_day <= TODAY:
            prev_month = first_in_month.get(email)
            if prev_month is None or event_day < prev_month:
                first_in_month[email] = event_day

        if e["status"] in stop_statuses and candidate_first < event_day:
            add(stopped_map, event_day, email)

    new_map = {}
    recurring_map = {}
    for email, event_day in first_in_month.items():
        if MONTH_START <= first_ever.get(email, "9999-99-99") <= TODAY:
            add(new_map, event_day, email)
        elif first_ever.get(email, "") < MONTH_START:
            add(recurring_map, event_day, email)

    return new_map, recurring_map, stopped_map

def main():
    db = get_raw_db()
    if db is None:
        raise SystemExit("MongoDB not available")

    cutover = get_cutover_date()
    print(f"Cutover date = {cutover}")
    base = load_base_daily_kpis()
    new_by_day, recurring_by_day, stopped_by_day = build_payment_maps()

    all_dates = set(base.keys()) | set(new_by_day.keys()) | set(recurring_by_day.keys()) | set(stopped_by_day.keys())
    rows = []

    for d in sorted(all_dates):
        b = base.get(d, {"date": d, "signups": 0, "uploads": 0, "first_uploads": 0})
        new_c = len(new_by_day.get(d, set()))
        rec_c = len(recurring_by_day.get(d, set()))
        stop_c = len(stopped_by_day.get(d, set()))

        rows.append({
            "date": d,
            "signups": _as_int(b.get("signups", 0)),
            "uploads": _as_int(b.get("uploads", b.get("first_uploads", 0))),
            "first_uploads": _as_int(b.get("first_uploads", b.get("uploads", 0))),
            "paid_customers": new_c,
            "new_paid_customers": new_c,
            "recurring_customers": rec_c,
            "stopped_recurring_customers": stop_c,
            "total_paying_customers": new_c + rec_c,
            "payments": new_c,
            "source": "daily_kpis_safe_fix",
            "rebuilt_at": datetime.utcnow().isoformat(),
        })

    db["daily_kpis"].delete_many({})
    if rows:
        db["daily_kpis"].insert_many(rows)

    month_rows = [r for r in rows if MONTH_START <= r["date"] <= TODAY]
    print(json.dumps({
        "month_signups": sum(_as_int(r["signups"]) for r in month_rows),
        "month_first_uploads": sum(_as_int(r["first_uploads"]) for r in month_rows),
        "month_new_paid_customers": sum(_as_int(r["new_paid_customers"]) for r in month_rows),
        "month_recurring_customers": sum(_as_int(r["recurring_customers"]) for r in month_rows),
        "month_stopped_recurring_customers": sum(_as_int(r["stopped_recurring_customers"]) for r in month_rows),
        "month_total_paying_customers": sum(_as_int(r["total_paying_customers"]) for r in month_rows),
    }, indent=2))

if __name__ == "__main__":
    main()
