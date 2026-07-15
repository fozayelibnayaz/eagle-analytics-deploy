from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime
from typing import Any, Dict, List

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import MongoClient

APP = FastAPI(title="Eagle Analytics Webhook API", version="1.0.0")

MONGO_URI = os.environ.get("MONGO_URI", "").strip()
MONGO_DB = os.environ.get("MONGO_DB", "eagle3d").strip()
WEBHOOK_API_KEY = os.environ.get("WEBHOOK_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

if not MONGO_URI:
    raise RuntimeError("MONGO_URI is required")

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
db = client[MONGO_DB]


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
    return str(v or "").strip().lower()


def require_key(x_api_key: str | None):
    if not WEBHOOK_API_KEY:
        raise HTTPException(status_code=500, detail="WEBHOOK_API_KEY not configured")
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    if x_api_key != WEBHOOK_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def upsert_signup(source: str, info: Dict[str, Any]) -> Dict[str, Any]:
    email = normalize_email(info.get("email"))
    if not email:
        return {"ok": False, "error": "signup missing email"}

    doc = dict(info)
    doc["email"] = email
    doc["email_normalized"] = email
    doc["source"] = source
    doc["final_status"] = "ACCEPTED"
    doc["_updated_at"] = now_iso()

    db["signups"].update_one(
        {"email_normalized": email},
        {"$set": doc},
        upsert=True,
    )
    return {"ok": True, "email": email, "id": info.get("id")}


def upsert_upload(source: str, info: Dict[str, Any]) -> Dict[str, Any]:
    email = normalize_email(info.get("email"))
    if not email:
        return {"ok": False, "error": "upload missing email"}

    doc = dict(info)
    doc["email"] = email
    doc["email_normalized"] = email
    doc["source"] = source
    doc["final_status"] = "ACCEPTED"
    doc["_updated_at"] = now_iso()

    db["uploads"].update_one(
        {"email_normalized": email},
        {"$set": doc},
        upsert=True,
    )
    return {"ok": True, "email": email, "id": info.get("id")}


def upsert_payment(source: str, info: Dict[str, Any]) -> Dict[str, Any]:
    email = normalize_email(info.get("email"))
    amount = float(info.get("amount", 0) or 0)

    if not email:
        return {"ok": False, "error": "payment missing email"}
    if amount <= 0:
        return {"ok": False, "error": "payment missing/invalid amount"}

    existing = db["payments"].count_documents({"email_normalized": email})
    customer_type = "NEW_CUSTOMER" if existing == 0 else "RECURRING"

    doc = dict(info)
    doc["email"] = email
    doc["email_normalized"] = email
    doc["source"] = source
    doc["final_status"] = "ACCEPTED"
    doc["customer_type"] = customer_type
    doc["total_spend"] = amount
    doc["_updated_at"] = now_iso()

    db["payments"].update_one(
        {"email_normalized": email},
        {"$set": doc},
        upsert=True,
    )

    return {"ok": True, "email": email, "id": info.get("id"), "customer_type": customer_type, "amount": amount}


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
        "source": "example-backend",
        "data": [
            {"type": "signup", "info": {"id": "sig-001", "email": "user@example.com", "signup_date": "2026-07-15", "lead_source": "google"}},
            {"type": "upload", "info": {"id": "up-001", "email": "user@example.com", "upload_date": "2026-07-15", "app_name": "DemoApp"}},
            {"type": "payment", "info": {"id": "pay-001", "email": "user@example.com", "first_payment_date": "2026-07-15", "amount": 29.0}},
        ],
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
