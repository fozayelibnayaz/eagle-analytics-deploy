"""
attribution_tracker.py — Eagle 3D Streaming Analytics Hub
============================================================
Tracks traffic source (lead_source) per KPI event:
  - signups by source
  - uploads by source (inherits from matching signup)
  - paying customers by source (inherits from matching signup)

Sources are normalized (google/Google/GOOGLE → google).
Reports daily/weekly/monthly breakdowns for alerts + dashboard.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List

from mongo_client import find_all, find_one


# ─── Source normalization ───────────────────────────────────────
_SOURCE_ALIASES = {
    "google": ["google", "Google", "GOOGLE", "google search", "Google Search",
                "google.com", "search"],
    "linkedin": ["linkedin", "LinkedIn", "LINKEDIN", "linkedin.com"],
    "youtube": ["youtube", "YouTube", "YOUTUBE", "youtube.com", "yt"],
    "chatgpt": ["chatgpt", "ChatGPT", "chat gpt", "Chat GPT", "chatgpt.com",
                 "openai"],
    "claude": ["claude", "Claude", "claude.ai", "claude reccomendation",
                "claude recommendation"],
    "reddit": ["reddit", "Reddit", "REDDIT", "reddit.com", "r/"],
    "twitter": ["twitter", "Twitter", "x.com", "X"],
    "facebook": ["facebook", "Facebook", "fb", "meta"],
    "instagram": ["instagram", "Instagram", "IG"],
    "bing": ["bing", "Bing"],
    "direct": ["direct", "Direct", "(direct)", "(none)", "typed"],
    "referral": ["referral", "Referral"],
    "friend": ["friend", "Friend", "friend recommendation", "colleague"],
    "email": ["email", "Email", "newsletter"],
    "ai": ["ai", "AI", "ai tools", "AI Tools", "artificial intelligence"],
    "trust": ["trust", "Trst", "Trust"],
    "other": ["other", "Other", "OTHER", "Othe"],
    "unknown": ["", "unknown", "Unknown", "n/a", "N/A", "-", "none"],
}


def normalize_source(raw: str) -> str:
    if not raw:
        return "unknown"
    raw = str(raw).strip().lower()
    if not raw:
        return "unknown"
    for canonical, aliases in _SOURCE_ALIASES.items():
        if any(raw == a.lower() or a.lower() in raw for a in aliases):
            return canonical
    return raw  # keep the original if not aliased


# ─── Aggregation ────────────────────────────────────────────────
def signups_by_source(start_iso: str, end_iso: str) -> Dict[str, int]:
    rows = find_all("signups", filters={
        "final_status": "ACCEPTED",
        "signup_date":  {"$gte": start_iso, "$lte": end_iso},
    }, projection={"lead_source": 1})
    out: Dict[str, int] = defaultdict(int)
    for r in rows:
        out[normalize_source(r.get("lead_source", ""))] += 1
    return dict(sorted(out.items(), key=lambda x: -x[1]))


def uploads_by_source(start_iso: str, end_iso: str) -> Dict[str, int]:
    """Uploads inherit source from their matching signup."""
    rows = find_all("uploads", filters={
        "final_status": "ACCEPTED",
        "upload_date":  {"$gte": start_iso, "$lte": end_iso},
    }, projection={"signup_lead_source": 1, "email_normalized": 1})
    out: Dict[str, int] = defaultdict(int)
    for r in rows:
        src = r.get("signup_lead_source", "")
        if not src:
            # Fallback: look up signup manually
            s = find_one("signups", {
                "email_normalized": r.get("email_normalized"),
                "final_status":     "ACCEPTED",
            }, projection={"lead_source": 1})
            src = s.get("lead_source", "") if s else ""
        out[normalize_source(src)] += 1
    return dict(sorted(out.items(), key=lambda x: -x[1]))


def payments_by_source(start_iso: str, end_iso: str,
                        new_customers_only: bool = True) -> Dict[str, int]:
    """Paying customers inherit source from matching signup."""
    f = {
        "final_status": "ACCEPTED",
        "first_payment_date": {"$gte": start_iso, "$lte": end_iso},
    }
    if new_customers_only:
        f["customer_type"] = "NEW_CUSTOMER"
    rows = find_all("payments", filters=f,
                     projection={"email_normalized": 1})
    out: Dict[str, int] = defaultdict(int)
    for r in rows:
        s = find_one("signups", {
            "email_normalized": r.get("email_normalized"),
            "final_status":     "ACCEPTED",
        }, projection={"lead_source": 1})
        src = s.get("lead_source", "") if s else ""
        out[normalize_source(src)] += 1
    return dict(sorted(out.items(), key=lambda x: -x[1]))


def revenue_by_source(start_iso: str, end_iso: str,
                       new_customers_only: bool = False) -> Dict[str, float]:
    f = {
        "final_status": "ACCEPTED",
        "first_payment_date": {"$gte": start_iso, "$lte": end_iso},
    }
    if new_customers_only:
        f["customer_type"] = "NEW_CUSTOMER"
    rows = find_all("payments", filters=f,
                     projection={"email_normalized": 1, "total_spend": 1})
    out: Dict[str, float] = defaultdict(float)
    for r in rows:
        s = find_one("signups", {
            "email_normalized": r.get("email_normalized"),
            "final_status":     "ACCEPTED",
        }, projection={"lead_source": 1})
        src = s.get("lead_source", "") if s else ""
        out[normalize_source(src)] += float(r.get("total_spend", 0) or 0)
    return dict(sorted(out.items(), key=lambda x: -x[1]))


# ─── Composite report ───────────────────────────────────────────
def daily_attribution_report(days_back: int = 1) -> Dict[str, Any]:
    """Full attribution snapshot for the last N days."""
    end = date.today()
    start = end - timedelta(days=days_back - 1) if days_back > 0 else end
    s_iso, e_iso = start.isoformat(), end.isoformat()

    return {
        "period":         f"{s_iso} → {e_iso}",
        "days":           days_back,
        "signups":        signups_by_source(s_iso, e_iso),
        "uploads":        uploads_by_source(s_iso, e_iso),
        "new_paying":     payments_by_source(s_iso, e_iso, new_customers_only=True),
        "total_revenue":  revenue_by_source(s_iso, e_iso, new_customers_only=False),
        "new_cust_revenue": revenue_by_source(s_iso, e_iso, new_customers_only=True),
    }


# ─── Alert builder ──────────────────────────────────────────────
def build_attribution_alert(days_back: int = 1) -> str:
    r = daily_attribution_report(days_back)
    lines = [
        f"🎯 *TRAFFIC SOURCE ATTRIBUTION*",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        f"Period: {r['period']} ({r['days']} day{'s' if r['days']>1 else ''})",
        "",
    ]

    # Signups
    total_s = sum(r["signups"].values())
    lines.append(f"👥 *Sign-ups: {total_s} total*")
    if r["signups"]:
        for src, n in list(r["signups"].items())[:6]:
            pct = round(n / total_s * 100, 1) if total_s else 0
            lines.append(f"   • {src}: {n} ({pct}%)")
    else:
        lines.append("   (none)")

    # Uploads
    lines.append("")
    total_u = sum(r["uploads"].values())
    lines.append(f"�� *First Uploads: {total_u} total*")
    if r["uploads"]:
        for src, n in list(r["uploads"].items())[:6]:
            pct = round(n / total_u * 100, 1) if total_u else 0
            lines.append(f"   • {src}: {n} ({pct}%)")
    else:
        lines.append("   (none)")

    # New paying customers
    lines.append("")
    total_p = sum(r["new_paying"].values())
    lines.append(f"💳 *New Paying Customers: {total_p} total*")
    if r["new_paying"]:
        for src, n in list(r["new_paying"].items())[:6]:
            pct = round(n / total_p * 100, 1) if total_p else 0
            lines.append(f"   • {src}: {n} ({pct}%)")
    else:
        lines.append("   (none)")

    # Revenue split
    lines.append("")
    total_rev = sum(r["total_revenue"].values())
    new_rev = sum(r["new_cust_revenue"].values())
    rec_rev = total_rev - new_rev
    lines.append(f"💰 *Revenue Breakdown*")
    lines.append(f"   Total: ${total_rev:,.2f}")
    lines.append(f"      New customers:  ${new_rev:,.2f}")
    lines.append(f"      Recurring:      ${rec_rev:,.2f}")
    if r["total_revenue"]:
        lines.append(f"   *Top source by $:*")
        for src, amt in list(r["total_revenue"].items())[:3]:
            lines.append(f"      {src}: ${amt:,.2f}")

    from datetime import datetime
    lines.append("")
    lines.append(f"⏰ {datetime.now().strftime('%b %d, %Y %I:%M %p')}")

    return "\n".join(lines)


def send_attribution_alert(days_back: int = 1) -> bool:
    try:
        from reporting_engine import send_telegram
        msg = build_attribution_alert(days_back)
        return bool(send_telegram(msg))
    except Exception as e:
        print(f"[attribution] alert send failed: {e}")
        return False


# ─── CLI ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    print("Testing attribution tracker...")
    print()
    for days in [1, 7, 30]:
        r = daily_attribution_report(days)
        print(f"── Last {days} day{'s' if days>1 else ''} ──")
        print(json.dumps(r, indent=2, default=str))
        print()

    print("\n═ Sending attribution alert to Telegram ═")
    ok = send_attribution_alert(7)
    print("Sent!" if ok else "Failed")
