from __future__ import annotations

from datetime import datetime, date
from pathlib import Path
from typing import Optional, Any
import json
import os
import re

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from mongo_client import get_db, get_mongo_status

try:
    from bson import ObjectId
except Exception:
    ObjectId = None

app = FastAPI(title="Eagle3D MongoDB Sync API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

KEY_FILE = Path(".api_keys.json")
NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
DEFAULT_KEYS = ["email_normalized", "email", "date", "snapshot_date", "post_urn", "id"]


def now() -> str:
    return datetime.utcnow().isoformat()


def safe(obj: Any):
    if ObjectId is not None and isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): safe(v) for k, v in obj.items() if k != "_id"}
    if isinstance(obj, list):
        return [safe(x) for x in obj]
    if isinstance(obj, tuple):
        return [safe(x) for x in obj]
    try:
        import math
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return 0
    except Exception:
        pass
    return obj


def safe_int(v, default=0):
    try:
        if v is None:
            return default
        if isinstance(v, str):
            v = v.replace(",", "").replace("$", "").strip()
            if not v:
                return default
        return int(float(v))
    except Exception:
        return default


def load_keys():
    keys = []

    for v in [os.environ.get("INGEST_API_KEY", ""), os.environ.get("INGEST_API_KEYS", "")]:
        keys += [x.strip() for x in v.split(",") if x.strip()]

    try:
        if KEY_FILE.exists():
            data = json.loads(KEY_FILE.read_text())
            keys += [str(x).strip() for x in data.get("api_keys", []) if str(x).strip()]
    except Exception:
        pass

    return set(keys)


def auth(x_api_key: Optional[str], authorization: Optional[str]):
    key = (x_api_key or "").strip()

    if not key and authorization:
        a = authorization.strip()
        key = a.split(" ", 1)[1].strip() if a.lower().startswith("bearer ") else a

    allowed = load_keys()

    if not allowed:
        raise HTTPException(503, "No API key configured")

    if key not in allowed:
        raise HTTPException(401, "Invalid or missing API key")


def raw_db():
    dbo = get_db()
    db = dbo.raw() if hasattr(dbo, "raw") else dbo

    if db is None:
        raise HTTPException(503, "MongoDB not connected")

    return db


def collection_name(name: str):
    name = str(name or "").strip()

    if not NAME_RE.match(name):
        raise HTTPException(400, "Invalid collection name")

    return name


def records(payload):
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        payload = payload["records"]
    elif isinstance(payload, dict):
        payload = [payload]

    if not isinstance(payload, list):
        raise HTTPException(400, "Body must be object, list, or {records:[...]}")

    out = []
    for i, r in enumerate(payload):
        if not isinstance(r, dict):
            raise HTTPException(400, f"Record {i} is not object")
        out.append(dict(r))

    return out


def conflict_list(v):
    if not v:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in str(v).split(",") if x.strip()]


def conflict_filter(doc, fields):
    res = {}

    for k in (fields or DEFAULT_KEYS):
        if k in doc and doc[k] not in ("", None):
            res[k] = doc[k]

    return res


def count(db, col):
    try:
        return db[col].count_documents({})
    except Exception:
        return 0


def audit(collection, mode, count_value, ok, request, error=""):
    try:
        db = raw_db()
        db["api_ingest_log"].insert_one({
            "timestamp": now(),
            "collection": collection,
            "mode": mode,
            "count": count_value,
            "success": ok,
            "error": error,
            "client": request.client.host if request.client else "unknown",
            "ua": request.headers.get("user-agent", ""),
        })
    except Exception:
        pass


@app.get("/")
def root():
    return {
        "service": "Eagle3D MongoDB Sync API",
        "status": "ok",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    status = get_mongo_status()
    return {"ok": bool(status.get("connected")), "mongo": safe(status)}


@app.get("/api/v1/collections")
def collections(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_api_key, authorization)
    db = raw_db()

    return {
        "success": True,
        "collections": [
            {"collection": n, "count": count(db, n)}
            for n in sorted(db.list_collection_names())
        ],
    }


@app.post("/api/v1/sync/{collection}")
async def sync(collection: str, request: Request, x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_api_key, authorization)

    db = raw_db()
    collection = collection_name(collection)
    body = await request.json()

    mode = str(body.get("mode", "upsert") if isinstance(body, dict) else "upsert").lower()
    cfields = conflict_list(body.get("conflict_fields") if isinstance(body, dict) else None)
    recs = records(body)

    col = db[collection]
    ts = now()

    inserted = matched = upserted = deleted = 0

    try:
        if mode == "replace":
            deleted = col.delete_many({}).deleted_count
            docs = [{**r, "_api_ingested_at": ts, "_api_ingest_mode": mode} for r in recs]
            if docs:
                col.insert_many(docs, ordered=False)
                inserted = len(docs)

        elif mode == "insert":
            docs = [{**r, "_api_ingested_at": ts, "_api_ingest_mode": mode} for r in recs]
            if docs:
                col.insert_many(docs, ordered=False)
                inserted = len(docs)

        elif mode == "upsert":
            for r in recs:
                d = {**r, "_api_ingested_at": ts, "_api_ingest_mode": mode}
                f = conflict_filter(d, cfields)

                if f:
                    rr = col.update_one(f, {"$set": d}, upsert=True)
                    matched += rr.matched_count
                    upserted += 1 if rr.upserted_id else 0
                else:
                    col.insert_one(d)
                    inserted += 1

        else:
            raise HTTPException(400, "mode must be insert, replace, or upsert")

        audit(collection, mode, len(recs), True, request)

        return {
            "success": True,
            "collection": collection,
            "mode": mode,
            "received": len(recs),
            "inserted": inserted,
            "matched": matched,
            "upserted": upserted,
            "deleted_before_replace": deleted,
        }

    except HTTPException:
        raise
    except Exception as e:
        audit(collection, mode, len(recs), False, request, str(e))
        raise HTTPException(500, str(e))


@app.post("/api/v1/dump/{collection}")
async def dump_alias(collection: str, request: Request, x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    return await sync(collection, request, x_api_key, authorization)


@app.get("/api/v1/dashboard/summary")
def dashboard_summary(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_api_key, authorization)

    try:
        import executive_dashboard
        data = {}

        for period in ["this_month", "last_month", "this_year", "last_year", "all_time"]:
            m = executive_dashboard.get_core_metrics(period)

            data[period] = {
                "period": period,
                "period_start": m.get("period_start"),
                "period_end": m.get("period_end"),
                "signups": m.get("signups", 0),
                "uploads": m.get("uploads", 0),
                "paid": m.get("paid", 0),
                "revenue": m.get("revenue", 0),
                "signup_pct": m.get("signup_pct", 0),
                "upload_pct": m.get("upload_pct", 0),
                "paid_pct": m.get("paid_pct", 0),
                "revenue_pct": m.get("revenue_pct", 0),
                "linkedin_posts": m.get("content_volume", {}).get("linkedin", {}).get("total_posts", 0),
                "youtube_videos": m.get("content_volume", {}).get("youtube", {}).get("total_videos", 0),
                "linkedin_followers": m.get("channel_growth", {}).get("linkedin_followers", {}).get("current", 0),
                "total_revenue": m.get("total_revenue", 0),
                "total_paid": m.get("total_paid", 0),
                "avg_subscription": m.get("avg_subscription", 0),
            }

        return safe({"success": True, "source": "mongodb", "data": data})

    except Exception as e:
        return {"success": False, "error": str(e), "data": {}}


@app.get("/api/v1/youtube/overview")
def youtube_overview(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_api_key, authorization)
    db = raw_db()

    channel = db["youtube_channel"].find_one({}, {"_id": 0}) or {}
    videos = list(db["youtube_videos"].find({}, {"_id": 0}))

    videos_sorted = sorted(
        videos,
        key=lambda x: safe_int(x.get("views") or x.get("view_count") or 0),
        reverse=True,
    )

    return safe({
        "success": True,
        "channel": channel,
        "video_count": len(videos),
        "top_videos": videos_sorted[:50],
    })


@app.get("/api/v1/linkedin/overview")
def linkedin_overview(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_api_key, authorization)
    db = raw_db()

    posts = list(db["linkedin_posts"].find({}, {"_id": 0}))
    followers = list(db["linkedin_followers_daily"].find({}, {"_id": 0}))

    posts_sorted = sorted(
        posts,
        key=lambda x: safe_int(x.get("impressions") or 0),
        reverse=True,
    )

    return safe({
        "success": True,
        "post_count": len(posts),
        "followers_points": len(followers),
        "latest_followers": followers[-1] if followers else {},
        "top_posts": posts_sorted[:50],
    })


@app.get("/api/v1/customer-success/overview")
def customer_success_overview(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_api_key, authorization)
    db = raw_db()

    return {
        "success": True,
        "customer_success_master": count(db, "customer_success_master"),
        "customer_success_enriched": count(db, "customer_success_enriched"),
    }


@app.get("/api/v1/cross-platform/overview")
def cross_platform_overview(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_api_key, authorization)
    db = raw_db()

    try:
        import executive_dashboard
        kpi = executive_dashboard.get_core_metrics("this_year")
    except Exception:
        kpi = {}

    return safe({
        "success": True,
        "source": "mongodb",
        "timeline_days": count(db, "daily_kpis"),
        "kpi": kpi,
        "platforms": {
            "youtube_videos": count(db, "youtube_videos"),
            "linkedin_posts": count(db, "linkedin_posts"),
            "customer_records": count(db, "customer_success_master"),
        },
        "sections": ["Unified Timeline", "Correlations", "Attribution", "Funnel", "Growth", "Insights"],
    })


@app.get("/api/v1/ga4/overview")
def ga4_overview(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_api_key, authorization)

    try:
        import ga4_connector
        status = ga4_connector.get_status() if hasattr(ga4_connector, "get_status") else {"configured": True}
    except Exception as e:
        status = {"configured": False, "error": str(e)}

    return safe({
        "success": True,
        "source": "ga4",
        "status": status,
        "sections": ["Traffic Overview", "Pages", "Events", "Countries", "Devices", "Channels", "Strategic QA"],
    })


@app.get("/api/v1/ai/overview")
def ai_overview(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_api_key, authorization)

    return {
        "success": True,
        "modules": [
            "Ask AI",
            "AI KPI",
            "AI YouTube",
            "AI LinkedIn",
            "AI GA4",
            "AI Customer Success",
            "Predictions",
            "AI Tools",
        ],
    }


@app.get("/api/v1/custom-modules")
def custom_modules_api(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_api_key, authorization)
    db = raw_db()

    modules = []
    if "custom_modules" in db.list_collection_names():
        modules = list(db["custom_modules"].find({"is_active": True}, {"_id": 0}))

    return safe({"success": True, "modules": modules})


@app.get("/api/v1/settings/overview")
def settings_overview(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_api_key, authorization)
    db = raw_db()
    names = db.list_collection_names()

    return {
        "success": True,
        "access_users": count(db, "access_control"),
        "access_logs": count(db, "access_log"),
        "api_ingest_logs": count(db, "api_ingest_log") if "api_ingest_log" in names else 0,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))


@app.get("/api/v1/features")
def features_overview(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_api_key, authorization)
    from feature_registry import get_feature_registry

    registry = get_feature_registry()

    # Current migration status.
    live = {
        "KPI": ["Dashboard", "Data Quality", "Daily Counts", "Monthly Counts"],
        "Google Analytics": ["Overview"],
        "YouTube": ["Channel Overview", "All Videos", "OAuth Status"],
        "LinkedIn": ["Command Center", "Posts", "Followers"],
        "Customer Success": ["Master Customers", "Enriched Customers"],
        "Cross-Platform": ["Unified Timeline", "Platform Health"],
        "AI & Insights": [],
        "Custom Modules": ["Create Module", "Upload CSV/XLSX", "Auto Insights", "Auto Charts", "Data Browser", "Download CSV"],
        "Settings": ["User Access", "API Keys", "System Health"],
        "Reports": ["KPI Report"],
    }

    needs_oauth = {
        "YouTube": ["Analytics", "Audience", "Revenue", "Traffic"],
        "Google Analytics": ["Traffic Sources", "Pages", "Events", "Countries", "Devices", "Channels"],
        "LinkedIn": ["Visitors", "Competitors", "Search Appearances"],
    }

    result = {}

    for module, data in registry.items():
        features = []
        for name in data["features"]:
            status = "not_migrated"
            if name in live.get(module, []):
                status = "live"
            if name in needs_oauth.get(module, []):
                status = "needs_oauth"
            features.append({
                "name": name,
                "status": status,
            })

        result[module] = {
            "icon": data["icon"],
            "features": features,
        }

    return {
        "success": True,
        "modules": result,
    }


@app.get("/api/v1/data/{collection}")
def data_collection(
    collection: str,
    limit: int = 500,
    skip: int = 0,
    q: str = "",
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    auth(x_api_key, authorization)
    db = raw_db()
    collection = collection_name(collection)

    query = {}

    # Simple search across common text fields
    if q:
        query = {
            "$or": [
                {"email": {"$regex": q, "$options": "i"}},
                {"email_normalized": {"$regex": q, "$options": "i"}},
                {"title": {"$regex": q, "$options": "i"}},
                {"name": {"$regex": q, "$options": "i"}},
                {"source": {"$regex": q, "$options": "i"}},
            ]
        }

    total = db[collection].count_documents(query)

    rows = list(
        db[collection]
        .find(query, {"_id": 0})
        .skip(max(0, skip))
        .limit(min(max(1, limit), 5000))
    )

    return safe({
        "success": True,
        "collection": collection,
        "total": total,
        "skip": skip,
        "limit": limit,
        "rows": rows,
    })
