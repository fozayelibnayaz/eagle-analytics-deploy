from __future__ import annotations

import json
import os
import re
import uuid
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import MongoClient, ASCENDING

APP = FastAPI(title="Eagle Analytics Webhook API", version="6.0.0")

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


def local_now() -> datetime:
    return datetime.now(BD_TZ)


def now_iso() -> str:
    return local_now().isoformat()


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


def normalize_email(v: Any) -> str:
    s = str(v or "").strip().replace("mailto:", "")
    m = re.search(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", s)
    return m.group(1).lower() if m else s.lower()


def normalize_username(v: Any) -> str:
    return str(v or "").strip().lower()


def parse_amount(v: Any) -> Optional[float]:
    try:
        amt = float(v)
        if amt <= 0:
            return None
        return amt
    except Exception:
        return None


def pretty_time(iso_value: str) -> str:
    s = str(iso_value or "").strip()
    if not s:
        return "unknown time"
    try:
        dt = datetime.fromisoformat(s)
        return dt.strftime("%Y-%m-%d %H:%M (%Z)") if dt.tzinfo else dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return s


def kind_label(kind: str) -> str:
    k = str(kind or "").strip().lower()
    return {
        "signup": "Sign-up",
        "upload": "Project upload",
        "payment": "Payment",
    }.get(k, k or "Unknown")


def humanize_error(reason: str) -> str:
    r = str(reason or "").strip()
    if "signup missing email" in r:
        return "The sign-up data did not include an email address."
    if "signup missing username" in r:
        return "The sign-up data did not include a username."
    if "upload missing username" in r:
        return "The project upload data did not include a username."
    if "upload missing appname" in r:
        return "The project upload data did not include the project/app name."
    if "payment missing username" in r:
        return "The payment data did not include a username."
    if "payment missing/invalid amount" in r:
        return "The payment amount was missing or invalid."
    if "payment missing subscription" in r:
        return "The payment data did not include the subscription name."
    if "username not mapped to a signup yet" in r:
        return "This username is not linked to any saved sign-up yet. Please send the sign-up data first or make sure the username already exists in the system."
    if "duplicate key error" in r:
        return "This record already exists in the older database structure. The system should update it instead of inserting a duplicate."
    if "internal_processing_error" in r:
        return "The server received the data, but processing failed internally. Please check the payload and server logs."
    return r[:400]


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


def send_success_alert(source: str, processed: Dict[str, int], results: Dict[str, Any], received_at: str) -> None:
    success_items: List[Dict[str, Any]] = []
    success_items.extend(results.get("signups", []))
    success_items.extend(results.get("uploads", []))
    success_items.extend(results.get("payments", []))

    duplicates = sum(1 for item in success_items if item.get("duplicate"))
    warnings = [str(item.get("warning")) for item in success_items if item.get("warning")]
    failed = len(results.get("errors", []))

    lines = [
        "✅ *Webhook Update Received*",
        "",
        f"Source: `{source}`",
        f"Time: `{pretty_time(received_at)}`",
        "",
        "*Saved successfully:*",
        f"• Sign-ups: *{processed.get('signups', 0)}*",
        f"• Project uploads: *{processed.get('uploads', 0)}*",
        f"• Payments: *{processed.get('payments', 0)}*",
        "",
        "*Also handled safely:*",
        f"• Existing records updated from replay/history: *{duplicates}*",
        f"• Failed records: *{failed}*",
    ]

    if warnings:
        lines.append(f"• Automatic fallback values used: *{len(warnings)}*")

    if failed == 0:
        lines += ["", "Everything received in this webhook call was handled successfully."]

    send_telegram("\n".join(lines))


def send_error_alert(source: str, errors: List[Dict[str, Any]], received_at: str) -> None:
    if not errors:
        return

    lines = [
        "⚠️ *Some webhook records could not be saved*",
        "",
        f"Source: `{source}`",
        f"Time: `{pretty_time(received_at)}`",
        f"Problem count: *{len(errors)}*",
        ""
    ]

    for i, err in enumerate(errors[:10], start=1):
        kind = kind_label(err.get("kind") or err.get("type") or "unknown")
        username = str(err.get("username") or err.get("info", {}).get("username") or "").strip()
        email = str(err.get("email") or err.get("info", {}).get("email") or "").strip()
        reason = humanize_error(err.get("error") or err.get("reason") or "unknown error")

        lines.append(f"*{i}) {kind}*")
        if username:
            lines.append(f"• Username: `{username}`")
        if email:
            lines.append(f"• Email: `{email}`")
        lines.append(f"• Issue: {reason}")

        raw = json.dumps(err.get("info", {}), ensure_ascii=False)[:300]
        if raw:
            lines.append(f"• Payload: `{raw}`")
        lines.append("")

    send_telegram("\n".join(lines))


def require_key(x_api_key: str | None):
    if not WEBHOOK_API_KEY:
        raise HTTPException(status_code=500, detail="WEBHOOK_API_KEY not configured")
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    if x_api_key != WEBHOOK_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")


def drop_unique_index_if_exists(coll_name: str, index_name: str) -> None:
    try:
        for idx in db[coll_name].list_indexes():
            if idx.get("name") == index_name and idx.get("unique"):
                db[coll_name].drop_index(index_name)
                break
    except Exception:
        pass


def ensure_indexes() -> None:
    try:
        drop_unique_index_if_exists("uploads", "email_normalized_1")
        drop_unique_index_if_exists("uploads", "username_normalized_1")
        drop_unique_index_if_exists("payments", "email_normalized_1")
        drop_unique_index_if_exists("payments", "username_normalized_1")

        db["signups"].create_index([("email_normalized", ASCENDING)])
        db["signups"].create_index([("username_normalized", ASCENDING)])

        db["username_registry"].create_index([("username_normalized", ASCENDING)], unique=True)
        db["username_registry"].create_index([("email_normalized", ASCENDING)])

        db["uploads"].create_index([("username_normalized", ASCENDING)])
        db["uploads"].create_index([("email_normalized", ASCENDING)])

        db["payments"].create_index([("username_normalized", ASCENDING)])
        db["payments"].create_index([("email_normalized", ASCENDING)])
        db["payments"].create_index([("payment_date", ASCENDING)])

        db["payment_history"].create_index([("email_normalized", ASCENDING)], unique=True)

        db["signups_webhook"].create_index([("username_normalized", ASCENDING)], unique=True)
        db["uploads_webhook"].create_index([("username_normalized", ASCENDING)], unique=True)
        db["payments_webhook"].create_index([("username_normalized", ASCENDING)], unique=True)

        db["signups_raw_webhook"].create_index([("received_at", ASCENDING)])
        db["signups_raw_webhook"].create_index([("username_normalized", ASCENDING)])
        db["uploads_raw_webhook"].create_index([("received_at", ASCENDING)])
        db["uploads_raw_webhook"].create_index([("username_normalized", ASCENDING)])
        db["payments_raw_webhook"].create_index([("received_at", ASCENDING)])
        db["payments_raw_webhook"].create_index([("username_normalized", ASCENDING)])
        db["payments_raw_webhook"].create_index([("payment_date", ASCENDING)])

        db["webhook_unresolved"].create_index([("received_at", ASCENDING)])
        db["webhook_log"].create_index([("received_at", ASCENDING)])
    except Exception:
        pass


ensure_indexes()


def mirror_doc(collection: str, doc_id: str, payload: Dict[str, Any]) -> None:
    doc = dict(payload or {})
    doc["_id"] = doc_id
    doc["received_at"] = now_iso()
    db[collection].update_one({"_id": doc_id}, {"$set": doc}, upsert=True)


def extract_event_uid(info: Dict[str, Any]) -> str:
    for k in ("uid", "id", "event_id", "signup_id", "upload_id", "payment_id", "invoice_id", "charge_id"):
        v = str((info or {}).get(k) or "").strip()
        if v:
            return v
    return ""


def raw_row_id(kind: str, source: str) -> str:
    return f"{kind}|{source}|{now_iso()}|{uuid.uuid4().hex}"


def write_raw_event(kind: str, source: str, info: Dict[str, Any], resolved_email: str = "", resolved_username: str = "", extra: Optional[Dict[str, Any]] = None) -> str:
    collection_map = {
        "signup": "signups_raw_webhook",
        "upload": "uploads_raw_webhook",
        "payment": "payments_raw_webhook",
    }
    collection = collection_map[kind]

    username = str(info.get("username") or resolved_username or "").strip()
    email = normalize_email(info.get("email") or resolved_email)
    event_uid = extract_event_uid(info)
    raw_id = raw_row_id(kind, source)

    doc = dict(info or {})
    doc.update({
        "_id": raw_id,
        "raw_id": raw_id,
        "event_uid": event_uid or "",
        "type": kind,
        "source": source,
        "username": username,
        "username_normalized": normalize_username(username),
        "email": email,
        "email_normalized": email,
        "received_at": now_iso(),
        "processing_status": "RECEIVED",
        "processing_error": "",
    })
    if extra:
        doc.update(extra)

    db[collection].insert_one(doc)
    return raw_id


def update_raw_event_status(kind: str, raw_id: str, ok: bool, error: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
    collection_map = {
        "signup": "signups_raw_webhook",
        "upload": "uploads_raw_webhook",
        "payment": "payments_raw_webhook",
    }
    collection = collection_map[kind]

    payload = {
        "processing_status": "PROCESSED" if ok else "FAILED",
        "processing_error": str(error or ""),
        "processed_at": now_iso(),
    }
    if extra:
        payload.update(extra)

    db[collection].update_one({"_id": raw_id}, {"$set": payload})


def unresolved(kind: str, source: str, info: Dict[str, Any], reason: str) -> Dict[str, Any]:
    doc = {
        "kind": kind,
        "source": source,
        "reason": reason,
        "info": dict(info or {}),
        "username": normalize_username((info or {}).get("username")),
        "email": normalize_email((info or {}).get("email")),
        "received_at": now_iso(),
    }
    db["webhook_unresolved"].insert_one(doc)
    return {"ok": False, "kind": kind, "error": reason, "info": dict(info or {})}


def upsert_username_registry(source: str, email: str, username: str, signup_date: str, lead_source: Any = None) -> None:
    username_normalized = normalize_username(username)
    email_normalized = normalize_email(email)
    db["username_registry"].update_one(
        {"username_normalized": username_normalized},
        {
            "$set": {
                "username": username,
                "username_normalized": username_normalized,
                "email": email_normalized,
                "email_normalized": email_normalized,
                "lead_source": lead_source,
                "signup_date": signup_date,
                "source": source,
                "updated_at": now_iso(),
            }
        },
        upsert=True,
    )


def find_signup_by_username(username_normalized: str) -> Optional[Dict[str, Any]]:
    if not username_normalized:
        return None
    return db["signups"].find_one({"username_normalized": username_normalized})


def signup_lookup(username: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    uname = normalize_username(username)
    if not uname:
        return None, "username missing"

    reg = db["username_registry"].find_one({"username_normalized": uname})
    if reg:
        email = normalize_email(reg.get("email") or reg.get("email_normalized"))
        if email:
            return {
                "email": email,
                "email_normalized": email,
                "username": reg.get("username") or uname,
                "username_normalized": uname,
                "signup_date": str(reg.get("signup_date") or "")[:10],
                "lead_source": reg.get("lead_source"),
            }, None

    signup = find_signup_by_username(uname)
    if signup:
        email = normalize_email(signup.get("email") or signup.get("email_normalized"))
        if email:
            return signup, None

    return None, f"username not mapped to a signup yet: {uname}"


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
            "duplicate_month": False,
        }

    if current_month in paid_months:
        return {
            "customer_type": history.get("customer_type") or "RECURRING_CUSTOMER",
            "lifecycle_label": history.get("lifecycle_label") or "RECURRING_CUSTOMER",
            "paid_months": paid_months,
            "paid_months_count": int(history.get("paid_months_count") or len(paid_months)),
            "consecutive_paid_months": int(history.get("consecutive_paid_months") or consecutive_before or 1),
            "first_ever_payment_date": str(history.get("first_ever_payment_date") or payment_date)[:10],
            "reactivated": bool(history.get("reactivated", False)),
            "duplicate_month": True,
        }

    new_paid_months = sorted(set(paid_months + [current_month]))
    paid_months_count = len(new_paid_months)

    if prev_latest_month and current_month == add_month(prev_latest_month):
        return {
            "customer_type": "RECURRING_CUSTOMER",
            "lifecycle_label": f"RECURRING_CUSTOMER_{paid_months_count}_MONTHS",
            "paid_months": new_paid_months,
            "paid_months_count": paid_months_count,
            "consecutive_paid_months": (consecutive_before or 1) + 1,
            "first_ever_payment_date": str(history.get("first_ever_payment_date") or payment_date)[:10],
            "reactivated": False,
            "duplicate_month": False,
        }

    return {
        "customer_type": "CHURNED_CUSTOMER_RETURNED",
        "lifecycle_label": f"CHURNED_CUSTOMER_RETURNED_{paid_months_count}_MONTHS_TOTAL",
        "paid_months": new_paid_months,
        "paid_months_count": paid_months_count,
        "consecutive_paid_months": 1,
        "first_ever_payment_date": str(history.get("first_ever_payment_date") or payment_date)[:10],
        "reactivated": True,
        "duplicate_month": False,
    }


def upsert_signup(source: str, info: Dict[str, Any]) -> Dict[str, Any]:
    email = normalize_email(info.get("email"))
    username = str(info.get("username") or "").strip()
    username_normalized = normalize_username(username)
    signup_date = pick_day(info.get("signup_date"), info.get("created_at"), info.get("date"))

    if not email:
        return unresolved("signup", source, info, "signup missing email")
    if not username_normalized:
        return unresolved("signup", source, info, "signup missing username")

    existing = db["signups"].find_one({
        "$or": [
            {"email_normalized": email},
            {"username_normalized": username_normalized},
        ]
    })
    selector = {"_id": existing["_id"]} if existing else {"username_normalized": username_normalized}

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

    upsert_username_registry(
        source=source,
        email=email,
        username=username,
        signup_date=signup_date,
        lead_source=info.get("lead_source"),
    )

    mirror_doc(
        "signups_webhook",
        username_normalized,
        {
            "source": source,
            "type": "signup",
            "username": username,
            "username_normalized": username_normalized,
            "email": email,
            "email_normalized": email,
            "lead_source": info.get("lead_source"),
            "signup_date": signup_date,
        },
    )

    return {"ok": True, "email": email, "username": username_normalized}


def upsert_upload(source: str, info: Dict[str, Any]) -> Dict[str, Any]:
    username = str(info.get("username") or "").strip()
    username_normalized = normalize_username(username)
    upload_date = pick_day(info.get("upload_date"), info.get("created_at"), info.get("date"))
    app_name = str(info.get("app_name") or info.get("appname") or "").strip()

    if not username_normalized:
        return unresolved("upload", source, info, "upload missing username")
    if not app_name:
        return unresolved("upload", source, info, "upload missing appname")

    signup, err = signup_lookup(username_normalized)
    if err:
        return unresolved("upload", source, info, err)

    email = normalize_email(signup.get("email") or signup.get("email_normalized"))
    existing = db["uploads"].find_one({
        "$or": [
            {"username_normalized": username_normalized},
            {"email_normalized": email},
        ]
    })

    final_upload_date = upload_date
    final_app_name = app_name
    if existing:
        existing_date = str(existing.get("upload_date") or "")[:10]
        existing_app = str(existing.get("app_name") or existing.get("appname") or "").strip()
        if existing_date and existing_date <= upload_date:
            final_upload_date = existing_date
            if existing_app:
                final_app_name = existing_app

    doc = dict(info)
    doc.update({
        "event_type": "upload",
        "username": username,
        "username_normalized": username_normalized,
        "email": email,
        "email_normalized": email,
        "signup_date": str(signup.get("signup_date") or "")[:10],
        "upload_date": final_upload_date,
        "app_name": final_app_name,
        "source": source,
        "final_status": "ACCEPTED",
        "_updated_at": now_iso(),
    })

    selector = {"_id": existing["_id"]} if existing else {"username_normalized": username_normalized}
    db["uploads"].update_one(selector, {"$set": doc}, upsert=True)

    mirror_doc(
        "uploads_webhook",
        username_normalized,
        {
            "type": "upload",
            "username": username,
            "username_normalized": username_normalized,
            "email": email,
            "email_normalized": email,
            "appname": app_name,
            "upload_date": upload_date,
            "received_at": now_iso(),
        },
    )

    return {
        "ok": True,
        "email": email,
        "username": username_normalized,
        "app_name": final_app_name,
        "duplicate": bool(existing),
    }


def upsert_payment(source: str, info: Dict[str, Any]) -> Dict[str, Any]:
    username = str(info.get("username") or "").strip()
    username_normalized = normalize_username(username)
    amount = parse_amount(info.get("amount"))
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
    if amount is None:
        return unresolved("payment", source, info, "payment missing/invalid amount")
    if not subscription:
        return unresolved("payment", source, info, "payment missing subscription")

    signup, err = signup_lookup(username_normalized)
    if err:
        return unresolved("payment", source, info, err)

    email = normalize_email(signup.get("email") or signup.get("email_normalized"))
    history = db["payment_history"].find_one({"email_normalized": email}) or {}
    classification = classify_payment(history, payment_date)

    existing = db["payments"].find_one({
        "$or": [
            {"username_normalized": username_normalized},
            {"email_normalized": email},
        ]
    })

    doc = dict(info)
    doc.update({
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

    selector = {"_id": existing["_id"]} if existing else {"username_normalized": username_normalized}
    db["payments"].update_one(selector, {"$set": doc}, upsert=True)

    prev_count = int(history.get("payment_count") or 0)
    prev_revenue = float(history.get("lifetime_revenue_usd") or 0.0)

    if classification["duplicate_month"]:
        payment_count = prev_count
        lifetime_revenue = prev_revenue
    else:
        payment_count = prev_count + 1
        lifetime_revenue = round(prev_revenue + amount, 2)

    history_doc = {
        "email": email,
        "email_normalized": email,
        "username": username,
        "username_normalized": username_normalized,
        "lead_source": signup.get("lead_source"),
        "first_signup_date": str(signup.get("signup_date") or "")[:10],
        "first_ever_payment_date": classification["first_ever_payment_date"],
        "latest_payment_date": payment_date,
        "payment_count": payment_count,
        "paid_months": classification["paid_months"],
        "paid_months_count": classification["paid_months_count"],
        "consecutive_paid_months": classification["consecutive_paid_months"],
        "customer_type": classification["customer_type"],
        "lifecycle_label": classification["lifecycle_label"],
        "reactivated": classification["reactivated"],
        "last_subscription": subscription,
        "last_amount_usd": amount,
        "lifetime_revenue_usd": lifetime_revenue,
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

    mirror_doc(
        "payments_webhook",
        username_normalized,
        {
            "type": "payment",
            "username": username,
            "username_normalized": username_normalized,
            "email": email,
            "email_normalized": email,
            "amount": amount,
            "subscription": subscription,
            "payment_date": payment_date,
            "currency": "USD",
            "customer_type": classification["customer_type"],
            "lifecycle_label": classification["lifecycle_label"],
            "received_at": now_iso(),
        },
    )

    warning = None
    if not any(info.get(k) for k in ("payment_date", "first_payment_date", "paid_at", "created_at", "date")):
        warning = f"payment_date missing in payload; defaulted to {payment_date}"

    return {
        "ok": True,
        "email": email,
        "username": username_normalized,
        "customer_type": classification["customer_type"],
        "lifecycle_label": classification["lifecycle_label"],
        "amount": amount,
        "warning": warning,
        "duplicate": bool(existing or classification["duplicate_month"]),
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
                    "upload_date": local_now().date().isoformat()
                }
            },
            {
                "type": "payment",
                "info": {
                    "username": "demouser",
                    "amount": 70,
                    "subscription": "Pre Paid Minute"
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
        raw_id = None

        try:
            if kind == "signup":
                raw_id = write_raw_event(
                    "signup",
                    source,
                    info,
                    resolved_email=normalize_email(info.get("email")),
                    resolved_username=str(info.get("username") or "").strip(),
                    extra={"signup_date": pick_day(info.get("signup_date"), info.get("created_at"), info.get("date"))},
                )
            elif kind == "upload":
                raw_id = write_raw_event(
                    "upload",
                    source,
                    info,
                    resolved_username=str(info.get("username") or "").strip(),
                    extra={
                        "appname": str(info.get("app_name") or info.get("appname") or "").strip(),
                        "upload_date": pick_day(info.get("upload_date"), info.get("created_at"), info.get("date")),
                    },
                )
            elif kind == "payment":
                raw_id = write_raw_event(
                    "payment",
                    source,
                    info,
                    resolved_username=str(info.get("username") or "").strip(),
                    extra={
                        "amount": info.get("amount"),
                        "subscription": str(info.get("subscription") or info.get("plan") or info.get("product") or "").strip(),
                        "payment_date": pick_day(
                            info.get("payment_date"),
                            info.get("first_payment_date"),
                            info.get("paid_at"),
                            info.get("created_at"),
                            info.get("date"),
                        ),
                    },
                )

            if kind == "signup":
                res = upsert_signup(source, info)
                if res.get("ok"):
                    processed["signups"] += 1
                    results["signups"].append(res)
                    if raw_id:
                        update_raw_event_status("signup", raw_id, True, extra={"processed_kind": "signup"})
                else:
                    results["errors"].append(res)
                    if raw_id:
                        update_raw_event_status("signup", raw_id, False, res.get("error", ""), extra={"processed_kind": "signup"})

            elif kind == "upload":
                res = upsert_upload(source, info)
                if res.get("ok"):
                    processed["uploads"] += 1
                    results["uploads"].append(res)
                    if raw_id:
                        update_raw_event_status("upload", raw_id, True, extra={"processed_kind": "upload"})
                else:
                    results["errors"].append(res)
                    if raw_id:
                        update_raw_event_status("upload", raw_id, False, res.get("error", ""), extra={"processed_kind": "upload"})

            elif kind == "payment":
                res = upsert_payment(source, info)
                if res.get("ok"):
                    processed["payments"] += 1
                    results["payments"].append(res)
                    if raw_id:
                        update_raw_event_status("payment", raw_id, True, extra={"processed_kind": "payment"})
                else:
                    results["errors"].append(res)
                    if raw_id:
                        update_raw_event_status("payment", raw_id, False, res.get("error", ""), extra={"processed_kind": "payment"})

            else:
                err = {
                    "ok": False,
                    "kind": kind,
                    "error": f"unknown type: {kind}",
                    "info": info,
                }
                results["errors"].append(err)

        except Exception as e:
            err = {
                "ok": False,
                "kind": kind,
                "error": f"internal_processing_error: {e}",
                "info": info,
            }
            results["errors"].append(err)
            if raw_id and kind in ("signup", "upload", "payment"):
                try:
                    update_raw_event_status(kind, raw_id, False, err["error"])
                except Exception:
                    pass

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
        send_success_alert(source, processed, results, received_at)

    if results["errors"]:
        send_error_alert(source, results["errors"], received_at)

    return {
        "success": len(results["errors"]) == 0,
        "processed": processed,
        "errors_count": len(results["errors"]),
        "results": results,
        "received_at": received_at,
    }
