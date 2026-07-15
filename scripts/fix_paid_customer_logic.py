from pathlib import Path
from datetime import datetime, date
import json
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mongo_client import find_all, get_raw_db

NOW = date.today()
MONTH_START = NOW.replace(day=1).isoformat()
TODAY = NOW.isoformat()


def norm_email(v):
    return str(v or "").strip().lower()


def is_accepted(doc):
    return str(doc.get("final_status", "")).strip().upper() == "ACCEPTED"


def is_new_customer(doc):
    ctype = str(doc.get("customer_type", "")).strip().upper()
    if ctype == "NEW_CUSTOMER":
        return True
    try:
        if int(float(doc.get("payment_count", 0) or 0)) == 1:
            return True
    except Exception:
        pass
    return False


def pick_payment_date(doc):
    for k in ("first_payment_date", "payment_date", "date", "created_date"):
        v = str(doc.get(k, "") or "").strip()
        if v:
            return v[:10]
    return ""


def backup_collection(db, name):
    docs = list(db[name].find({}, {"_id": 0}))
    out = ROOT / "backups" / f"{name}.before_paid_logic_fix.{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(docs, indent=2, default=str), encoding="utf-8")
    print(f"BACKUP: {name} -> {out} ({len(docs)} docs)")


def inspect_current_month(db):
    payments = list(db["payments"].find({}, {"_id": 0}))
    new_rows = []
    recurring_rows = []

    for p in payments:
        if not is_accepted(p):
            continue
        dt = pick_payment_date(p)
        if not dt or dt < MONTH_START or dt > TODAY:
            continue

        row = {
            "date": dt,
            "email": norm_email(p.get("email") or p.get("email_normalized")),
            "amount": p.get("amount", p.get("total_spend")),
            "customer_type": p.get("customer_type"),
            "payment_count": p.get("payment_count"),
            "id": p.get("id"),
        }

        if is_new_customer(p):
            new_rows.append(row)
        else:
            recurring_rows.append(row)

    new_rows.sort(key=lambda x: (x["date"], x["email"]))
    recurring_rows.sort(key=lambda x: (x["date"], x["email"]))

    print("\n== CURRENT MONTH PAYMENT CLASSIFICATION ==")
    print("Month start:", MONTH_START)
    print("Today:", TODAY)
    print("NEW customers:", len(new_rows))
    for r in new_rows:
        print("  NEW      ", r)

    print("RECURRING customers:", len(recurring_rows))
    for r in recurring_rows:
        print("  RECURRING", r)


def rebuild_daily_kpis(db):
    signups = list(db["signups"].find({}, {"_id": 0}))
    uploads = list(db["uploads"].find({}, {"_id": 0}))
    payments = list(db["payments"].find({}, {"_id": 0}))

    daymap = {}

    def ensure_day(d):
        if d not in daymap:
            daymap[d] = {
                "date": d,
                "_signup_emails": set(),
                "_upload_emails": set(),
                "_new_paid_emails": set(),
                "_recurring_paid_emails": set(),
            }
        return daymap[d]

    for s in signups:
        if not is_accepted(s):
            continue
        d = str(s.get("signup_date", "") or "").strip()[:10]
        if not d:
            continue
        email = norm_email(s.get("email") or s.get("email_normalized"))
        if not email:
            continue
        ensure_day(d)["_signup_emails"].add(email)

    for u in uploads:
        if not is_accepted(u):
            continue
        d = str(u.get("upload_date", "") or "").strip()[:10]
        if not d:
            continue
        email = norm_email(u.get("email") or u.get("email_normalized"))
        if not email:
            continue
        ensure_day(d)["_upload_emails"].add(email)

    for p in payments:
        if not is_accepted(p):
            continue
        d = pick_payment_date(p)
        if not d:
            continue
        email = norm_email(p.get("email") or p.get("email_normalized"))
        if not email:
            continue
        bucket = ensure_day(d)
        if is_new_customer(p):
            bucket["_new_paid_emails"].add(email)
        else:
            bucket["_recurring_paid_emails"].add(email)

    rows = []
    for d in sorted(daymap.keys()):
        b = daymap[d]
        rows.append({
            "date": d,
            "signups": len(b["_signup_emails"]),
            "uploads": len(b["_upload_emails"]),
            "first_uploads": len(b["_upload_emails"]),
            "paid_customers": len(b["_new_paid_emails"]),   # source of truth for dashboard tile
            "new_paid_customers": len(b["_new_paid_emails"]),
            "recurring_customers": len(b["_recurring_paid_emails"]),
            "payments": len(b["_new_paid_emails"]),
            "source": "daily_kpis_rebuild_new_customer_logic",
            "rebuilt_at": datetime.utcnow().isoformat(),
        })

    backup_collection(db, "daily_kpis")
    db["daily_kpis"].delete_many({})
    if rows:
        db["daily_kpis"].insert_many(rows)

    print(f"\n✅ Rebuilt daily_kpis with {len(rows)} rows")
    latest = rows[-5:] if len(rows) >= 5 else rows
    print("Latest rows:")
    for r in latest:
        print(r)


def patch_ui_labels():
    candidates = [
        ROOT / "app.py",
        ROOT / "pages_registry.py",
        ROOT / "ui_helpers.py",
    ]
    touched = 0
    for path in candidates:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        new_text = text
        new_text = new_text.replace("Paying Customers", "New Paying Customers")
        new_text = new_text.replace("paying customers", "new paying customers")
        if new_text != text:
            backup = ROOT / "backups" / f"{path.name}.before_paid_label_fix.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
            backup.write_text(text, encoding="utf-8")
            path.write_text(new_text, encoding="utf-8")
            print(f"PATCHED UI LABEL: {path} (backup -> {backup})")
            touched += 1
    if touched == 0:
        print("No UI label patch applied automatically (string not found exactly).")


def main():
    db = get_raw_db()
    if db is None:
        raise SystemExit("❌ MongoDB/Atlas not available")

    inspect_current_month(db)
    rebuild_daily_kpis(db)
    patch_ui_labels()

    print("\n✅ Paid customer logic fix complete")


if __name__ == "__main__":
    main()
