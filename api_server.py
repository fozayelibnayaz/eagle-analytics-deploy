"""
api_server.py — Eagle 3D Streaming Analytics Hub
=================================================
FastAPI server exposing all analytics data as REST endpoints.

For backend developer (Aninda Sadman) integration:
  - Base URL: http://localhost:8000  (or wherever deployed)
  - Auth: API key in X-API-Key header
  - All responses are JSON
  - Interactive docs: http://localhost:8000/docs

Run locally:
  python3 api_server.py

Or with uvicorn:
  uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from mongo_client import (
    find_all, find_one, count_docs, count_accepted, get_raw_db,
)


# ─── Config ──────────────────────────────────────────────────────
def _secret(name: str, default: str = "") -> str:
    # 1. env var
    val = os.environ.get(name, "").strip()
    if val:
        return val
    # 2. Streamlit secrets (works if running in Streamlit context)
    try:
        import streamlit as st
        v = str(st.secrets.get(name, "") or "").strip()
        if v:
            return v
    except Exception:
        pass
    # 3. Fallback: parse .streamlit/secrets.toml directly (for standalone servers)
    try:
        import re
        from pathlib import Path as _P
        content = _P(".streamlit/secrets.toml").read_text()
        m = re.search(rf'^{name}\s*=\s*"([^"]+)"', content, re.MULTILINE)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return default


# API key auth — Aninda sends this in X-API-Key header
API_KEY = _secret("API_KEY", "eagle3d-analytics-key-CHANGE-ME")

app = FastAPI(
    title="Eagle 3D Streaming Analytics API",
    description=("Read-only API exposing KPI, YouTube, LinkedIn, "
                  "Customer Success, GA4 & attribution data from MongoDB."),
    version="1.0.0",
)

# CORS — allow all origins for now (tighten before production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ─── Auth dependency ─────────────────────────────────────────────
def verify_api_key(x_api_key: Optional[str] = Header(None,
                                                       alias="X-API-Key")):
    if not x_api_key:
        raise HTTPException(status_code=401,
                            detail="Missing X-API-Key header")
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403,
                            detail="Invalid API key")
    return True


# ─── Helpers ─────────────────────────────────────────────────────
def _clean_docs(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove MongoDB internal fields + ensure JSON-serializable."""
    for r in rows:
        r.pop("_id", None)
        for k, v in list(r.items()):
            if isinstance(v, datetime):
                r[k] = v.isoformat()
    return rows


def _resolve_dates(start: Optional[str], end: Optional[str],
                    days_back: int = 30) -> tuple:
    if not end:
        end = date.today().isoformat()
    if not start:
        start = (date.today() - timedelta(days=days_back)).isoformat()
    return start, end


# ═════════════════════════════════════════════════════════════════
# ROOT + HEALTH
# ═════════════════════════════════════════════════════════════════
@app.get("/", tags=["System"])
def root():
    return {
        "app":         "Eagle 3D Streaming Analytics API",
        "version":     "1.0.0",
        "docs":        "/docs",
        "authenticated_endpoints": [
            "/api/kpis/summary",
            "/api/kpis/daily",
            "/api/signups",
            "/api/uploads",
            "/api/payments",
            "/api/attribution/signups",
            "/api/attribution/revenue",
            "/api/youtube/channel",
            "/api/youtube/videos",
            "/api/linkedin/latest",
            "/api/customer-success",
            "/api/pipeline/health",
        ],
    }


@app.get("/health", tags=["System"])
def health():
    """Check MongoDB + API status. No auth required."""
    from mongo_client import get_mongo_status
    s = get_mongo_status()
    return {
        "api":     "ok",
        "mongodb": s,
        "server_time": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════════
# KPI ENDPOINTS
# ═════════════════════════════════════════════════════════════════
@app.get("/api/kpis/summary", tags=["KPIs"],
          dependencies=[Depends(verify_api_key)])
def kpi_summary(
    start: Optional[str] = Query(None, description="YYYY-MM-DD (default: 30d ago)"),
    end:   Optional[str] = Query(None, description="YYYY-MM-DD (default: today)"),
):
    """Aggregate KPI counts for a date range (post-dedup + accepted only)."""
    start, end = _resolve_dates(start, end)

    signups  = count_accepted("signups",  "signup_date",        date_gte=start, date_lte=end)
    uploads  = count_accepted("uploads",  "upload_date",        date_gte=start, date_lte=end)
    payments = count_accepted("payments", "first_payment_date", date_gte=start, date_lte=end)

    # Revenue
    pay_docs = find_all("payments", {
        "final_status": "ACCEPTED",
        "first_payment_date": {"$gte": start, "$lte": end},
    }, projection={"total_spend": 1, "customer_type": 1})
    total_revenue    = sum(float(p.get("total_spend", 0) or 0) for p in pay_docs)
    new_cust_revenue = sum(float(p.get("total_spend", 0) or 0)
                            for p in pay_docs
                            if p.get("customer_type") == "NEW_CUSTOMER")
    new_paying = sum(1 for p in pay_docs
                      if p.get("customer_type") == "NEW_CUSTOMER")

    return {
        "period":                {"start": start, "end": end,
                                   "days": (date.fromisoformat(end) - date.fromisoformat(start)).days + 1},
        "signups":               signups,
        "uploads":               uploads,
        "paying_customers":      payments,
        "new_paying_customers":  new_paying,
        "revenue":               {
            "total":         round(total_revenue, 2),
            "new_customer":  round(new_cust_revenue, 2),
            "recurring":     round(total_revenue - new_cust_revenue, 2),
        },
        "conversion_rates":      {
            "signup_to_upload_pct": round(uploads / signups * 100, 2) if signups else 0,
            "upload_to_paid_pct":   round(payments / uploads * 100, 2) if uploads else 0,
            "signup_to_paid_pct":   round(payments / signups * 100, 2) if signups else 0,
        },
    }


@app.get("/api/kpis/daily", tags=["KPIs"],
          dependencies=[Depends(verify_api_key)])
def kpi_daily(
    start: Optional[str] = None,
    end:   Optional[str] = None,
):
    """Per-day KPI counts for a range."""
    start, end = _resolve_dates(start, end, days_back=90)
    rows = find_all("daily_kpis",
                     filters={"date": {"$gte": start, "$lte": end}},
                     sort=[("date", 1)])
    return {"period": {"start": start, "end": end},
             "rows":   _clean_docs(rows),
             "count":  len(rows)}


# ═════════════════════════════════════════════════════════════════
# RAW DATA (signups / uploads / payments)
# ═════════════════════════════════════════════════════════════════
@app.get("/api/signups", tags=["Raw Data"],
          dependencies=[Depends(verify_api_key)])
def get_signups(
    status: Optional[str] = Query(None, description="ACCEPTED / REJECTED / PENDING"),
    start:  Optional[str] = None,
    end:    Optional[str] = None,
    limit:  int = Query(500, le=5000),
):
    filters = {}
    if status:
        filters["final_status"] = status.upper()
    if start or end:
        rng = {}
        if start: rng["$gte"] = start
        if end:   rng["$lte"] = end
        filters["signup_date"] = rng

    rows = find_all("signups", filters=filters, limit=limit,
                     sort=[("signup_date", -1)])
    return {"count": len(rows), "rows": _clean_docs(rows)}


@app.get("/api/uploads", tags=["Raw Data"],
          dependencies=[Depends(verify_api_key)])
def get_uploads(
    status: Optional[str] = None,
    start:  Optional[str] = None,
    end:    Optional[str] = None,
    limit:  int = Query(500, le=5000),
):
    filters = {}
    if status:
        filters["final_status"] = status.upper()
    if start or end:
        rng = {}
        if start: rng["$gte"] = start
        if end:   rng["$lte"] = end
        filters["upload_date"] = rng

    rows = find_all("uploads", filters=filters, limit=limit,
                     sort=[("upload_date", -1)])
    return {"count": len(rows), "rows": _clean_docs(rows)}


@app.get("/api/payments", tags=["Raw Data"],
          dependencies=[Depends(verify_api_key)])
def get_payments(
    status:        Optional[str] = None,
    customer_type: Optional[str] = Query(None, description="NEW_CUSTOMER / RECURRING"),
    start:         Optional[str] = None,
    end:           Optional[str] = None,
    limit:         int = Query(500, le=5000),
):
    filters = {}
    if status:
        filters["final_status"] = status.upper()
    if customer_type:
        filters["customer_type"] = customer_type.upper()
    if start or end:
        rng = {}
        if start: rng["$gte"] = start
        if end:   rng["$lte"] = end
        filters["first_payment_date"] = rng

    rows = find_all("payments", filters=filters, limit=limit,
                     sort=[("first_payment_date", -1)])
    return {"count": len(rows), "rows": _clean_docs(rows)}


# ═════════════════════════════════════════════════════════════════
# ATTRIBUTION
# ═════════════════════════════════════════════════════════════════
@app.get("/api/attribution/signups", tags=["Attribution"],
          dependencies=[Depends(verify_api_key)])
def attribution_signups(start: Optional[str] = None,
                         end:   Optional[str] = None):
    """Signup counts by normalized traffic source."""
    start, end = _resolve_dates(start, end)
    from attribution_tracker import signups_by_source
    return {"period": {"start": start, "end": end},
             "by_source": signups_by_source(start, end)}


@app.get("/api/attribution/uploads", tags=["Attribution"],
          dependencies=[Depends(verify_api_key)])
def attribution_uploads(start: Optional[str] = None,
                         end:   Optional[str] = None):
    start, end = _resolve_dates(start, end)
    from attribution_tracker import uploads_by_source
    return {"period": {"start": start, "end": end},
             "by_source": uploads_by_source(start, end)}


@app.get("/api/attribution/paying", tags=["Attribution"],
          dependencies=[Depends(verify_api_key)])
def attribution_paying(start: Optional[str] = None,
                        end:   Optional[str] = None,
                        new_only: bool = True):
    start, end = _resolve_dates(start, end)
    from attribution_tracker import payments_by_source
    return {"period": {"start": start, "end": end},
             "new_customers_only": new_only,
             "by_source": payments_by_source(start, end, new_only)}


@app.get("/api/attribution/revenue", tags=["Attribution"],
          dependencies=[Depends(verify_api_key)])
def attribution_revenue(start: Optional[str] = None,
                         end:   Optional[str] = None,
                         new_only: bool = False):
    start, end = _resolve_dates(start, end)
    from attribution_tracker import revenue_by_source
    return {"period": {"start": start, "end": end},
             "new_customers_only": new_only,
             "by_source": revenue_by_source(start, end, new_only)}


@app.get("/api/attribution/full-report", tags=["Attribution"],
          dependencies=[Depends(verify_api_key)])
def attribution_full(days: int = Query(7, ge=1, le=365)):
    """Complete attribution snapshot: signups/uploads/paying/revenue by source."""
    from attribution_tracker import daily_attribution_report
    return daily_attribution_report(days)


# ═════════════════════════════════════════════════════════════════
# YOUTUBE
# ═════════════════════════════════════════════════════════════════
@app.get("/api/youtube/channel", tags=["YouTube"],
          dependencies=[Depends(verify_api_key)])
def youtube_channel():
    ch = find_one("youtube_channel", {})
    return _clean_docs([ch])[0] if ch else {"error": "no data"}


@app.get("/api/youtube/videos", tags=["YouTube"],
          dependencies=[Depends(verify_api_key)])
def youtube_videos(
    limit:  int = Query(100, le=1000),
    sort_by: str = Query("views", description="views/likes/comments/published_at"),
):
    valid = ["views", "likes", "comments", "published_at"]
    if sort_by not in valid:
        sort_by = "views"
    rows = find_all("youtube_videos", sort=[(sort_by, -1)], limit=limit)
    return {"count": len(rows), "rows": _clean_docs(rows)}


@app.get("/api/youtube/analytics", tags=["YouTube"],
          dependencies=[Depends(verify_api_key)])
def youtube_analytics(start: Optional[str] = None,
                       end:   Optional[str] = None):
    """Real per-day analytics via YouTube Analytics API (OAuth)."""
    start, end = _resolve_dates(start, end)
    try:
        from youtube_analytics import get_daily_views, get_revenue
        return {
            "period":       {"start": start, "end": end},
            "daily_views":  get_daily_views(start, end),
            "revenue":      get_revenue(start, end),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═════════════════════════════════════════════════════════════════
# LINKEDIN
# ═════════════════════════════════════════════════════════════════
@app.get("/api/linkedin/latest", tags=["LinkedIn"],
          dependencies=[Depends(verify_api_key)])
def linkedin_latest():
    hl = find_all("linkedin_highlights_daily",
                   sort=[("snapshot_date", -1)], limit=1)
    return _clean_docs(hl)[0] if hl else {"error": "no data"}


@app.get("/api/linkedin/posts", tags=["LinkedIn"],
          dependencies=[Depends(verify_api_key)])
def linkedin_posts(limit: int = Query(50, le=200)):
    rows = find_all("linkedin_posts",
                     sort=[("impressions", -1)], limit=limit)
    return {"count": len(rows), "rows": _clean_docs(rows)}


@app.get("/api/linkedin/followers", tags=["LinkedIn"],
          dependencies=[Depends(verify_api_key)])
def linkedin_followers(limit: int = Query(90, le=365)):
    """Daily follower snapshots for trend analysis."""
    rows = find_all("linkedin_followers_daily",
                     sort=[("snapshot_date", -1)], limit=limit)
    return {"count": len(rows), "rows": _clean_docs(rows)}


# ═════════════════════════════════════════════════════════════════
# CUSTOMER SUCCESS
# ═════════════════════════════════════════════════════════════════
@app.get("/api/customer-success", tags=["Customer Success"],
          dependencies=[Depends(verify_api_key)])
def customer_success(
    view:  str = Query("enriched", description="'enriched' or 'master'"),
    limit: int = Query(500, le=5000),
):
    coll = "customer_success_enriched" if view == "enriched" else "customer_success_master"
    rows = find_all(coll, limit=limit)
    return {"count": len(rows), "view": view, "rows": _clean_docs(rows)}


# ═════════════════════════════════════════════════════════════════
# GA4 CACHE
# ═════════════════════════════════════════════════════════════════
@app.get("/api/ga4/cache", tags=["GA4"],
          dependencies=[Depends(verify_api_key)])
def ga4_cache():
    """Latest cached GA4 snapshot (total_sessions, top_sources, top_countries)."""
    from pathlib import Path
    import json
    c = Path("data_output/ga4_traffic_cache.json")
    if not c.exists():
        return {"error": "no cache"}
    return json.loads(c.read_text())


# ═════════════════════════════════════════════════════════════════
# PIPELINE HEALTH
# ═════════════════════════════════════════════════════════════════
@app.get("/api/pipeline/health", tags=["System"],
          dependencies=[Depends(verify_api_key)])
def pipeline_health():
    from pipeline_gap_scanner import scan_gaps
    return scan_gaps()


# ═════════════════════════════════════════════════════════════════
# GENERIC COLLECTION ACCESS (for advanced integrations)
# ═════════════════════════════════════════════════════════════════
@app.get("/api/collections", tags=["Advanced"],
          dependencies=[Depends(verify_api_key)])
def list_collections():
    """List all available MongoDB collections."""
    db = get_raw_db()
    if db is None:
        raise HTTPException(500, "MongoDB offline")
    colls = sorted(db.list_collection_names())
    return {"count": len(colls), "collections": colls}


@app.get("/api/collections/{name}", tags=["Advanced"],
          dependencies=[Depends(verify_api_key)])
def get_collection(
    name:  str,
    limit: int = Query(100, le=5000),
    skip:  int = Query(0, ge=0),
):
    """Read from any collection (paginated). Use with caution."""
    db = get_raw_db()
    if db is None:
        raise HTTPException(500, "MongoDB offline")
    if name not in db.list_collection_names():
        raise HTTPException(404, f"Collection '{name}' not found")

    total = db[name].count_documents({})
    rows = list(db[name].find({}, {"_id": 0}).skip(skip).limit(limit))
    return {"collection": name, "total": total,
             "skip": skip, "limit": limit,
             "count": len(rows), "rows": _clean_docs(rows)}


# ═════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("Eagle 3D Streaming Analytics API")
    print("=" * 60)
    print(f"Docs:     http://localhost:8000/docs")
    print(f"Health:   http://localhost:8000/health  (no auth)")
    print(f"API key:  {API_KEY[:12]}...  (in X-API-Key header)")
    print("=" * 60)
    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=True)
