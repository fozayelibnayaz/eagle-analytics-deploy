"""
events_tracker.py — Eagle 3D Streaming Analytics Hub
======================================================
Tracks GA4 custom events (GTM-fired) and stores in MongoDB.

Events tracked (extensible via events_registry collection):
  - download_click     (el_launcher, diy_guide)
  - blog_share         (platform, article_title)
  - pricing_*          (billing_cycle, minutes, storage, addon_id)
  - demo_category_filter (category)

Uses GA4 Data API (already OAuth'd) to fetch event counts.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from mongo_client import find_all, find_one, upsert_one, upsert_many, count_docs


# ─── Default registered events (auto-detected from GTM setup) ────
DEFAULT_EVENTS = [
    {"event_name": "download_click",              "category": "engagement", "description": "User clicked a download button", "params": ["el_launcher", "diy_guide"]},
    {"event_name": "blog_share",                  "category": "content",    "description": "User shared a blog post",        "params": ["platform", "article_title"]},
    {"event_name": "pricing_billing_toggle",      "category": "pricing",    "description": "Toggled monthly/annual billing", "params": ["billing_cycle"]},
    {"event_name": "pricing_minutes_changed",     "category": "pricing",    "description": "Changed streaming minutes slider","params": ["minutes"]},
    {"event_name": "pricing_storage_changed",     "category": "pricing",    "description": "Changed storage slider",         "params": ["storage"]},
    {"event_name": "pricing_addon_toggled",       "category": "pricing",    "description": "Toggled a pricing add-on",       "params": ["addon_id", "addon_action"]},
    {"event_name": "pricing_contact_specialist_click", "category": "pricing", "description": "Clicked contact specialist",  "params": []},
    {"event_name": "demo_category_filter",        "category": "demos",      "description": "Filtered demos by category",     "params": ["category"]},
]


def seed_default_events() -> int:
    """Insert default events into events_registry if not present."""
    from datetime import datetime as _dt
    added = 0
    for ev in DEFAULT_EVENTS:
        if not find_one("events_registry", {"event_name": ev["event_name"]}):
            ev["registered_at"] = _dt.utcnow().isoformat()
            ev["is_active"] = True
            upsert_one("events_registry", ev, ["event_name"])
            added += 1
    return added


def list_registered_events(active_only: bool = True) -> List[Dict[str, Any]]:
    filters = {"is_active": True} if active_only else {}
    return find_all("events_registry", filters=filters,
                     sort=[("category", 1), ("event_name", 1)])


def register_event(event_name: str, category: str = "custom",
                    description: str = "", params: Optional[List[str]] = None) -> bool:
    """User-facing: register a new event to track."""
    from datetime import datetime as _dt
    return upsert_one("events_registry", {
        "event_name":    event_name.strip(),
        "category":      category.strip() or "custom",
        "description":   description.strip(),
        "params":        params or [],
        "registered_at": _dt.utcnow().isoformat(),
        "is_active":     True,
    }, ["event_name"])


def deregister_event(event_name: str) -> bool:
    return upsert_one("events_registry",
                       {"event_name": event_name, "is_active": False},
                       ["event_name"])


# ─── GA4 fetch ───────────────────────────────────────────────────
def fetch_events_from_ga4(start: str, end: str) -> Dict[str, int]:
    """Pull event counts from GA4 API for the date range."""
    try:
        from ga4_connector import _get_ga4_client, _ga4_property_id
    except ImportError:
        return {}

    client = _get_ga4_client()
    prop_id = _ga4_property_id()
    if not (client and prop_id):
        return {}

    try:
        from google.analytics.data_v1beta.types import (
            RunReportRequest, Dimension, Metric, DateRange,
        )
        req = RunReportRequest(
            property=f"properties/{prop_id}",
            dimensions=[Dimension(name="eventName")],
            metrics=[Metric(name="eventCount")],
            date_ranges=[DateRange(start_date=start, end_date=end)],
        )
        resp = client.run_report(req)
        out: Dict[str, int] = {}
        for row in resp.rows:
            name = row.dimension_values[0].value
            count = int(row.metric_values[0].value or 0)
            out[name] = count
        return out
    except Exception as e:
        print(f"[events_tracker] GA4 fetch failed: {e}")
        return {}


def fetch_event_breakdown(event_name: str, start: str, end: str,
                           dimension: str = "eventName") -> List[Dict[str, Any]]:
    """Get param breakdown for a specific event."""
    try:
        from ga4_connector import _get_ga4_client, _ga4_property_id
        from google.analytics.data_v1beta.types import (
            RunReportRequest, Dimension, Metric, DateRange,
            FilterExpression, Filter,
        )
        client = _get_ga4_client()
        prop_id = _ga4_property_id()
        if not (client and prop_id):
            return []

        req = RunReportRequest(
            property=f"properties/{prop_id}",
            dimensions=[Dimension(name="eventName"),
                         Dimension(name=dimension)],
            metrics=[Metric(name="eventCount")],
            date_ranges=[DateRange(start_date=start, end_date=end)],
            dimension_filter=FilterExpression(
                filter=Filter(
                    field_name="eventName",
                    string_filter=Filter.StringFilter(value=event_name),
                )
            ),
            limit=50,
        )
        resp = client.run_report(req)
        return [{
            "event_name": r.dimension_values[0].value,
            "value":      r.dimension_values[1].value,
            "count":      int(r.metric_values[0].value or 0),
        } for r in resp.rows]
    except Exception as e:
        print(f"[events_tracker] breakdown failed: {e}")
        return []


# ─── Snapshot to Mongo (for historical trends) ──────────────────
def snapshot_daily_events(days_back: int = 1) -> int:
    """Save today's event counts as historical snapshot."""
    from datetime import datetime as _dt
    end = date.today()
    start = end - timedelta(days=days_back)
    counts = fetch_events_from_ga4(start.isoformat(), end.isoformat())
    if not counts:
        return 0

    rows = []
    for name, count in counts.items():
        rows.append({
            "date":       end.isoformat(),
            "event_name": name,
            "count":      count,
            "snapshot_at": _dt.utcnow().isoformat(),
        })
    from mongo_client import get_raw_db
    db = get_raw_db()
    if db is not None:
        # Composite key = (date + event_name)
        for r in rows:
            db["events_daily"].update_one(
                {"date": r["date"], "event_name": r["event_name"]},
                {"$set": r}, upsert=True,
            )
    return len(rows)


# ─── Alert: event anomaly ───────────────────────────────────────
def detect_event_anomalies() -> List[Dict[str, Any]]:
    """
    Compare last 7d events vs previous 7d for each registered event.
    Alert on ≥2x spike or ≥50% drop.
    """
    today = date.today()
    cur_start = (today - timedelta(days=7)).isoformat()
    prev_start = (today - timedelta(days=14)).isoformat()
    prev_end = cur_start
    end = today.isoformat()

    cur = fetch_events_from_ga4(cur_start, end)
    prv = fetch_events_from_ga4(prev_start, prev_end)

    events = list_registered_events(active_only=True)
    tracked = {e["event_name"] for e in events}

    anomalies = []
    for name in tracked | set(cur.keys()):
        c = cur.get(name, 0)
        p = prv.get(name, 0)
        if p >= 5 and c >= p * 2:
            anomalies.append({
                "event": name, "type": "spike",
                "current": c, "previous": p,
                "message": f"🚀 Event SPIKE: '{name}' {c} vs {p} prev 7d ({c/p:.1f}x)",
            })
        elif p >= 10 and c <= p * 0.5:
            anomalies.append({
                "event": name, "type": "drop",
                "current": c, "previous": p,
                "message": f"📉 Event DROP: '{name}' {c} vs {p} prev 7d ({c/p*100:.0f}%)",
            })
    return anomalies


if __name__ == "__main__":
    print("Seeding default events...")
    n = seed_default_events()
    print(f"  Registered {n} new events")
    print()
    print("All registered events:")
    for e in list_registered_events():
        print(f"  {e['category']:12s} | {e['event_name']:38s} | params: {e.get('params', [])}")
    print()
    print("Fetching last 7 days from GA4...")
    end = date.today()
    start = end - timedelta(days=7)
    counts = fetch_events_from_ga4(start.isoformat(), end.isoformat())
    if counts:
        print(f"  Got {len(counts)} unique events:")
        for name, count in sorted(counts.items(), key=lambda x: -x[1])[:20]:
            print(f"    {name:40s} {count:>6}")
    else:
        print("  No events (GA4 not configured or no data yet)")



def fetch_events_from_mongo(start: str, end: str) -> dict:
    """
    Read historical event snapshots from Mongo (fallback when GA4 empty).
    Returns event_name -> total count for the range.
    """
    from mongo_client import find_all
    rows = find_all("events_daily", filters={
        "date": {"$gte": start, "$lte": end},
    })
    out: dict = {}
    for r in rows:
        name = r.get("event_name", "")
        count = int(r.get("count", 0) or 0)
        if name:
            out[name] = out.get(name, 0) + count
    return out


def fetch_events_combined(start: str, end: str) -> dict:
    """
    Best-of-both: try GA4 live first, fall back to Mongo history.
    Returns dict with keys: source, counts.
    """
    live = fetch_events_from_ga4(start, end)
    if live:
        return {"source": "GA4 live", "counts": live}
    hist = fetch_events_from_mongo(start, end)
    if hist:
        return {"source": "MongoDB history (cached)", "counts": hist}
    return {"source": "none", "counts": {}}
