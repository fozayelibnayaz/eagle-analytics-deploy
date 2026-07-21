from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import MongoClient

APP = FastAPI(title="Eagle Analytics Webhook API", version="2.0.0")

MONGO_URI = os.environ.get("MONGO_URI", "").strip()
MONGO_DB = os.environ.get("MONGO_DB", "eagle3d").strip()
WEBHOOK_API_KEY = os.environ.get("WEBHOOK_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

if not MONGO_URI:
    raise RuntimeError("MONGO_URI is required")

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
db = client[MONGO_DB]

BD_TZ = ZoneInfo("Asia/Dhaka")


class WebhookItem(BaseModel):
    type: str
    info: Dict[str, Any] = Field(default_factory=dict)


class WebhookPayload(BaseModel):
    source: str = "unknown"
    data: List[WebhookItem]


def send_telegram(msg: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        payload = json.dumps({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown",
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode())
            return bool(body.get("ok"))
    except Exception:
        return False


def normalize_email(v: Any) -> str:
    s = str(v or "").strip()
    m = re.search(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", s)
    return m.group(1).lower() if m else s.lower()


def normalize_username(v: Any) -> str:
    return str(v or "").strip().lower()


def local_now() -> datetime:
    return datetime.now(BD_TZ)

def pick_day(*values: Any) -> str:
    for v in values:
        s = str(v or "").strip()
        if s:
            return s[:10]
    return local_now().date().isoformat()


def month_key(day: str) -> str:
    return str(day or "")[:7]


def add_month(yyyy_mm: str) -> str:
    y, m = yyyy_mm.split("-")
    y = int(y)
    m = int(m)
    if m == 12:
        return f"{y+1:04d}-01"
    return f"{y:04d}-{m+1:02d}"


def now_iso() -> str:
    return local_now().isoformat()


def require_key(x_api_key: str | None):
    if not WEBHOOK_API_KEY:
        raise HTTPException(status_code=500, detail="WEBHOOK_API_KEY not configured")
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    if x_api_key != WEBHOOK_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")


def find_signup_by_username(username_normalized: str) -> Optional[Dict[str, Any]]:
    if not username_normalized:
        return None
    return db["signups"].find_one({"username_normalized": username_normalized})


def unresolved(kind: str, source: str, info: Dict[str, Any], reason: str) -> Dict[str, Any]:
    doc = {
        "kind": kind,
        "source": source,
        "reason": reason,
        "info": dict(info or {}),
        "received_at": now_iso(),
    }
    db["webhook_unresolved"].insert_one(doc)
    return {"ok": False, "error": reason}


def signup_lookup(username: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    uname = normalize_username(username)
    signup = find_signup_by_username(uname)
    if not signup:
        return None, f"username not mapped to a signup yet: {uname}"
    email = normalize_email(signup.get("email") or signup.get("email_normalized"))
    if not email:
        return None, f"signup exists but email is missing for username: {uname}"
    return signup, None


def upsert_signup(source: str, info: Dict[str, Any]) -> Dict[str, Any]:
    email = normalize_email(info.get("email"))
    username = str(info.get("username") or "").strip()
    username_normalized = normalize_username(username)
    signup_date = pick_day(info.get("signup_date"), info.get("created_at"), info.get("date"))

    if not email:
        return {"ok": False, "error": "signup missing email"}
    if not username_normalized:
        return {"ok": False, "error": "signup missing username"}

    existing = db["signups"].find_one({
        "$or": [
            {"email_normalized": email},
            {"username_normalized": username_normalized},
        ]
    })
    selector = {"_id": existing["_id"]} if existing else {"email_normalized": email}

    doc = dict(info)
    doc.update({
        "event_type": "signup",
        "email": email,
        "email_normalized": email,
        "username": username,
        "username_normalized": username_normalized,
        "signup_date": signup_date,
        "source": source,
        "final_status": "ACCEPTED",
        "_updated_at": now_iso(),
    })

    db["signups"].update_one(selector, {"$set": doc}, upsert=True)
    return {"ok": True, "email": email, "username": username_normalized}


def upsert_upload(source: str, info: Dict[str, Any]) -> Dict[str, Any]:
    username = str(info.get("username") or "").strip()
    username_normalized = normalize_username(username)
    upload_date = pick_day(info.get("upload_date"), info.get("created_at"), info.get("date"))
    app_name = str(info.get("app_name") or info.get("appname") or "").strip()

    if not username_normalized:
        return unresolved("upload", source, info, "upload missing username")

    signup, err = signup_lookup(username_normalized)
    if err:
        return unresolved("upload", source, info, err)

    email = normalize_email(signup.get("email") or signup.get("email_normalized"))
    lead_source = info.get("lead_source") or signup.get("lead_source")

    doc = dict(info)
    doc.update({
        "event_type": "upload",
        "username": username,
        "username_normalized": username_normalized,
        "email": email,
        "email_normalized": email,
        "signup_date": str(signup.get("signup_date") or "")[:10],
        "upload_date": upload_date,
        "app_name": app_name,
        "source": source,
        "lead_source": lead_source,
        "final_status": "ACCEPTED",
        "_updated_at": now_iso(),
    })

    db["uploads"].update_one(
        {"username_normalized": username_normalized},
        {"$set": doc},
        upsert=True,
    )
    return {"ok": True, "email": email, "username": username_normalized, "app_name": app_name}


def classify_payment(history: Optional[Dict[str, Any]], payment_date: str) -> Dict[str, Any]:
    history = history or {}
    current_month = month_key(payment_date)
    paid_months = sorted(set(str(x)[:7] for x in (history.get("paid_months") or []) if str(x).strip()))
    prev_latest_date = str(history.get("latest_payment_date") or "")[:10]
    prev_latest_month = month_key(prev_latest_date) if prev_latest_date else ""
    consecutive_before = int(history.get("consecutive_paid_months") or 0)

    if not paid_months:
        return {
            "customer_type": "NEW_CUSTOMER",
            "lifecycle_label": "NEW_CUSTOMER",
            "paid_months": [current_month],
            "paid_months_count": 1,
            "consecutive_paid_months": 1,
            "first_ever_payment_date": payment_date,
            "reactivated": False,
        }

    new_paid_months = sorted(set(paid_months + [current_month]))
    paid_months_count = len(new_paid_months)

    if current_month in paid_months and prev_latest_date and payment_date <= prev_latest_date:
        return {
            "customer_type": history.get("customer_type") or "RECURRING_CUSTOMER",
            "lifecycle_label": history.get("lifecycle_label") or "RECURRING_CUSTOMER",
            "paid_months": paid_months,
            "paid_months_count": int(history.get("paid_months_count") or len(paid_months)),
            "consecutive_paid_months": consecutive_before or 1,
            "first_ever_payment_date": str(history.get("first_ever_payment_date") or payment_date)[:10],
            "reactivated": bool(history.get("reactivated", False)),
        }

    if prev_latest_month and current_month == add_month(prev_latest_month):
        return {
            "customer_type": "RECURRING_CUSTOMER",
            "lifecycle_label": f"RECURRING_CUSTOMER_{paid_months_count}_MONTHS",
            "paid_months": new_paid_months,
            "paid_months_count": paid_months_count,
            "consecutive_paid_months": (consecutive_before or 1) + (0 if current_month in paid_months else 1),
            "first_ever_payment_date": str(history.get("first_ever_payment_date") or payment_date)[:10],
            "reactivated": False,
        }

    return {
        "customer_type": "CHURNED_CUSTOMER_RETURNED",
        "lifecycle_label": f"CHURNED_CUSTOMER_RETURNED_{paid_months_count}_MONTHS_TOTAL",
        "paid_months": new_paid_months,
        "paid_months_count": paid_months_count,
        "consecutive_paid_months": 1,
        "first_ever_payment_date": str(history.get("first_ever_payment_date") or payment_date)[:10],
        "reactivated": True,
    }


def upsert_payment(source: str, info: Dict[str, Any]) -> Dict[str, Any]:
    username = str(info.get("username") or "").strip()
    username_normalized = normalize_username(username)
    amount = float(info.get("amount", 0) or 0)
    subscription = str(info.get("subscription") or info.get("plan") or info.get("product") or "").strip()
    payment_date = pick_day(
        info.get("payment_date"),
        info.get("first_payment_date"),
        info.get("paid_at"),
        info.get("created_at"),
        info.get("date"),
    )

    if not username_normalized:
        return unresolved("payment", source, info, "payment missing username")
    if amount <= 0:
        return unresolved("payment", source, info, "payment missing/invalid amount")

    signup, err = signup_lookup(username_normalized)
    if err:
        return unresolved("payment", source, info, err)

    email = normalize_email(signup.get("email") or signup.get("email_normalized"))
    history = db["payment_history"].find_one({"email_normalized": email}) or {}
    classification = classify_payment(history, payment_date)

    payment_id = (
        str(info.get("payment_id") or info.get("invoice_id") or info.get("charge_id") or info.get("id") or "").strip()
        or f"{username_normalized}|{payment_date}|{amount:.2f}|{subscription or 'subscription-na'}"
    )

    existing_event = db["payments"].find_one({"_id": payment_id}, {"_id": 1})
    if existing_event:
        return {
            "ok": True,
            "duplicate": True,
            "payment_id": payment_id,
            "email": email,
            "username": username_normalized,
        }

    event_doc = dict(info)
    event_doc.update({
        "_id": payment_id,
        "event_type": "payment",
        "email": email,
        "email_normalized": email,
        "username": username,
        "username_normalized": username_normalized,
        "lead_source": signup.get("lead_source"),
        "signup_date": str(signup.get("signup_date") or "")[:10],
        "first_payment_date": payment_date,
        "payment_date": payment_date,
        "first_ever_payment_date": classification["first_ever_payment_date"],
        "amount": amount,
        "total_spend": amount,
        "currency": "USD",
        "subscription": subscription,
        "customer_type": classification["customer_type"],
        "lifecycle_label": classification["lifecycle_label"],
        "paid_months_count": classification["paid_months_count"],
        "consecutive_paid_months": classification["consecutive_paid_months"],
        "reactivated": classification["reactivated"],
        "source": source,
        "final_status": "ACCEPTED",
        "_updated_at": now_iso(),
    })
    db["payments"].insert_one(event_doc)

    prev_count = int(history.get("payment_count") or 0)
    prev_revenue = float(history.get("lifetime_revenue_usd") or 0.0)
    history_doc = {
        "email": email,
        "email_normalized": email,
        "username": username,
        "username_normalized": username_normalized,
        "lead_source": signup.get("lead_source"),
        "first_signup_date": str(signup.get("signup_date") or "")[:10],
        "first_ever_payment_date": classification["first_ever_payment_date"],
        "latest_payment_date": payment_date,
        "payment_count": prev_count + 1,
        "paid_months": classification["paid_months"],
        "paid_months_count": classification["paid_months_count"],
        "consecutive_paid_months": classification["consecutive_paid_months"],
        "customer_type": classification["customer_type"],
        "lifecycle_label": classification["lifecycle_label"],
        "reactivated": classification["reactivated"],
        "last_subscription": subscription,
        "last_amount_usd": amount,
        "lifetime_revenue_usd": round(prev_revenue + amount, 2),
        "currency": "USD",
        "final_status": "ACCEPTED",
        "source": source,
        "_updated_at": now_iso(),
    }
    db["payment_history"].update_one(
        {"email_normalized": email},
        {"$set": history_doc},
        upsert=True,
    )

    warning = None
    if not any(info.get(k) for k in ("payment_date", "first_payment_date", "paid_at", "created_at", "date")):
        warning = f"payment_date missing in payload; defaulted to {payment_date}"

    return {
        "ok": True,
        "payment_id": payment_id,
        "email": email,
        "username": username_normalized,
        "customer_type": classification["customer_type"],
        "lifecycle_label": classification["lifecycle_label"],
        "amount": amount,
        "warning": warning,
    }


@APP.get("/")
def root():
    return {
        "ok": True,
        "service": "eagle-analytics-webhook-api",
        "db": MONGO_DB,
        "endpoints": ["/health", "/docs", "/webhook", "/webhook/test", "/webhook/log"],
        "time": now_iso(),
    }


@APP.get("/health")
def health():
    try:
        client.admin.command("ping")
        return {"ok": True, "db": MONGO_DB, "time": now_iso()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@APP.get("/webhook/test")
def webhook_test(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    require_key(x_api_key)
    return {
        "source": "aninda-backend",
        "data": [
            {
                "type": "signup",
                "info": {
                    "lead_source": "Google",
                    "signup_date": local_now().date().isoformat(),
                    "email": "demo.user@company.com",
                    "username": "demouser"
                }
            },
            {
                "type": "upload",
                "info": {
                    "username": "demouser",
                    "appname": "Demo",
                    "lead_source": "Google",
                    "upload_date": local_now().date().isoformat()
                }
            },
            {
                "type": "payment",
                "info": {
                    "username": "demouser",
                    "amount": 70,
                    "subscription": "Pre Paid Minute",
                    "payment_date": local_now().date().isoformat()
                }
            }
        ]
    }


@APP.get("/webhook/log")
def webhook_log(limit: int = Query(default=20, ge=1, le=200), x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    require_key(x_api_key)
    rows = list(db["webhook_log"].find({}, {"_id": 0}).sort("received_at", -1).limit(limit))
    return {"ok": True, "rows": rows}


@APP.post("/webhook")
def webhook(payload: WebhookPayload, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    require_key(x_api_key)

    source = str(payload.source or "unknown").strip()
    results = {
        "signups": [],
        "uploads": [],
        "payments": [],
        "errors": [],
    }
    processed = {"signups": 0, "uploads": 0, "payments": 0}

    for item in payload.data:
        kind = str(item.type or "").strip().lower()
        info = dict(item.info or {})

        if kind == "signup":
            res = upsert_signup(source, info)
            if res.get("ok"):
                processed["signups"] += 1
                results["signups"].append(res)
            else:
                results["errors"].append(res)

        elif kind == "upload":
            res = upsert_upload(source, info)
            if res.get("ok"):
                processed["uploads"] += 1
                results["uploads"].append(res)
            else:
                results["errors"].append(res)

        elif kind == "payment":
            res = upsert_payment(source, info)
            if res.get("ok"):
                processed["payments"] += 1
                results["payments"].append(res)
            else:
                results["errors"].append(res)
        else:
            results["errors"].append({"ok": False, "error": f"unknown type: {kind}"})

    received_at = now_iso()
    log_doc = {
        "source": source,
        "processed": processed,
        "errors_count": len(results["errors"]),
        "results": results,
        "received_at": received_at,
    }
    db["webhook_log"].insert_one(log_doc)

    if processed["signups"] or processed["uploads"] or processed["payments"]:
        send_telegram(
            f"🔔 *Webhook Sync*\\n"
            f"Source: `{source}`\\n"
            f"Signups: *{processed['signups']}*\\n"
            f"Uploads: *{processed['uploads']}*\\n"
            f"Payments: *{processed['payments']}*\\n"
            f"Time: `{received_at}`"
        )

    return {
        "success": len(results["errors"]) == 0,
        "processed": processed,
        "errors_count": len(results["errors"]),
        "results": results,
        "received_at": received_at,
    }
