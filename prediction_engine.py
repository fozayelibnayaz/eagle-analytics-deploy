"""
prediction_engine.py — ML Forecasting & Trend Analysis v2
=========================================================
Ensemble: Moving Average + Weighted Linear Regression + Exponential Smoothing
+ Seasonality detection + Confidence intervals + Day-of-week patterns
Pure Python — no external API needed.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict
import math


def _to_float(val):
    try:
        return float(val) if not pd.isna(val) else 0.0
    except Exception:
        return 0.0


def prepare_time_series(kpi_df, metric_col="signups"):
    """Convert KPI DataFrame to time series array."""
    if kpi_df is None or kpi_df.empty or "date" not in kpi_df.columns:
        return np.array([]), []
    
    df = kpi_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    
    if metric_col not in df.columns:
        return np.array([]), []
    
    values = df[metric_col].apply(_to_float).values
    dates = df["date"].dt.strftime("%Y-%m-%d").tolist()
    return values, dates


def moving_average_forecast(values, window=7, horizon=14):
    """Simple moving average forecast."""
    if len(values) < window:
        window = max(len(values), 1)
    
    recent = values[-window:]
    avg = np.mean(recent)
    std = np.std(recent) if len(recent) > 1 else avg * 0.2
    
    forecast = []
    for i in range(horizon):
        if len(values) >= 7:
            trend = (np.mean(values[-3:]) - np.mean(values[-7:])) / 7
        else:
            trend = 0
        predicted = max(0, avg + trend * i)
        forecast.append(predicted)
    
    return np.array(forecast), avg, std


def linear_regression_forecast(values, horizon=14):
    """Linear regression trend forecast."""
    n = len(values)
    if n < 3:
        return moving_average_forecast(values, horizon=horizon)
    
    x = np.arange(n)
    weights = np.exp(np.linspace(0, 2, n))
    
    W = np.diag(weights)
    X = np.column_stack([np.ones(n), x])
    try:
        beta = np.linalg.inv(X.T @ W @ X) @ X.T @ W @ values
    except np.linalg.LinAlgError:
        return moving_average_forecast(values, horizon=horizon)
    
    slope = beta[1]
    intercept = beta[0]
    
    future_x = np.arange(n, n + horizon)
    forecast = intercept + slope * future_x
    forecast = np.maximum(forecast, 0)
    
    return forecast, slope, intercept


def exponential_smoothing_forecast(values, alpha=0.3, horizon=14):
    """Exponential smoothing forecast."""
    if len(values) < 2:
        return moving_average_forecast(values, horizon=horizon)
    
    smoothed = [values[0]]
    for i in range(1, len(values)):
        smoothed.append(alpha * values[i] + (1 - alpha) * smoothed[-1])
    
    last_smoothed = smoothed[-1]
    trend = (smoothed[-1] - smoothed[max(0, len(smoothed) - 7)]) / min(7, len(smoothed))
    
    forecast = []
    for i in range(horizon):
        predicted = last_smoothed + trend * (i + 1)
        forecast.append(max(0, predicted))
    
    return np.array(forecast), trend, last_smoothed


def detect_seasonality(values, dates=None):
    """Detect day-of-week patterns in data."""
    if len(values) < 14 or dates is None or len(dates) != len(values):
        return None
    
    try:
        dow_values = {i: [] for i in range(7)}
        for i, d in enumerate(dates):
            dt = datetime.strptime(d, "%Y-%m-%d")
            dow_values[dt.weekday()].append(values[i])
        
        dow_avg = {k: np.mean(v) if v else 0 for k, v in dow_values.items()}
        overall_avg = np.mean(values)
        if overall_avg == 0: return None
        
        dow_index = {k: v / overall_avg for k, v in dow_avg.items()}
        
        # Check if there's meaningful variation
        max_ratio = max(dow_index.values()) if dow_index else 0
        min_ratio = min(dow_index.values()) if dow_index else 0
        if max_ratio - min_ratio < 0.15:
            return None
        
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        return {
            "pattern": {day_names[k]: round(v, 2) for k, v in dow_index.items()},
            "best_day": day_names[max(dow_index, key=dow_index.get)],
            "worst_day": day_names[min(dow_index, key=dow_index.get)],
        }
    except:
        return None


def ensemble_forecast(values, horizon=14, dates=None):
    """Combine multiple forecast methods for better accuracy."""
    if len(values) < 3:
        ma_f, avg, std = moving_average_forecast(values, horizon=horizon)
        return {
            "forecast": ma_f,
            "method": "moving_average",
            "confidence": "low",
            "avg_daily": avg,
            "std_daily": std,
        }
    
    ma_f, ma_avg, ma_std = moving_average_forecast(values, horizon=horizon)
    lr_f, lr_slope, lr_int = linear_regression_forecast(values, horizon=horizon)
    es_f, es_trend, es_last = exponential_smoothing_forecast(values, horizon=horizon)
    
    # Weighted ensemble
    ensemble = 0.3 * ma_f + 0.4 * lr_f + 0.3 * es_f
    
    # Confidence based on coefficient of variation
    recent_std = np.std(values[-7:]) if len(values) >= 7 else np.std(values)
    mean_val = np.mean(values[-7:]) if len(values) >= 7 else np.mean(values)
    cv = recent_std / mean_val if mean_val > 0 else 1.0
    
    if cv < 0.3:
        confidence = "high"
    elif cv < 0.6:
        confidence = "medium"
    else:
        confidence = "low"
    
    # Trend direction
    if lr_slope > 0.5:
        trend = "📈 Upward"
    elif lr_slope < -0.5:
        trend = "📉 Downward"
    else:
        trend = "➡️ Stable"
    
    # Seasonality
    seasonality = detect_seasonality(values, dates)
    
    return {
        "forecast": ensemble,
        "method": "ensemble (MA + Linear + Exponential)",
        "confidence": confidence,
        "trend_direction": trend,
        "slope": lr_slope,
        "avg_daily": round(mean_val, 1),
        "std_daily": round(recent_std, 1),
        "cv": round(cv, 2),
        "seasonality": seasonality,
    }


def generate_forecast_report(kpi_df, horizon=14, prev_kpi_df=None):
    """Generate complete forecast report for all metrics."""
    metrics = {
        "signups": {"name": "Sign-ups", "col": "signups"},
        "first_uploads": {"name": "First Uploads", "col": "first_uploads"},
        "paid_customers": {"name": "Paid Customers", "col": "paid_customers"},
    }
    
    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "horizon_days": horizon,
        "metrics": {},
    }
    
    for key, info in metrics.items():
        values, dates = prepare_time_series(kpi_df, info["col"])
        
        if len(values) < 3:
            report["metrics"][key] = {
                "name": info["name"],
                "status": "insufficient_data",
                "message": f"Need at least 3 days of data, have {len(values)}",
            }
            continue
        
        result = ensemble_forecast(values, horizon, dates)
        
        last_date = datetime.strptime(dates[-1], "%Y-%m-%d") if dates else datetime.now()
        pred_dates = [(last_date + timedelta(days=i+1)).strftime("%Y-%m-%d") for i in range(horizon)]
        
        forecast = result["forecast"]
        
        # Compute predictions for various horizons
        predictions = {}
        for h in [7, 14, 21, 30, 60, 90]:
            if h <= len(forecast):
                predictions[f"predicted_next_{h}d"] = int(np.sum(forecast[:h]))
                predictions[f"best_case_{h}d"] = int(np.sum(forecast[:h] * 1.2))
                predictions[f"worst_case_{h}d"] = int(np.sum(forecast[:h] * 0.8))
        
        metric_report = {
            "name": info["name"],
            "status": "ok",
            "current_total": int(np.sum(values)),
            "current_days": len(values),
            "avg_daily": result["avg_daily"],
            "trend": result["trend_direction"],
            "confidence": result["confidence"],
            "method": result["method"],
            "slope": round(result["slope"], 2),
            "cv": result["cv"],
            "daily_predictions": [
                {"date": d, "predicted": round(float(v), 1)}
                for d, v in zip(pred_dates, forecast)
            ],
        }
        metric_report.update(predictions)
        
        # Seasonality info
        if result.get("seasonality"):
            metric_report["seasonality"] = result["seasonality"]
        
        # Period comparison
        if prev_kpi_df is not None and not prev_kpi_df.empty and info["col"] in prev_kpi_df.columns:
            prev_total = int(pd.to_numeric(prev_kpi_df[info["col"]], errors="coerce").fillna(0).sum())
            curr_total = int(np.sum(values))
            change = ((curr_total - prev_total) / prev_total * 100) if prev_total > 0 else 0
            metric_report["prev_period_total"] = prev_total
            metric_report["period_change_pct"] = round(change, 1)
        
        report["metrics"][key] = metric_report
    
    return report


def format_forecast_report(report: dict) -> str:
    """Format forecast report as readable markdown."""
    lines = [f"## 🔮 Forecast Report — {report['generated_at']}"]
    lines.append(f"**Prediction horizon:** {report['horizon_days']} days\n")
    lines.append("> **Note:** Current Period Total = REAL data from your KPI pipeline. Predicted values = ML FORECASTS.\n")
    
    for key, data in report["metrics"].items():
        lines.append(f"### {data['name']}")
        
        if data.get("status") == "insufficient_data":
            lines.append(f"⚠️ {data.get('message', 'Insufficient data')}\n")
            continue
        
        lines.append(f"- **Current Period Total (REAL DATA):** {data['current_total']}")
        lines.append(f"- **Average Daily:** {data['avg_daily']}")
        lines.append(f"- **Trend:** {data['trend']}")
        lines.append(f"- **Confidence:** {data['confidence']} (CV: {data['cv']})")
        
        for h in [7, 14, 30]:
            pk = f"predicted_next_{h}d"
            bk = f"best_case_{h}d"
            wk = f"worst_case_{h}d"
            if pk in data:
                lines.append(f"- **Predicted Next {h} Days (FORECAST):** {data[pk]} (best: {data.get(bk, '?')}, worst: {data.get(wk, '?')})")
        
        if "period_change_pct" in data:
            emoji = "📈" if data["period_change_pct"] > 0 else "📉" if data["period_change_pct"] < 0 else "➡️"
            lines.append(f"- {emoji} **Period Change:** {data['period_change_pct']:+.1f}%")
        
        if data.get("seasonality"):
            lines.append(f"- **Seasonality:** Best on {data['seasonality']['best_day']}, worst on {data['seasonality']['worst_day']}")
        
        lines.append("")
    
    lines.append("---")
    lines.append("*Predictions by Eagle3D ML Engine — Ensemble of Moving Average, Linear Regression & Exponential Smoothing*")
    return "\n".join(lines)


def calculate_trend_indicator(values):
    """Returns trend analysis for a series of values."""
    if len(values) < 3:
        return {"direction": "unknown", "strength": 0, "momentum": 0}
    
    recent_3 = np.mean(values[-3:])
    recent_7 = np.mean(values[-7:]) if len(values) >= 7 else np.mean(values)
    older_7 = np.mean(values[-14:-7]) if len(values) >= 14 else recent_7
    
    short_term = recent_3 - recent_7
    long_term = recent_7 - older_7
    momentum = short_term / recent_7 if recent_7 > 0 else 0
    
    if momentum > 0.1:
        direction = "up"
    elif momentum < -0.1:
        direction = "down"
    else:
        direction = "stable"
    
    return {
        "direction": direction,
        "strength": abs(momentum),
        "momentum": round(momentum, 3),
        "short_avg": round(recent_3, 1),
        "long_avg": round(recent_7, 1),
    }
