from pathlib import Path
from datetime import datetime
import json
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mongo_client import get_raw_db, find_all

db = get_raw_db()
if db is None:
    raise SystemExit("❌ MongoDB/Atlas not available")

EMAIL_PATTERN = re.compile(r'([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})')

COLLECTIONS = [
    "payments",
    "payment_history",
    "sheet_verified_stripe",
    "sheet_raw_stripe",
    "signups",
    "uploads",
]

def extract_email(v):
    s = str(v or "").strip()
    if not s:
        return ""
    m = EMAIL_PATTERN.search(s)
    return m.group(1).lower() if m else s.lower()

def pick_date(doc):
    for k in ("first_payment_date", "payment_date", "created_date", "date"):
        v = str(doc.get(k, "") or "").strip()
        if v:
            return v[:10]
    return ""

def as_amount(doc):
    for k in ("amount", "total_spend", "paid_amount", "invoice_amount", "first_ever_amount"):
        v = doc.get(k)
        try:
            if v not in (None, "", 0, "0"):
                return float(v)
        except Exception:
            pass
    return 0.0

def is_accepted(doc):
    fs = str(doc.get("final_status", "")).strip().upper()
    if fs:
        return fs == "ACCEPTED"
    return as_amount(doc) > 0

print("== NORMALIZING EMAIL FIELDS ==")
for col in COLLECTIONS:
    docs = list(db[col].find({}))
    changed = 0
    for d in docs:
        updates = {}
        raw_email = d.get("email")
        raw_norm = d.get("email_normalized")

        if raw_email is not None:
            clean = extract_email(raw_email)
            if clean and clean != raw_email:
                updates["email"] = clean

        if raw_norm is not None:
            clean = extract_email(raw_norm)
            if clean and clean != raw_norm:
                updates["email_normalized"] = clean

        if raw_email and "email_normalized" not in updates:
            clean = extract_email(raw_email)
            if clean and clean != d.get("email_normalized"):
                updates["email_normalized"] = clean

        if updates:
            db[col].update_one({"_id": d["_id"]}, {"$set": updates})
            changed += 1
    print(f"{col}: changed {changed} docs")

print("\n== REBUILDING payment_history FIRST-EVER PAYMENT TRUTH ==")
payment_sources = ["payments", "sheet_verified_stripe", "sheet_raw_stripe"]
events = []
seen = set()

for col in payment_sources:
    for d in find_all(col, {}):
        if not is_accepted(d):
            continue
        email = extract_email(d.get("email") or d.get("email_normalized"))
        dt = pick_date(d)
        amt = as_amount(d)
        if not email or not dt or amt <= 0:
            continue
        if email.endswith("@example.com") or "webhook-test" in email or "cloud-test" in email:
            continue
        sig = (email, dt, round(amt, 2))
        if sig in seen:
            continue
        seen.add(sig)
        events.append({
            "email_normalized": email,
            "first_ever_payment_date": dt,
            "first_ever_amount": amt,
            "recorded_at": datetime.utcnow().isoformat(),
        })

events.sort(key=lambda x: (x["email_normalized"], x["first_ever_payment_date"]))

first_map = {}
for e in events:
    first_map.setdefault(e["email_normalized"], e)

db["payment_history"].delete_many({})
if first_map:
    db["payment_history"].insert_many(list(first_map.values()))
print(f"payment_history rebuilt with {len(first_map)} unique emails")

print("\n== PATCHING payment rows WITH first_ever_payment_date ==")
for col in ["payments", "sheet_verified_stripe"]:
    docs = list(db[col].find({}))
    changed = 0
    for d in docs:
        email = extract_email(d.get("email") or d.get("email_normalized"))
        if not email:
            continue
        first = first_map.get(email)
        if not first:
            continue
        updates = {
            "email_normalized": email,
            "first_ever_payment_date": first["first_ever_payment_date"],
        }
        db[col].update_one({"_id": d["_id"]}, {"$set": updates})
        changed += 1
    print(f"{col}: patched {changed} docs with first_ever_payment_date")

print("\n✅ Email normalization + payment truth rebuild complete")
