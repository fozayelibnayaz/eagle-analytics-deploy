"""
Cross-Platform Correlation Engine — Eagle 3D KPI System v7.2
============================================================
Correlates data across all platforms:
  - KPI (sign-ups, uploads, paid customers)
  - GA4 (web traffic, sources, user behavior)
  - YouTube (views, subscribers, watch time)
  - LinkedIn (followers, engagement, posts)
  - Stripe (revenue, payments)

All numeric operations are fully guarded against TypeError.
"""

import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

DATA_DIR = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)


def _safe_num(val) -> float:
    """Convert anything to float safely."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _safe_sum(series) -> float:
    """Sum a pandas series safely, handling non-numeric types."""
    try:
        if not pd.api.types.is_numeric_dtype(series):
            return 0.0
        return float(series.fillna(0).sum())
    except Exception:
        try:
            return float(pd.to_numeric(series, errors='coerce').fillna(0).sum())
        except Exception:
            return 0.0


def _safe_corr(a: pd.Series, b: pd.Series) -> float:
    """Safely compute correlation."""
    try:
        a_num = pd.to_numeric(a, errors='coerce').fillna(0)
        b_num = pd.to_numeric(b, errors='coerce').fillna(0)
        if len(a_num) < 3 or len(b_num) < 3:
            return 0.0
        r = a_num.corr(b_num)
        return round(float(r), 3) if not np.isnan(r) else 0.0
    except Exception:
        return 0.0


def _ensure_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Force all non-date columns to numeric."""
    for col in df.columns:
        if col == "date" or col == "day":
            continue
        try:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        except Exception:
            df[col] = 0.0
    return df


def build_unified_timeline(
    kpi_df: pd.DataFrame,
    ga4_df: pd.DataFrame = None,
    youtube_daily: pd.DataFrame = None,
    linkedin_daily: pd.DataFrame = None,
    start_date: str = "",
    end_date: str = "",
) -> pd.DataFrame:
    """Build unified timeline with all platform metrics aligned by date."""
    if start_date and end_date:
        dates = pd.date_range(start=start_date, end=end_date, freq="D")
    else:
        dates = pd.date_range(
            start=datetime.now() - timedelta(days=90),
            end=datetime.now(), freq="D",
        )

    unified = pd.DataFrame({"date": pd.to_datetime(dates)})

    # KPI data
    if kpi_df is not None and not kpi_df.empty:
        kpi = kpi_df.copy()
        dc = next((c for c in kpi.columns if "date" in c.lower()), None)
        if dc:
            kpi[dc] = pd.to_datetime(kpi[dc], errors="coerce")
            kpi = _ensure_numeric(kpi)
            rename_map = {}
            for col in kpi.columns:
                if col != dc and col != "date":
                    rename_map[col] = f"kpi_{col}"
            kpi = kpi.rename(columns={**rename_map, dc: "date"})
            kpi = kpi.dropna(subset=["date"])
            unified = unified.merge(kpi, on="date", how="left")

    # GA4 data
    if ga4_df is not None and not ga4_df.empty:
        ga4 = ga4_df.copy()
        dc = next((c for c in ga4.columns if "date" in c.lower() or c == "day"), None)
        if dc:
            ga4[dc] = pd.to_datetime(ga4[dc], errors="coerce")
            ga4 = _ensure_numeric(ga4)
            rename_map = {c: f"ga4_{c}" for c in ga4.columns if c != dc}
            ga4 = ga4.rename(columns={**rename_map, dc: "date"})
            ga4 = ga4.dropna(subset=["date"])
            unified = unified.merge(ga4, on="date", how="left")

    # YouTube data
    if youtube_daily is not None and not youtube_daily.empty:
        yt = youtube_daily.copy()
        dc = next((c for c in yt.columns if c == "day" or "date" in c.lower()), None)
        if dc:
            yt[dc] = pd.to_datetime(yt[dc], errors="coerce")
            yt = _ensure_numeric(yt)
            rename_map = {c: f"yt_{c}" for c in yt.columns if c != dc}
            yt = yt.rename(columns={**rename_map, dc: "date"})
            yt = yt.dropna(subset=["date"])
            unified = unified.merge(yt, on="date", how="left")

    # LinkedIn data
    if linkedin_daily is not None and not linkedin_daily.empty:
        li = linkedin_daily.copy()
        dc = next((c for c in li.columns if "date" in c.lower() or c == "day"), None)
        if dc:
            li[dc] = pd.to_datetime(li[dc], errors="coerce")
            li = _ensure_numeric(li)
            rename_map = {c: f"li_{c}" for c in li.columns if c != dc}
            li = li.rename(columns={**rename_map, dc: "date"})
            li = li.dropna(subset=["date"])
            unified = unified.merge(li, on="date", how="left")

    # Ensure all columns are numeric (except date)
    unified = _ensure_numeric(unified)
    return unified


def compute_correlations(unified: pd.DataFrame) -> Dict[str, Any]:
    """Compute cross-platform correlations."""
    if unified.empty or len(unified) < 3:
        return {"error": "Need at least 3 days of data for correlation", "strong_correlations": [], "matrix": {}, "metric_count": 0, "day_count": len(unified)}

    numeric_cols = [c for c in unified.columns if c != "date" and c != "day"]
    if len(numeric_cols) < 2:
        return {"error": "Need at least 2 metrics for correlation", "strong_correlations": [], "matrix": {}, "metric_count": len(numeric_cols), "day_count": len(unified)}

    # Compute correlation matrix
    corr_matrix = unified[numeric_cols].corr().round(3)

    strong_corrs = []
    for i, col1 in enumerate(numeric_cols):
        for j, col2 in enumerate(numeric_cols):
            if i < j:
                r = corr_matrix.loc[col1, col2]
                if abs(r) > 0.3:
                    strong_corrs.append({
                        "metric_a": col1, "metric_b": col2,
                        "correlation": r,
                        "strength": "strong" if abs(r) > 0.7 else "moderate",
                        "direction": "positive" if r > 0 else "negative",
                    })

    strong_corrs.sort(key=lambda x: abs(x["correlation"]), reverse=True)
    return {
        "matrix": corr_matrix.to_dict(),
        "strong_correlations": strong_corrs[:20],
        "metric_count": len(numeric_cols),
        "day_count": len(unified),
    }


def compute_attribution(unified: pd.DataFrame) -> Dict[str, Any]:
    """Attribution model: which platform metrics best predict KPI conversions."""
    if unified.empty or len(unified) < 7:
        return {"error": "Need at least 7 days of data"}

    kpi_cols = [c for c in unified.columns if c.startswith("kpi_")]
    traffic_cols = [c for c in unified.columns if c.startswith(("ga4_", "yt_", "li_"))]

    if not kpi_cols or not traffic_cols:
        return {"error": "Need both KPI and traffic metrics"}

    attributions = {}
    for kpi_col in kpi_cols:
        kpi_series = unified[kpi_col]
        if _safe_sum(kpi_series) == 0:
            continue

        predictors = []
        for traffic_col in traffic_cols:
            traffic_series = unified[traffic_col]
            if _safe_sum(traffic_series) == 0:
                continue

            r0 = _safe_corr(kpi_series, traffic_series)
            best_lag = 0
            best_r = abs(r0)

            for lag in range(1, 8):
                if len(kpi_series) > lag:
                    try:
                        r_lag = _safe_corr(
                            kpi_series.iloc[lag:].reset_index(drop=True),
                            traffic_series.iloc[:-lag].reset_index(drop=True),
                        )
                        if abs(r_lag) > best_r:
                            best_r = abs(r_lag)
                            best_lag = lag
                    except Exception:
                        pass

            if best_r > 0.2:
                if traffic_col.startswith("ga4_"):
                    platform = "GA4/Web"
                elif traffic_col.startswith("yt_"):
                    platform = "YouTube"
                elif traffic_col.startswith("li_"):
                    platform = "LinkedIn"
                else:
                    platform = "Other"

                predictors.append({
                    "metric": traffic_col, "platform": platform,
                    "correlation": round(best_r, 3), "lag_days": best_lag,
                })

        predictors.sort(key=lambda x: abs(x["correlation"]), reverse=True)
        attributions[kpi_col] = predictors[:10]

    return attributions


def compute_cross_platform_funnel(
    kpi_df: pd.DataFrame,
    ga4_sessions: int = 0, yt_views: int = 0, li_impressions: int = 0,
    period_label: str = "",
) -> Dict[str, Any]:
    """Build cross-platform funnel."""
    total_signups = int(_safe_sum(kpi_df["signups"])) if not kpi_df.empty and "signups" in kpi_df.columns else 0
    total_uploads = int(_safe_sum(kpi_df["first_uploads"])) if not kpi_df.empty and "first_uploads" in kpi_df.columns else 0
    total_paid = int(_safe_sum(kpi_df["paid_customers"])) if not kpi_df.empty and "paid_customers" in kpi_df.columns else 0

    awareness = yt_views + li_impressions

    funnel = {
        "period": period_label or "Selected Period",
        "stages": [
            {"stage": "Awareness", "value": awareness, "icon": "👁️",
             "detail": f"YouTube: {yt_views:,} views + LinkedIn: {li_impressions:,} impressions"},
            {"stage": "Interest", "value": ga4_sessions, "icon": "🌐",
             "detail": f"GA4: {ga4_sessions:,} web sessions"},
            {"stage": "Consideration", "value": total_signups, "icon": "👥",
             "detail": f"KPI: {total_signups:,} sign-ups"},
            {"stage": "Action", "value": total_uploads, "icon": "📤",
             "detail": f"KPI: {total_uploads:,} first uploads"},
            {"stage": "Revenue", "value": total_paid, "icon": "💳",
             "detail": f"KPI: {total_paid:,} paid customers"},
        ],
        "conversion_rates": {},
    }

    stages = funnel["stages"]
    for i in range(1, len(stages)):
        prev = stages[i - 1]["value"]
        curr = stages[i]["value"]
        rate = round(curr / prev * 100, 2) if prev > 0 else 0
        funnel["conversion_rates"][f"{stages[i-1]['stage']}_to_{stages[i]['stage']}"] = rate

    if awareness > 0:
        funnel["conversion_rates"]["awareness_to_revenue"] = round(total_paid / awareness * 100, 4)
    if ga4_sessions > 0:
        funnel["conversion_rates"]["interest_to_revenue"] = round(total_paid / ga4_sessions * 100, 4)

    return funnel


def compute_growth_analysis(unified: pd.DataFrame, lookback_days: int = 28) -> Dict[str, Any]:
    """Analyze growth trends across platforms. FULLY GUARDED."""
    if unified.empty:
        return {"error": "No data available", "metrics": {}}

    dates = unified["date"]
    if len(dates) < lookback_days * 2:
        lookback_days = max(3, len(dates) // 2)

    if lookback_days < 3:
        return {"error": "Not enough data for growth analysis", "metrics": {}}

    current = unified.tail(lookback_days)
    previous = unified.iloc[-(lookback_days * 2):-lookback_days]

    growth = {}
    for col in unified.columns:
        if col in ("date", "day"):
            continue
        try:
            curr_sum = _safe_sum(current[col])
            prev_sum = _safe_sum(previous[col])
            change = curr_sum - prev_sum
            pct_change = round(change / prev_sum * 100, 1) if prev_sum > 0 else 0
            if abs(pct_change) < 5:
                trend = "stable"
            elif pct_change > 0:
                trend = "growing"
            else:
                trend = "declining"

            growth[col] = {
                "current_period": round(curr_sum, 1),
                "previous_period": round(prev_sum, 1),
                "change": round(change, 1),
                "pct_change": pct_change,
                "trend": trend,
            }
        except Exception:
            growth[col] = {
                "current_period": 0, "previous_period": 0,
                "change": 0, "pct_change": 0, "trend": "no data",
            }

    return {"lookback_days": lookback_days, "metrics": growth}


def generate_cross_insights(
    correlations: Dict, attributions: Dict, growth: Dict, funnel: Dict,
) -> List[str]:
    """Generate AI-like insights from cross-platform analysis."""
    insights = []

    strong = correlations.get("strong_correlations", [])
    if strong:
        for corr in strong[:3]:
            direction = "increases" if corr["correlation"] > 0 else "decreases"
            insights.append(
                f"🔗 <b>Correlation ({corr['strength']})</b>: When <code>{corr['metric_a']}</code> goes up, "
                f"<code>{corr['metric_b']}</code> also {direction} (r={corr['correlation']})"
            )

    for kpi, predictors in attributions.items():
        if isinstance(predictors, list) and predictors:
            top = predictors[0]
            if top["lag_days"] > 0:
                insights.append(
                    f"🎯 <b>Attribution</b>: <code>{top['metric']}</code> ({top['platform']}) "
                    f"leads <code>{kpi}</code> by <b>{top['lag_days']} days</b> (r={top['correlation']})"
                )
            else:
                insights.append(
                    f"🎯 <b>Attribution</b>: <code>{top['metric']}</code> ({top['platform']}) "
                    f"directly correlates with <code>{kpi}</code> (r={top['correlation']})"
                )

    metrics = growth.get("metrics", {})
    for metric, data in metrics.items():
        if not isinstance(data, dict):
            continue
        if data.get("trend") == "growing" and data.get("pct_change", 0) > 20:
            insights.append(f"📈 <b>Growth</b>: <code>{metric}</code> is up <b>{data['pct_change']}%</b>")
        elif data.get("trend") == "declining" and data.get("pct_change", 0) < -20:
            insights.append(f"📉 <b>Alert</b>: <code>{metric}</code> is down <b>{abs(data['pct_change'])}%</b>")

    conv_rates = funnel.get("conversion_rates", {})
    awareness_to_revenue = conv_rates.get("awareness_to_revenue", 0)
    if awareness_to_revenue > 0:
        insights.append(f"🔄 <b>Full Funnel</b>: Awareness → Revenue = <b>{awareness_to_revenue}%</b>")

    interest_to_revenue = conv_rates.get("interest_to_revenue", 0)
    if interest_to_revenue > 0:
        insights.append(f"💰 <b>Web Conversion</b>: Sessions → Paid = <b>{interest_to_revenue}%</b>")

    if not insights:
        insights.append("📊 Connect more platforms and add data for richer cross-platform insights.")

    return insights


def compute_platform_comparison(unified: pd.DataFrame) -> Dict[str, Any]:
    """Compare metrics across platforms for the same time period."""
    result = {"platforms": {}, "rankings": []}
    if unified.empty:
        return result

    platform_metrics = {
        "KPI": {"cols": ["signups", "first_uploads", "paid_customers"], "label": "KPI System"},
        "GA4": {"cols": ["sessions", "activeUsers"], "label": "GA4 Analytics"},
        "YouTube": {"cols": ["youtube_views", "youtube_likes", "youtube_subscribers"], "label": "YouTube"},
        "LinkedIn": {"cols": ["linkedin_followers", "linkedin_engagement"], "label": "LinkedIn"},
    }

    for platform, info in platform_metrics.items():
        available = [c for c in info["cols"] if c in unified.columns]
        if available:
            totals = {}
            for col in available:
                totals[col] = _safe_sum(unified[col])
            result["platforms"][platform] = {
                "label": info["label"],
                "metrics": totals,
                "total_engagement": sum(totals.values()),
            }

    # Rank by total engagement
    ranked = sorted(result["platforms"].items(), key=lambda x: x[1]["total_engagement"], reverse=True)
    result["rankings"] = [(p, d["total_engagement"]) for p, d in ranked]

    return result
