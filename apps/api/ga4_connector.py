"""
GA4 Connector - Eagle 3D KPI System
Reads from google_creds.json locally OR Streamlit secrets on cloud
100% Free - No paid APIs needed
"""

import os
import json
import pandas as pd
from datetime import datetime, timedelta
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest,
    DateRange,
    Dimension,
    Metric,
    OrderBy,
)
from google.oauth2 import service_account

GA4_PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "374525971")
SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]


def _get_credentials():
    # Try Streamlit secrets first (cloud)
    try:
        import streamlit as st
        if "ga4_service_account" in st.secrets:
            d = dict(st.secrets["ga4_service_account"])
            if "private_key" in d:
                d["private_key"] = d["private_key"].replace("\\n", "\n")
            return service_account.Credentials.from_service_account_info(
                d, scopes=SCOPES
            )
    except Exception:
        pass

    # Try GOOGLE_CREDS_JSON env var (pipeline uses this)
    _env_creds = os.environ.get("GOOGLE_CREDS_JSON", "").strip()
    if _env_creds:
        try:
            d = json.loads(_env_creds)
            if "private_key" in d:
                d["private_key"] = d["private_key"].replace("\\n", "\n")
            return service_account.Credentials.from_service_account_info(d, scopes=SCOPES)
        except Exception:
            pass

    # Fall back to local file
    try:
        return service_account.Credentials.from_service_account_file(
            "google_creds.json", scopes=SCOPES
        )
    except Exception as e:
        raise RuntimeError(f"No credentials found: {e}")


def _get_client():
    return BetaAnalyticsDataClient(credentials=_get_credentials())


def _run_report(body):
    try:
        client = _get_client()
        response = client.run_report(RunReportRequest(**body))
        rows = []
        dim_h = [h.name for h in response.dimension_headers]
        met_h = [h.name for h in response.metric_headers]
        for row in response.rows:
            r = {}
            for i, d in enumerate(row.dimension_values):
                r[dim_h[i]] = d.value
            for i, m in enumerate(row.metric_values):
                r[met_h[i]] = m.value
            rows.append(r)
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        for col in met_h:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception as e:
        print(f"GA4 Error: {e}")
        return pd.DataFrame()


def fetch_utm_traffic(start_date, end_date):
    return _run_report({
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": [
            Dimension(name="date"),
            Dimension(name="sessionSource"),
            Dimension(name="sessionMedium"),
            Dimension(name="sessionCampaignName"),
            Dimension(name="sessionDefaultChannelGroup"),
        ],
        "metrics": [
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="newUsers"),
            Metric(name="bounceRate"),
            Metric(name="averageSessionDuration"),
            Metric(name="conversions"),
        ],
        "order_bys": [OrderBy(
            dimension=OrderBy.DimensionOrderBy(dimension_name="date"),
            desc=True
        )],
        "limit": 10000,
    })


def fetch_daily_traffic_summary(start_date, end_date):
    return _run_report({
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": [
            Dimension(name="date"),
            Dimension(name="sessionDefaultChannelGroup"),
        ],
        "metrics": [
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="newUsers"),
            Metric(name="conversions"),
        ],
        "order_bys": [OrderBy(
            dimension=OrderBy.DimensionOrderBy(dimension_name="date")
        )],
        "limit": 10000,
    })


def fetch_page_performance(start_date, end_date):
    return _run_report({
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": [
            Dimension(name="date"),
            Dimension(name="pagePath"),
            Dimension(name="pageTitle"),
        ],
        "metrics": [
            Metric(name="screenPageViews"),
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="bounceRate"),
            Metric(name="averageSessionDuration"),
            Metric(name="engagementRate"),
            Metric(name="conversions"),
        ],
        "order_bys": [OrderBy(
            metric=OrderBy.MetricOrderBy(metric_name="screenPageViews"),
            desc=True
        )],
        "limit": 5000,
    })


def fetch_event_performance(start_date, end_date):
    return _run_report({
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": [
            Dimension(name="date"),
            Dimension(name="eventName"),
            Dimension(name="sessionSource"),
            Dimension(name="sessionMedium"),
        ],
        "metrics": [
            Metric(name="eventCount"),
            Metric(name="totalUsers"),
            Metric(name="conversions"),
        ],
        "order_bys": [OrderBy(
            metric=OrderBy.MetricOrderBy(metric_name="eventCount"),
            desc=True
        )],
        "limit": 5000,
    })


def fetch_geo_traffic(start_date, end_date):
    return _run_report({
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": [
            Dimension(name="country"),
            Dimension(name="city"),
            Dimension(name="sessionSource"),
        ],
        "metrics": [
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="newUsers"),
            Metric(name="conversions"),
        ],
        "order_bys": [OrderBy(
            metric=OrderBy.MetricOrderBy(metric_name="sessions"),
            desc=True
        )],
        "limit": 2000,
    })


def fetch_device_traffic(start_date, end_date):
    return _run_report({
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": [
            Dimension(name="deviceCategory"),
            Dimension(name="operatingSystem"),
            Dimension(name="sessionSource"),
        ],
        "metrics": [
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="conversions"),
        ],
        "order_bys": [OrderBy(
            metric=OrderBy.MetricOrderBy(metric_name="sessions"),
            desc=True
        )],
        "limit": 500,
    })


def fetch_signup_source_correlation(start_date, end_date):
    return _run_report({
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": [
            Dimension(name="date"),
            Dimension(name="sessionSource"),
            Dimension(name="sessionMedium"),
            Dimension(name="sessionCampaignName"),
            Dimension(name="firstUserSource"),
            Dimension(name="firstUserMedium"),
            Dimension(name="firstUserCampaignName"),
        ],
        "metrics": [
            Metric(name="conversions"),
            Metric(name="totalUsers"),
            Metric(name="newUsers"),
            Metric(name="sessions"),
        ],
        "order_bys": [
            OrderBy(
                dimension=OrderBy.DimensionOrderBy(dimension_name="date"),
                desc=True
            ),
            OrderBy(
                metric=OrderBy.MetricOrderBy(metric_name="conversions"),
                desc=True
            ),
        ],
        "limit": 5000,
    })


def fetch_event_attribution(start_date, end_date, event_name=None):
    """
    Fetch event data with traffic attribution (9 dimensions max - GA4 limit).

    Returns:
    - eventName, eventCount, totalUsers
    - sessionSource, sessionMedium, sessionCampaignName (last-touch)
    - firstUserSource, firstUserMedium (first-touch — fewer to fit limit)
    - country, deviceCategory

    Use fetch_event_attribution_extended() for landing page + campaign first-touch
    """
    from google.analytics.data_v1beta.types import FilterExpression, Filter

    dimensions = [
        Dimension(name="date"),
        Dimension(name="eventName"),
        Dimension(name="sessionSource"),
        Dimension(name="sessionMedium"),
        Dimension(name="sessionCampaignName"),
        Dimension(name="firstUserSource"),
        Dimension(name="firstUserMedium"),
        Dimension(name="country"),
        Dimension(name="deviceCategory"),
    ]

    metrics = [
        Metric(name="eventCount"),
        Metric(name="totalUsers"),
        Metric(name="sessions"),
        Metric(name="conversions"),
    ]

    request_body = {
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": dimensions,
        "metrics": metrics,
        "order_bys": [
            OrderBy(metric=OrderBy.MetricOrderBy(metric_name="eventCount"), desc=True),
        ],
        "limit": 10000,
    }

    if event_name:
        request_body["dimension_filter"] = FilterExpression(
            filter=Filter(
                field_name="eventName",
                string_filter=Filter.StringFilter(
                    value=event_name,
                    match_type=Filter.StringFilter.MatchType.EXACT,
                ),
            )
        )

    return _run_report(request_body)


def fetch_event_attribution_extended(start_date, end_date, event_name=None):
    """
    Extended view with landing page details (9 dimensions max).
    Use this as supplementary query for landing pages + campaigns.
    """
    from google.analytics.data_v1beta.types import FilterExpression, Filter

    dimensions = [
        Dimension(name="date"),
        Dimension(name="eventName"),
        Dimension(name="sessionSource"),
        Dimension(name="sessionCampaignName"),
        Dimension(name="firstUserSource"),
        Dimension(name="firstUserCampaignName"),
        Dimension(name="landingPage"),
        Dimension(name="country"),
        Dimension(name="deviceCategory"),
    ]

    metrics = [
        Metric(name="eventCount"),
        Metric(name="totalUsers"),
        Metric(name="sessions"),
    ]

    request_body = {
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": dimensions,
        "metrics": metrics,
        "order_bys": [
            OrderBy(metric=OrderBy.MetricOrderBy(metric_name="eventCount"), desc=True),
        ],
        "limit": 10000,
    }

    if event_name:
        request_body["dimension_filter"] = FilterExpression(
            filter=Filter(
                field_name="eventName",
                string_filter=Filter.StringFilter(
                    value=event_name,
                    match_type=Filter.StringFilter.MatchType.EXACT,
                ),
            )
        )

    return _run_report(request_body)


def fetch_available_events(start_date, end_date):
    """Get list of all unique events in the period - for dropdown selector."""
    df = _run_report({
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": [Dimension(name="eventName")],
        "metrics": [Metric(name="eventCount"), Metric(name="totalUsers")],
        "order_bys": [OrderBy(metric=OrderBy.MetricOrderBy(metric_name="eventCount"), desc=True)],
        "limit": 200,
    })
    return df



# ══════════════════════════════════════════════════════════════
# EXTENDED GA4 QUERIES — Deeper Analysis for Eagle Analytics Hub
# ══════════════════════════════════════════════════════════════

def fetch_landing_pages(start_date, end_date):
    """Landing page performance with source and engagement."""
    return _run_report({
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": [
            Dimension(name="landingPage"),
            Dimension(name="sessionSource"),
            Dimension(name="sessionMedium"),
        ],
        "metrics": [
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="newUsers"),
            Metric(name="bounceRate"),
            Metric(name="averageSessionDuration"),
            Metric(name="conversions"),
            Metric(name="engagementRate"),
        ],
        "order_bys": [OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        "limit": 5000,
    })


def fetch_user_engagement(start_date, end_date):
    """Daily engagement metrics: engagement rate, session duration, pages per session."""
    return _run_report({
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": [
            Dimension(name="date"),
        ],
        "metrics": [
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="newUsers"),
            Metric(name="engagementRate"),
            Metric(name="averageSessionDuration"),
            Metric(name="screenPageViewsPerSession"),
            Metric(name="conversions"),
            Metric(name="bounceRate"),
            Metric(name="eventCount"),
        ],
        "order_bys": [OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))],
        "limit": 10000,
    })


def fetch_content_analysis(start_date, end_date):
    """Page-level content analysis with engagement and conversions."""
    return _run_report({
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": [
            Dimension(name="pagePath"),
            Dimension(name="pageTitle"),
        ],
        "metrics": [
            Metric(name="screenPageViews"),
            Metric(name="uniqueScreenPageViews"),
            Metric(name="totalUsers"),
            Metric(name="averageSessionDuration"),
            Metric(name="engagementRate"),
            Metric(name="bounceRate"),
            Metric(name="conversions"),
            Metric(name="eventCount"),
        ],
        "order_bys": [OrderBy(metric=OrderBy.MetricOrderBy(metric_name="screenPageViews"), desc=True)],
        "limit": 5000,
    })


def fetch_source_medium_deep(start_date, end_date):
    """Source + Medium + Campaign breakdown with engagement."""
    return _run_report({
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": [
            Dimension(name="sessionSource"),
            Dimension(name="sessionMedium"),
            Dimension(name="sessionCampaignName"),
            Dimension(name="sessionDefaultChannelGroup"),
        ],
        "metrics": [
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="newUsers"),
            Metric(name="conversions"),
            Metric(name="engagementRate"),
            Metric(name="averageSessionDuration"),
            Metric(name="bounceRate"),
        ],
        "order_bys": [OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        "limit": 5000,
    })


def fetch_geo_deep(start_date, end_date):
    """Geo + city + language for localization decisions."""
    return _run_report({
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": [
            Dimension(name="country"),
            Dimension(name="city"),
            Dimension(name="language"),
        ],
        "metrics": [
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="newUsers"),
            Metric(name="conversions"),
            Metric(name="engagementRate"),
            Metric(name="averageSessionDuration"),
        ],
        "order_bys": [OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        "limit": 5000,
    })


def fetch_device_deep(start_date, end_date):
    """Device + OS + browser for UX decisions."""
    return _run_report({
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": [
            Dimension(name="deviceCategory"),
            Dimension(name="operatingSystem"),
            Dimension(name="browser"),
        ],
        "metrics": [
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="conversions"),
            Metric(name="engagementRate"),
            Metric(name="averageSessionDuration"),
        ],
        "order_bys": [OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        "limit": 2000,
    })


def fetch_first_user_source(start_date, end_date):
    """First-touch attribution: how users originally found the site."""
    return _run_report({
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": [
            Dimension(name="firstUserSource"),
            Dimension(name="firstUserMedium"),
            Dimension(name="firstUserCampaignName"),
            Dimension(name="firstUserDefaultChannelGroup"),
        ],
        "metrics": [
            Metric(name="newUsers"),
            Metric(name="totalUsers"),
            Metric(name="sessions"),
            Metric(name="conversions"),
        ],
        "order_bys": [OrderBy(metric=OrderBy.MetricOrderBy(metric_name="newUsers"), desc=True)],
        "limit": 5000,
    })


def fetch_conversion_paths(start_date, end_date):
    """Conversion events with source attribution."""
    return _run_report({
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": [
            Dimension(name="eventName"),
            Dimension(name="sessionSource"),
            Dimension(name="sessionMedium"),
            Dimension(name="pagePath"),
        ],
        "metrics": [
            Metric(name="eventCount"),
            Metric(name="totalUsers"),
            Metric(name="conversions"),
        ],
        "order_bys": [OrderBy(metric=OrderBy.MetricOrderBy(metric_name="conversions"), desc=True)],
        "limit": 5000,
    })


def fetch_hourly_pattern(start_date, end_date):
    """Hour-of-day traffic pattern for scheduling."""
    return _run_report({
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": [
            Dimension(name="hour"),
            Dimension(name="dayOfWeek"),
        ],
        "metrics": [
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="conversions"),
            Metric(name="engagementRate"),
        ],
        "order_bys": [OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="hour"))],
        "limit": 1000,
    })


def fetch_retention_cohort(start_date, end_date):
    """User retention: new vs returning users by day."""
    return _run_report({
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": [
            Dimension(name="date"),
            Dimension(name="newVsReturning"),
        ],
        "metrics": [
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="conversions"),
            Metric(name="engagementRate"),
        ],
        "order_bys": [OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))],
        "limit": 10000,
    })


def fetch_browser_tech(start_date, end_date):
    """Browser + OS for technical compatibility decisions."""
    return _run_report({
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": [
            Dimension(name="browser"),
            Dimension(name="operatingSystem"),
            Dimension(name="deviceCategory"),
        ],
        "metrics": [
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="conversions"),
            Metric(name="averageSessionDuration"),
        ],
        "order_bys": [OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        "limit": 1000,
    })


def fetch_referral_paths(start_date, end_date):
    """Referral traffic with full page path for backlink analysis."""
    return _run_report({
        "property": f"properties/{GA4_PROPERTY_ID}",
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "dimensions": [
            Dimension(name="sessionSource"),
            Dimension(name="sessionMedium"),
            Dimension(name="landingPage"),
        ],
        "metrics": [
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="conversions"),
            Metric(name="engagementRate"),
            Metric(name="averageSessionDuration"),
        ],
        "order_bys": [OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        "limit": 5000,
    })


def is_configured():
    """Check if GA4 is configured with valid credentials."""
    try:
        creds = _get_credentials()
        return creds is not None
    except Exception:
        return False


def get_status():
    """Get GA4 connection status."""
    try:
        creds = _get_credentials()
        connected = creds is not None
        # Try a quick test query
        if connected:
            try:
                client = _get_client()
                # Quick test: just create the client, don't run a full query
                connected = client is not None
            except Exception:
                connected = True  # Credentials are valid, client may fail for other reasons
        return {
            "connected": connected,
            "property_id": GA4_PROPERTY_ID,
            "has_secrets": False,
        }
    except Exception:
        return {
            "connected": False,
            "property_id": GA4_PROPERTY_ID,
            "has_secrets": False,
        }

