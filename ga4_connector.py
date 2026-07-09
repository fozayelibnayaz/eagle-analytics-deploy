"""
ga4_connector.py — Eagle 3D Streaming Analytics Hub
=====================================================
Google Analytics 4 Data API v1beta client.

Uses `ga4_service_account` from Streamlit secrets (falls back to
google_creds.json on disk). Reads GA4_PROPERTY_ID.

Public functions:
  - is_configured()
  - fetch_utm_traffic(start_date, end_date)
  - fetch_geo_traffic(start_date, end_date)
  - fetch_page_performance(start_date, end_date)
  - fetch_events(start_date, end_date)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

try:
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        DateRange, Dimension, Metric, RunReportRequest,
    )
    from google.oauth2 import service_account
    _HAS_GA4 = True
except ImportError:
    _HAS_GA4 = False


# ─────────────────────────────────────────────────────────────────
# SECRETS
# ─────────────────────────────────────────────────────────────────
def _secret(name: str, default: str = "") -> str:
    val = os.environ.get(name, "").strip()
    if val:
        return val
    try:
        import streamlit as st
        return str(st.secrets.get(name, "") or default).strip()
    except Exception:
        return default


def _property_id() -> str:
    return _secret("GA4_PROPERTY_ID")


def _get_creds():
    """Load service account credentials from secrets → env → disk."""
    if not _HAS_GA4:
        return None

    scopes = ["https://www.googleapis.com/auth/analytics.readonly"]

    # 1. Streamlit secrets: ga4_service_account
    try:
        import streamlit as st
        sa = dict(st.secrets.get("ga4_service_account", {}))
        if sa and sa.get("client_email"):
            if "private_key" in sa:
                sa["private_key"] = sa["private_key"].replace("\\n", "\n")
            return service_account.Credentials.from_service_account_info(sa, scopes=scopes)
    except Exception:
        pass

    # 2. Streamlit secrets: GOOGLE_CREDS
    try:
        import streamlit as st
        sa = dict(st.secrets.get("GOOGLE_CREDS", {}))
        if sa and sa.get("client_email"):
            if "private_key" in sa:
                sa["private_key"] = sa["private_key"].replace("\\n", "\n")
            return service_account.Credentials.from_service_account_info(sa, scopes=scopes)
    except Exception:
        pass

    # 3. google_creds.json on disk
    p = Path("google_creds.json")
    if p.exists():
        try:
            return service_account.Credentials.from_service_account_file(
                str(p), scopes=scopes
            )
        except Exception:
            pass

    return None


def _client() -> Optional[Any]:
    creds = _get_creds()
    if not creds:
        return None
    try:
        return BetaAnalyticsDataClient(credentials=creds)
    except Exception as e:
        print(f"[ga4_connector] Client init failed: {e}")
        return None


def is_configured() -> bool:
    return bool(_HAS_GA4 and _property_id() and _get_creds())


# ─────────────────────────────────────────────────────────────────
# CORE REQUEST
# ─────────────────────────────────────────────────────────────────
def _run_report(
    dimensions: List[str],
    metrics: List[str],
    start_date: str,
    end_date: str,
    limit: int = 100000,
) -> pd.DataFrame:
    prop = _property_id()
    cli = _client()
    if not cli or not prop:
        return pd.DataFrame()

    request = RunReportRequest(
        property=f"properties/{prop}",
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        limit=limit,
    )
    try:
        response = cli.run_report(request)
    except Exception as e:
        print(f"[ga4_connector] run_report failed: {e}")
        return pd.DataFrame()

    rows = []
    for row in response.rows:
        d = {}
        for i, dim in enumerate(dimensions):
            d[dim] = row.dimension_values[i].value
        for i, m in enumerate(metrics):
            v = row.metric_values[i].value
            try:
                d[m] = float(v) if "." in v else int(v)
            except (ValueError, TypeError):
                d[m] = 0
        rows.append(d)

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────
# PRE-BUILT QUERIES
# ─────────────────────────────────────────────────────────────────
def fetch_utm_traffic(start_date: str, end_date: str) -> pd.DataFrame:
    """Sessions/users by UTM sourceMedium."""
    return _run_report(
        dimensions=["sessionSourceMedium"],
        metrics=["sessions", "activeUsers", "screenPageViews", "bounceRate"],
        start_date=start_date,
        end_date=end_date,
    ).rename(columns={"sessionSourceMedium": "sourceMedium"})


def fetch_geo_traffic(start_date: str, end_date: str) -> pd.DataFrame:
    return _run_report(
        dimensions=["country", "city"],
        metrics=["sessions", "activeUsers"],
        start_date=start_date,
        end_date=end_date,
    )


def fetch_page_performance(start_date: str, end_date: str) -> pd.DataFrame:
    return _run_report(
        dimensions=["pagePath"],
        metrics=["screenPageViews", "activeUsers", "averageSessionDuration"],
        start_date=start_date,
        end_date=end_date,
    )


def fetch_events(start_date: str, end_date: str) -> pd.DataFrame:
    return _run_report(
        dimensions=["eventName"],
        metrics=["eventCount", "totalUsers"],
        start_date=start_date,
        end_date=end_date,
    )


def fetch_devices(start_date: str, end_date: str) -> pd.DataFrame:
    return _run_report(
        dimensions=["deviceCategory"],
        metrics=["sessions", "activeUsers"],
        start_date=start_date,
        end_date=end_date,
    )


def fetch_daily_sessions(start_date: str, end_date: str) -> pd.DataFrame:
    return _run_report(
        dimensions=["date"],
        metrics=["sessions", "activeUsers", "newUsers"],
        start_date=start_date,
        end_date=end_date,
    )


# ─────────────────────────────────────────────────────────────────
# CACHE HELPERS
# ─────────────────────────────────────────────────────────────────
def build_traffic_cache(days: int = 30) -> Dict[str, Any]:
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    utm = fetch_utm_traffic(start, end)
    geo = fetch_geo_traffic(start, end)

    cache: Dict[str, Any] = {
        "scraped_at": datetime.now().isoformat(),
        "start_date": start,
        "end_date":   end,
    }
    if not utm.empty:
        cache["total_sessions"] = int(utm.get("sessions", 0).sum()) if "sessions" in utm.columns else 0
        cache["total_users"]    = int(utm.get("activeUsers", 0).sum()) if "activeUsers" in utm.columns else 0
        if "sourceMedium" in utm.columns:
            top = utm.groupby("sourceMedium")["sessions"].sum().sort_values(ascending=False).head(10)
            cache["top_sources"] = [(s, int(v)) for s, v in top.items()]

    if not geo.empty and "country" in geo.columns:
        top = geo.groupby("country")["sessions"].sum().sort_values(ascending=False).head(10)
        cache["top_countries"] = [(c, int(v)) for c, v in top.items()]

    Path("data_output").mkdir(exist_ok=True)
    (Path("data_output") / "ga4_traffic_cache.json").write_text(
        json.dumps(cache, default=str, indent=2)
    )
    return cache


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"GA4 configured: {is_configured()}")
    print(f"Property ID: {_property_id()}")
    if is_configured():
        print("\nBuilding 30-day traffic cache...")
        cache = build_traffic_cache(30)
        print(json.dumps(cache, indent=2, default=str))
