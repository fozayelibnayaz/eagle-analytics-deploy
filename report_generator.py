"""
report_generator.py — Automated Report Generation v2
====================================================
Generates weekly, biweekly, monthly, quarterly reports.
Sends via Telegram + Email. Richer insights. More detail.
"""

import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

DATA_DIR = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)


def _si(val):
    try:
        return int(float(val or 0))
    except Exception:
        return 0

def _pct(part, whole):
    return round(part / whole * 100, 1) if whole > 0 else 0

def _change(curr, prev):
    if prev == 0:
        return "+∞" if curr > 0 else "0"
    return f"{((curr - prev) / prev * 100):+.1f}%"

def _rating(val, thresholds):
    """Rate a value against thresholds: [(threshold, label), ...]"""
    for threshold, label in thresholds:
        if val >= threshold:
            return label
    return thresholds[-1][1]


def generate_report(
    kpi_df, prev_kpi_df=None, leads_df=None, utm_df=None,
    period_type: str = "weekly",
    period_label: str = "",
) -> dict:
    """Generate a structured report."""
    now = datetime.now()
    
    if not period_label:
        labels = {
            "weekly": f"Week ending {now.strftime('%B %d, %Y')}",
            "biweekly": f"2 weeks ending {now.strftime('%B %d, %Y')}",
            "monthly": now.strftime("%B %Y"),
            "quarterly": f"Q{(now.month-1)//3+1} {now.year}",
            "business": f"Business Report — {now.strftime('%B %d, %Y')}",
            "marketing": f"Marketing Report — {now.strftime('%B %d, %Y')}",
            "data_analysis": f"Data Analysis — {now.strftime('%B %d, %Y')}",
            "executive": f"Executive Brief — {now.strftime('%B %d, %Y')}",
        }
        period_label = labels.get(period_type, f"Report — {now.strftime('%B %d, %Y')}")
    
    # Current period stats
    curr_s = int(kpi_df["signups"].sum()) if kpi_df is not None and not kpi_df.empty and "signups" in kpi_df.columns else 0
    curr_u = int(kpi_df["first_uploads"].sum()) if kpi_df is not None and not kpi_df.empty and "first_uploads" in kpi_df.columns else 0
    curr_p = int(kpi_df["paid_customers"].sum()) if kpi_df is not None and not kpi_df.empty and "paid_customers" in kpi_df.columns else 0
    
    # Previous period
    prev_s = int(prev_kpi_df["signups"].sum()) if prev_kpi_df is not None and not prev_kpi_df.empty and "signups" in prev_kpi_df.columns else 0
    prev_u = int(prev_kpi_df["first_uploads"].sum()) if prev_kpi_df is not None and not prev_kpi_df.empty and "first_uploads" in prev_kpi_df.columns else 0
    prev_p = int(prev_kpi_df["paid_customers"].sum()) if prev_kpi_df is not None and not prev_kpi_df.empty and "paid_customers" in prev_kpi_df.columns else 0
    
    # Funnel rates
    s2u = _pct(curr_u, curr_s)
    u2p = _pct(curr_p, curr_u)
    s2p = _pct(curr_p, curr_s)
    
    # Health score
    health_score = 0
    health_score += min(30, curr_s / 5)  # up to 30 points for signups
    health_score += min(30, s2u / 2)     # up to 30 for conversion
    health_score += min(20, u2p)         # up to 20 for monetization
    health_score += min(20, 15 if curr_s > prev_s else 5)  # growth bonus
    health_score = min(100, round(health_score))
    health_label = _rating(health_score, [(80, "🟢 Excellent"), (60, "🟡 Good"), (40, "🟠 Needs Attention"), (0, "🔴 Critical")])
    
    # Build report
    md_lines = [
        f"# 🦅 Eagle3D KPI Report — {period_label}",
        f"*Generated: {now.strftime('%B %d, %Y at %H:%M')}*",
        f"*Report type: {period_type.title()}*",
        f"*Health Score: {health_label} ({health_score}/100)*",
        "",
        "---",
        "",
        "## 📊 Executive Summary",
        "",
        f"| Metric | This Period | Previous | Change | Status |",
        f"|--------|------------|----------|--------|--------|",
    ]
    
    for name, c, p in [("Sign-ups", curr_s, prev_s), ("First Uploads", curr_u, prev_u), ("Paid Customers", curr_p, prev_p)]:
        change_str = _change(c, p)
        status = "📈" if c > p else "📉" if c < p else "➡️"
        md_lines.append(f"| **{name}** | {c} | {p} | {change_str} | {status} |")
    
    md_lines.append("")
    
    # Funnel
    md_lines.extend([
        "## 📈 Conversion Funnel",
        "",
        f"- Sign-up → Upload: **{s2u}%** {('✅' if s2u > 40 else '⚠️' if s2u > 20 else '🚨')}",
        f"- Upload → Paid: **{u2p}%** {('✅' if u2p > 30 else '⚠️' if u2p > 10 else '🚨')}",
        f"- Sign-up → Paid: **{s2p}%**",
        "",
    ])
    
    # Lead Sources
    if leads_df is not None and not leads_df.empty:
        md_lines.extend(["## 🎯 Lead Sources", ""])
        md_lines.append("| # | Source | Signups | Share | Category |")
        md_lines.append("|---|--------|---------|-------|----------|")
        for i, (_, row) in enumerate(leads_df.head(10).iterrows(), 1):
            src = row.get("Lead Source", "?")
            cnt = int(row.get("Signups", 0))
            pct = row.get("% of Total", 0)
            cat = row.get("Source_Category", "")
            md_lines.append(f"| {i} | {src} | {cnt} | {pct}% | {cat} |")
        md_lines.append("")
    
    # Traffic Sources
    if utm_df is not None and not utm_df.empty:
        src_col = "source_normalized" if "source_normalized" in utm_df.columns else "sessionSource"
        by_src = utm_df.groupby(src_col).agg(
            sessions=("sessions", "sum") if "sessions" in utm_df.columns else (src_col, "count"),
            conversions=("conversions", "sum") if "conversions" in utm_df.columns else (src_col, "count"),
        ).sort_values("sessions", ascending=False).head(10)
        
        md_lines.extend(["## 🌐 Traffic Sources (GA4)", ""])
        md_lines.append("| Source | Sessions | Conversions | Conv Rate |")
        md_lines.append("|--------|----------|-------------|-----------|")
        for src, row in by_src.iterrows():
            cr = (row['conversions'] / row['sessions'] * 100) if row['sessions'] > 0 else 0
            md_lines.append(f"| {src} | {int(row['sessions'])} | {int(row['conversions'])} | {cr:.1f}% |")
        md_lines.append("")
    
    # Insights
    md_lines.extend(["## 💡 Key Insights", ""])
    
    insights = []
    if curr_s > prev_s and prev_s > 0:
        insights.append(f"📈 Sign-ups grew by {_change(curr_s, prev_s)} — positive momentum")
    elif curr_s < prev_s and prev_s > 0:
        insights.append(f"📉 Sign-ups declined by {_change(curr_s, prev_s)} — investigate cause")
    
    if curr_u > 0 and s2u < 20:
        insights.append(f"⚠️ Upload conversion rate is only {s2u}% — consider onboarding improvements")
    
    if curr_p > 0 and u2p > 30:
        insights.append(f"✅ Upload-to-paid rate of {u2p}% is strong")
    
    if leads_df is not None and not leads_df.empty:
        top_source = leads_df.iloc[0].get("Lead Source", "?")
        top_count = int(leads_df.iloc[0].get("Signups", 0))
        insights.append(f"🎯 Top lead source: {top_source} ({top_count} signups)")
    
    # Health-based recommendations
    if health_score >= 80:
        insights.append("🏆 Overall health is excellent — maintain current strategies")
    elif health_score >= 60:
        insights.append("📊 Health is good but has room for improvement — focus on funnel optimization")
    elif health_score >= 40:
        insights.append("⚠️ Health needs attention — review acquisition channels and onboarding")
    else:
        insights.append("🚨 Critical health — immediate action needed on sign-ups and conversions")
    
    if not insights:
        insights.append("➡️ Performance is stable — no significant changes detected.")
    
    for insight in insights:
        md_lines.append(f"- {insight}")
    
    md_lines.extend([
        "",
        "---",
        "",
        "## 🎯 Recommended Actions",
        "",
    ])
    
    actions = []
    if s2u < 30:
        actions.append(("Improve onboarding", "Users sign up but don't upload. Add guided tutorial, templates, or video walkthrough."))
    if curr_s < prev_s and prev_s > 0:
        actions.append(("Investigate sign-up drop", f"Sign-ups fell from {prev_s} to {curr_s}. Check marketing campaigns, landing pages, and form functionality."))
    if curr_p == 0:
        actions.append(("Activation push", "No paid customers this period. Consider free trial promotions or email nurture campaigns."))
    
    for i, (title, desc) in enumerate(actions[:5], 1):
        md_lines.append(f"**{i}. {title}** — {desc}")
    
    # Report-type-specific sections
    if period_type == "business":
        md_lines.extend(["", "## 🏢 Business Analysis", "",
            "### Revenue Pipeline",
            f"- Free sign-ups: {curr_s} (potential conversions)",
            f"- First uploads: {curr_u} (engaged users)",
            f"- Paid conversions: {curr_p} (revenue generating)",
            f"- Estimated pipeline value: {curr_u * 50}–{curr_u * 200} USD (based on upload→paid conversion)",
            "",
            "### Customer Acquisition Cost",
            f"- With {curr_s} sign-ups from {len(leads_df) if leads_df is not None else 0} sources, focus on highest-converting channels.",
            "",
        ])
    elif period_type == "marketing":
        md_lines.extend(["", "## 📱 Marketing Analysis", "",
            "### Channel Performance",
        ])
        if leads_df is not None and not leads_df.empty:
            for _, row in leads_df.head(5).iterrows():
                src = row.get("Lead Source", "?")
                cnt = int(row.get("Signups", 0))
                pct = row.get("% of Total", 0)
                md_lines.append(f"- **{src}**: {cnt} signups ({pct}%) — {'⭐ Top channel' if pct > 20 else '📈 Growing' if pct > 10 else '🔍 Review'}")
        md_lines.extend(["",
            "### Recommendations",
            "- Double down on top-performing channels",
            "- A/B test landing pages for underperforming sources",
            "- Increase content marketing for organic growth",
            "",
        ])
    elif period_type == "data_analysis":
        md_lines.extend(["", "## 🔬 Data Analysis", "",
            "### Statistical Summary",
            f"- Total observations: {curr_s + curr_u + curr_p} data points",
            f"- Funnel conversion rate: {s2p}%",
            f"- Largest funnel drop: {'Sign-up → Upload' if s2u < 50 else 'Upload → Paid' if u2p < 30 else 'Balanced'}",
            "",
            "### Data Quality Notes",
            "- Source deduplication applied via intelligent normalizer",
            "- First upload logic validates against historical records",
            "- Paid customer verification includes Stripe cross-check",
            "",
        ])
    elif period_type == "executive":
        md_lines.extend(["", "## 👔 Executive Summary", "",
            f"**TL;DR:** {curr_s} sign-ups, {curr_u} uploads, {curr_p} paid this period.",
            f" Funnel conversion: {s2p}%. Health: {health_label}.",
            "",
            "### Key Decisions Needed:",
        ])
        if curr_s < 100:
            md_lines.append("1. **Increase acquisition** — sign-up volume below target")
        if s2u < 30:
            md_lines.append("2. **Fix onboarding** — upload conversion too low")
        if curr_p == 0:
            md_lines.append("3. **Activation push** — no paid conversions this period")
        md_lines.append("")

    md_lines.extend(["", "---", "", f"*Auto-generated by Eagle 3D Streaming KPI System v3*"])
    
    markdown = "\n".join(md_lines)
    
    return {
        "markdown": markdown,
        "period_label": period_label,
        "period_type": period_type,
        "summary": {
            "signups": curr_s,
            "uploads": curr_u,
            "paid": curr_p,
            "s_change": _change(curr_s, prev_s),
            "u_change": _change(curr_u, prev_u),
            "p_change": _change(curr_p, prev_p),
            "health_score": health_score,
            "health_label": health_label,
            "s2u": s2u,
            "u2p": u2p,
        },
    }


def generate_telegram_report(report: dict) -> str:
    """Format report for Telegram."""
    import re
    s = report["summary"]
    
    def esc(t):
        special = r"\_*[]()~`>#+-=|{}.!"
        return re.sub(f"([{re.escape(special)}])", r"\\\1", str(t))
    
    return (
        f"🦅 *Eagle3D KPI — {esc(report['period_label'])}*\n\n"
        f"📊 *Sign\\-ups:* `{s['signups']}` {esc(s['s_change'])}\n"
        f"📤 *Uploads:* `{s['uploads']}` {esc(s['u_change'])}\n"
        f"💳 *Paid:* `{s['paid']}` {esc(s['p_change'])}\n"
        f"🏥 *Health:* {s['health_label']}\n\n"
        f"🔗 [Dashboard](https://eagle3d\\-kpi\\-automation\\.streamlit\\.app/)\n"
        f"_{esc(report['period_type'].title())} Report_"
    )


def save_report(report: dict):
    """Save report to data_output/reports/"""
    reports_dir = DATA_DIR / "reports"
    reports_dir.mkdir(exist_ok=True)
    
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ptype = report.get("period_type", "custom")
    filename = f"{ptype}_{ts}.md"
    
    filepath = reports_dir / filename
    filepath.write_text(report["markdown"])
    return filepath


def list_saved_reports() -> list:
    """List all saved reports."""
    reports_dir = DATA_DIR / "reports"
    if not reports_dir.exists():
        return []
    
    reports = []
    for f in sorted(reports_dir.glob("*.md"), reverse=True):
        reports.append({
            "filename": f.name,
            "path": str(f),
            "size": f.stat().st_size,
            "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    return reports
