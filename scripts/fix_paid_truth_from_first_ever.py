from pathlib import Path
from datetime import datetime
import textwrap

ROOT = Path.cwd()
BACKUPS = ROOT / "backups"
BACKUPS.mkdir(exist_ok=True)

def backup(path: Path):
    if path.exists():
        b = BACKUPS / f"{path.name}.paid_truth_fix.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
        b.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        print(f"BACKUP: {path} -> {b}")

# ------------------------------------------------------------
# kpi_totals_resolver.py
# ------------------------------------------------------------
resolver = ROOT / "kpi_totals_resolver.py"
backup(resolver)
resolver.write_text(textwrap.dedent("""\
from __future__ import annotations

from typing import Tuple, Dict
from mongo_client import find_all

def _as_int(v):
    try:
        if v is None or str(v).strip() == "":
            return 0
        return int(float(v))
    except Exception:
        return 0

def _as_float(v):
    try:
        if v is None or str(v).strip() == "":
            return 0.0
        return float(v)
    except Exception:
        return 0.0

def _norm(v):
    return str(v or "").strip().lower()

def _pick_event_date(doc):
    for k in ("first_payment_date", "payment_date", "created_date", "date"):
        v = str(doc.get(k, "") or "").strip()
        if v:
            return v[:10]
    return ""

def _pick_first_ever_date(doc):
    for k in ("first_ever_payment_date", "first_payment_date", "payment_date", "created_date", "date"):
        v = str(doc.get(k, "") or "").strip()
        if v:
            return v[:10]
    return ""

def _pick_amount(doc):
    for k in ("amount", "total_spend", "paid_amount", "invoice_amount", "first_ever_amount"):
        v = doc.get(k)
        if v not in (None, "", 0, "0"):
            return _as_float(v)
    return 0.0

def _is_accepted(doc):
    fs = str(doc.get("final_status", "")).strip().upper()
    if fs:
        return fs == "ACCEPTED"
    return _pick_amount(doc) > 0

def _all_payment_events():
    collections = [
        "payments",
        "payment_history",
        "sheet_verified_stripe",
        "sheet_raw_stripe",
    ]

    rows = []
    seen = set()

    for col in collections:
        try:
            docs = find_all(col, {})
        except Exception:
            docs = []

        for d in docs:
            if not _is_accepted(d):
                continue

            email = _norm(d.get("email") or d.get("email_normalized"))
            event_date = _pick_event_date(d)
            first_ever_date = _pick_first_ever_date(d)
            amount = _pick_amount(d)

            if not email or not event_date or amount <= 0:
                continue

            # exclude known synthetic test emails
            if email.endswith("@example.com") or "webhook-test" in email or "cloud-test" in email:
                continue

            sig = (email, event_date, round(amount, 2))
            if sig in seen:
                continue
            seen.add(sig)

            rows.append({
                "email": email,
                "event_date": event_date,
                "first_ever_date": first_ever_date or event_date,
                "amount": amount,
                "status": str(
                    d.get("subscription_status")
                    or d.get("status")
                    or d.get("plan_status")
                    or d.get("customer_status")
                    or ""
                ).strip().lower(),
                "collection": col,
                "id": d.get("id"),
            })

    rows.sort(key=lambda x: (x["email"], x["event_date"], x["collection"]))
    return rows

def resolve_period_kpis(start_iso: str, end_iso: str) -> Tuple[int, int, int]:
    start_day = str(start_iso or "")[:10]
    end_day = str(end_iso or "")[:10]

    daily = find_all(
        "daily_kpis",
        filters={"date": {"$gte": start_day, "$lte": end_day}},
        sort=[("date", 1)],
        limit=10000,
    )

    signups = sum(_as_int(r.get("signups", 0)) for r in daily)
    uploads = sum(_as_int(r.get("first_uploads", r.get("uploads", 0))) for r in daily)

    events = _all_payment_events()
    new_paid = len({
        e["email"] for e in events
        if start_day <= e["event_date"] <= end_day
        and e["first_ever_date"] == e["event_date"]
    })

    return signups, uploads, new_paid

def resolve_paid_breakdown(start_iso: str, end_iso: str) -> Dict[str, int]:
    start_day = str(start_iso or "")[:10]
    end_day = str(end_iso or "")[:10]
    stop_statuses = {"cancelled", "canceled", "expired", "inactive", "past_due", "unpaid", "stopped"}

    events = _all_payment_events()
    new_set = set()
    recurring_set = set()
    stopped_set = set()

    for e in events:
        if not (start_day <= e["event_date"] <= end_day):
            continue
        if e["first_ever_date"] == e["event_date"]:
            new_set.add(e["email"])
        else:
            recurring_set.add(e["email"])

        if e["status"] in stop_statuses and e["first_ever_date"] < e["event_date"]:
            stopped_set.add(e["email"])

    return {
        "new_paid_customers": len(new_set),
        "recurring_customers": len(recurring_set),
        "stopped_recurring_customers": len(stopped_set),
        "total_paying_customers": len(new_set | recurring_set),
    }
"""), encoding="utf-8")
print("✅ kpi_totals_resolver.py rewritten with first_ever_payment_date logic")

# ------------------------------------------------------------
# scripts/fix_daily_kpis_safe.py
# ------------------------------------------------------------
kpi_fix = ROOT / "scripts" / "fix_daily_kpis_safe.py"
backup(kpi_fix)
kpi_fix.write_text(textwrap.dedent("""\
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
    return str(v or "").strip().lower()

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
        if d and e:
            ensure_day(d)["_s"].add(e)

    for u in find_all("uploads", {}):
        if not _is_accepted(u):
            continue
        d = _pick_date(u, ["upload_date", "first_upload_date", "created_date", "date"])
        e = _norm(u.get("email") or u.get("email_normalized"))
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
    events = _all_payment_events()
    stop_statuses = {"cancelled", "canceled", "expired", "inactive", "past_due", "unpaid", "stopped"}

    new_map = {}
    recurring_map = {}
    stopped_map = {}

    def add(mapper, d, email):
        mapper.setdefault(d, set()).add(email)

    for e in events:
        d = e["event_date"]
        email = e["email"]

        if e["first_ever_date"] == e["event_date"]:
            add(new_map, d, email)
        else:
            add(recurring_map, d, email)

        if e["status"] in stop_statuses and e["first_ever_date"] < e["event_date"]:
            add(stopped_map, d, email)

    return new_map, recurring_map, stopped_map

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
"""), encoding="utf-8")
print("✅ scripts/fix_daily_kpis_safe.py rewritten with first_ever logic")

print("✅ paid truth fix bundle complete")
