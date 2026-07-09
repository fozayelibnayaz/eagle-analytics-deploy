"""
rich_alerts_engine.py — Eagle 3D Streaming Analytics Hub
==========================================================
Generates rich per-system alerts matching AI-YouTube-Command-Center style:
  - Daily summary cards
  - Anomaly alerts (spikes, drops, flatlines)
  - Per-item alerts (dead videos, viral posts, top signups)
  - Health scores

Each alert has: icon, title, subtitle, bullet details, timestamp.
Sends to Telegram in nicely formatted blocks.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from mongo_client import count_accepted, count_docs, find_all, find_one


# ─── Alert formatting ────────────────────────────────────────────
def _now_str() -> str:
    return datetime.now().strftime("%b %-d, %Y, %-I:%M %p")


def _format_alert(icon: str, level: str, title: str,
                  subtitle: str, details: Dict[str, Any],
                  audience: Optional[str] = None) -> str:
    """
    Format a single alert card matching the Next.js YT-Command style.
    level: 'info' | 'warn' | 'success' | 'danger'
    """
    level_icons = {"info": "ℹ️", "warn": "⚠️",
                    "success": "✅", "danger": "🚨"}
    lvl_icon = level_icons.get(level, "ℹ️")

    lines = [
        f"{lvl_icon} {icon} *{title}*",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        subtitle,
        "",
        "📋 *Details*",
    ]
    for k, v in details.items():
        lines.append(f"  • {k}: {v}")

    lines.append("")
    footer = f"⏰ {_now_str()}"
    if audience:
        footer += f" | 👥 {audience}"
    lines.append(footer)

    return "\n".join(lines)


def _send(alert: str) -> bool:
    try:
        from reporting_engine import send_telegram
        return bool(send_telegram(alert))
    except Exception as e:
        print(f"[rich_alerts] send failed: {e}")
        return False


# ─── KPI ALERTS ──────────────────────────────────────────────────
def build_kpi_daily_summary() -> str:
    today = date.today()
    month_start = today.replace(day=1).isoformat()
    week_ago = (today - timedelta(days=7)).isoformat()
    today_iso = today.isoformat()
    yesterday_iso = (today - timedelta(days=1)).isoformat()

    # Counts
    sign_today = count_accepted("signups", "signup_date",
                                 date_gte=today_iso, date_lte=today_iso)
    sign_yesterday = count_accepted("signups", "signup_date",
                                     date_gte=yesterday_iso, date_lte=yesterday_iso)
    sign_week = count_accepted("signups", "signup_date",
                                date_gte=week_ago, date_lte=today_iso)
    sign_month = count_accepted("signups", "signup_date",
                                 date_gte=month_start, date_lte=today_iso)
    sign_total = count_accepted("signups", "signup_date")

    up_today = count_accepted("uploads", "upload_date",
                               date_gte=today_iso, date_lte=today_iso)
    up_week = count_accepted("uploads", "upload_date",
                              date_gte=week_ago, date_lte=today_iso)
    up_month = count_accepted("uploads", "upload_date",
                               date_gte=month_start, date_lte=today_iso)

    pay_today = count_accepted("payments", "first_payment_date",
                                date_gte=today_iso, date_lte=today_iso)
    pay_week = count_accepted("payments", "first_payment_date",
                               date_gte=week_ago, date_lte=today_iso)
    pay_month = count_accepted("payments", "first_payment_date",
                                date_gte=month_start, date_lte=today_iso)

    # Rejected (spam quality)
    sign_rej_today = count_docs("signups", {
        "final_status": "REJECTED",
        "signup_date": {"$gte": today_iso, "$lte": today_iso},
    })

    # Conversion rates
    conv_su = round(up_month / sign_month * 100, 1) if sign_month else 0
    conv_sp = round(pay_month / sign_month * 100, 1) if sign_month else 0

    # Health
    if sign_month > 50 and conv_sp > 5:
        health = "🟢 Healthy"
    elif sign_month > 20:
        health = "🟡 Ok"
    else:
        health = "🟠 Needs Work"

    return _format_alert(
        icon="📊",
        level="info",
        title="KPI DAILY SUMMARY",
        subtitle=f"Sign-ups, uploads & paying — {today.strftime('%A, %B %-d')}",
        details={
            "Sign-ups (today)":     f"{sign_today} (yesterday: {sign_yesterday})",
            "Sign-ups (7d)":         f"{sign_week}",
            "Sign-ups (MTD)":        f"{sign_month}",
            "Sign-ups (all time)":   f"{sign_total:,}",
            "Uploads (today/7d/MTD)": f"{up_today} / {up_week} / {up_month}",
            "Paid (today/7d/MTD)":    f"{pay_today} / {pay_week} / {pay_month}",
            "Rejected today":         f"{sign_rej_today}",
            "Sign→Upload rate":       f"{conv_su}%",
            "Sign→Paid rate":         f"{conv_sp}%",
            "Health":                 health,
        },
        audience="KPI team",
    )


def build_kpi_spike_alerts() -> List[str]:
    """Detect signup spikes/drops per source."""
    alerts = []
    today = date.today()
    week_ago = (today - timedelta(days=7)).isoformat()
    prev_week = (today - timedelta(days=14)).isoformat()
    today_iso = today.isoformat()

    # Group signups by lead_source last 7 days vs previous 7
    rows_cur = find_all("signups", filters={
        "final_status": "ACCEPTED",
        "signup_date":  {"$gte": week_ago, "$lte": today_iso},
    }, projection={"lead_source": 1})
    rows_prev = find_all("signups", filters={
        "final_status": "ACCEPTED",
        "signup_date":  {"$gte": prev_week, "$lte": week_ago},
    }, projection={"lead_source": 1})

    cur_by_source: Dict[str, int] = {}
    prev_by_source: Dict[str, int] = {}
    for r in rows_cur:
        src = (r.get("lead_source") or "Unknown").strip().lower() or "unknown"
        cur_by_source[src] = cur_by_source.get(src, 0) + 1
    for r in rows_prev:
        src = (r.get("lead_source") or "Unknown").strip().lower() or "unknown"
        prev_by_source[src] = prev_by_source.get(src, 0) + 1

    all_sources = set(cur_by_source) | set(prev_by_source)
    for src in all_sources:
        c = cur_by_source.get(src, 0)
        p = prev_by_source.get(src, 0)
        if p >= 3 and c >= p * 2:
            alerts.append(_format_alert(
                icon="📈",
                level="success",
                title="SIGNUP SPIKE",
                subtitle=f"'{src}' signups doubled: {c} vs {p} (prev 7d)",
                details={
                    "Source":       src,
                    "This 7d":      c,
                    "Previous 7d":  p,
                    "Change":       f"+{c-p} ({(c-p)/p*100:.0f}%)",
                },
            ))
        elif p >= 5 and c <= p * 0.3:
            alerts.append(_format_alert(
                icon="📉",
                level="warn",
                title="SIGNUP DROP",
                subtitle=f"'{src}' signups collapsed: {c} vs {p} (prev 7d)",
                details={
                    "Source":       src,
                    "This 7d":      c,
                    "Previous 7d":  p,
                    "Change":       f"{c-p} ({(c-p)/p*100:.0f}%)",
                },
            ))
    return alerts


# ─── YOUTUBE ALERTS ──────────────────────────────────────────────
def build_youtube_daily_summary() -> Optional[str]:
    ch = find_one("youtube_channel", {})
    videos = find_all("youtube_videos", limit=1000)
    if not ch or not videos:
        return None

    total_views = sum(int(v.get("views", 0) or 0) for v in videos)
    total_likes = sum(int(v.get("likes", 0) or 0) for v in videos)
    total_comments = sum(int(v.get("comments", 0) or 0) for v in videos)
    active = sum(1 for v in videos if int(v.get("views", 0) or 0) > 0)
    dead = sum(1 for v in videos
                if int(v.get("views", 0) or 0) < 50
                and v.get("published_at", "")[:10] < (date.today() - timedelta(days=30)).isoformat())

    avg_eng = 0
    if total_views:
        avg_eng = round((total_likes + total_comments) / total_views * 100, 2)

    # Most engaged
    def _score(v):
        views = int(v.get("views", 0) or 0)
        likes = int(v.get("likes", 0) or 0)
        comments = int(v.get("comments", 0) or 0)
        return (likes + comments) / views if views else 0

    most_eng = max(videos, key=_score, default={})
    most_eng_title = str(most_eng.get("title", "N/A"))[:50]

    # Uploads in last N days
    now = datetime.now()
    def _uploaded_in(days):
        cutoff = (now - timedelta(days=days)).isoformat()
        return sum(1 for v in videos
                    if str(v.get("published_at", "")) >= cutoff)

    if avg_eng >= 4:
        health = "🟢 Excellent"
    elif avg_eng >= 2:
        health = "🟡 Ok"
    else:
        health = "🟠 Needs Work"

    return _format_alert(
        icon="📺",
        level="info",
        title="YOUTUBE DAILY SUMMARY",
        subtitle=f"Full channel snapshot — {date.today().strftime('%A, %B %-d')}",
        details={
            "Channel":            ch.get("title", "?"),
            "Total Videos":       len(videos),
            "Active Videos":      active,
            "Total Views":        f"{total_views:,}",
            "Total Likes":        f"{total_likes:,}",
            "Total Comments":     f"{total_comments:,}",
            "Subscribers":        f"{int(ch.get('subscribers', 0) or 0):,}",
            "Avg Engagement":     f"{avg_eng}%",
            "Channel Health":     health,
            "Uploads (24h)":       _uploaded_in(1),
            "Uploads (7d)":        _uploaded_in(7),
            "Uploads (30d)":       _uploaded_in(30),
            "Dead Videos":        dead,
            "Most Engaged":       most_eng_title,
        },
        audience="Content team",
    )


def build_youtube_dead_video_alerts(max_alerts: int = 5) -> List[str]:
    """Alert on videos with < 1 view/day after 90+ days."""
    videos = find_all("youtube_videos", limit=1000)
    if not videos:
        return []

    alerts = []
    today = datetime.now()

    scored = []
    for v in videos:
        try:
            pub = datetime.fromisoformat(str(v.get("published_at", ""))[:19].replace("Z", ""))
        except Exception:
            continue
        age_days = (today - pub).days
        if age_days < 90:
            continue
        views = int(v.get("views", 0) or 0)
        vpd = views / age_days if age_days else 0
        if vpd < 1.0:
            scored.append((vpd, age_days, views, v))

    # Sort by lowest views/day (worst first)
    scored.sort(key=lambda x: x[0])

    for vpd, age, views, v in scored[:max_alerts]:
        alerts.append(_format_alert(
            icon="🪦",
            level="warn",
            title="DEAD VIDEO",
            subtitle=f"Dead video: {vpd:.2f} views/day after {age} days",
            details={
                "Video":     str(v.get("title", ""))[:60],
                "Views/Day": f"{vpd:.2f}",
                "Age":       f"{age} days",
                "Views":     f"{views:,}",
            },
        ))
    return alerts


# ─── LINKEDIN ALERTS ─────────────────────────────────────────────
def build_linkedin_daily_summary() -> Optional[str]:
    hl_rows = find_all("linkedin_highlights_daily",
                        sort=[("snapshot_date", -1)], limit=1)
    if not hl_rows:
        return None
    hl = hl_rows[0]

    posts = find_all("linkedin_posts", limit=200)
    if posts:
        total_imp = sum(int(p.get("impressions", 0) or 0) for p in posts)
        total_react = sum(int(p.get("reactions", 0) or 0) for p in posts)
    else:
        total_imp = int(hl.get("impressions", 0) or 0)
        total_react = int(hl.get("reactions", 0) or 0)

    return _format_alert(
        icon="💼",
        level="info",
        title="LINKEDIN DAILY SUMMARY",
        subtitle=f"Company page snapshot — {date.today().strftime('%A, %B %-d')}",
        details={
            "Total Followers":   f"{int(hl.get('total_followers', 0) or 0):,}",
            "Page Views (30d)":  f"{int(hl.get('page_views', 0) or 0):,}",
            "Unique Visitors":   f"{int(hl.get('unique_visitors', 0) or 0):,}",
            "Total Posts":       len(posts) if posts else 0,
            "Total Impressions": f"{total_imp:,}",
            "Total Reactions":   f"{total_react:,}",
            "Newsletter Subs":   f"{int(hl.get('newsletter_subscribers', 0) or 0):,}",
        },
        audience="Marketing team",
    )


def build_linkedin_viral_post_alerts(max_alerts: int = 3) -> List[str]:
    posts = find_all("linkedin_posts", sort=[("impressions", -1)], limit=50)
    if not posts:
        return []
    avg_imp = sum(int(p.get("impressions", 0) or 0) for p in posts) / len(posts)

    alerts = []
    for p in posts[:max_alerts]:
        imp = int(p.get("impressions", 0) or 0)
        if imp >= avg_imp * 3 and imp >= 500:
            alerts.append(_format_alert(
                icon="🔥",
                level="success",
                title="VIRAL LINKEDIN POST",
                subtitle=f"Post {imp:,} impressions ({imp/avg_imp:.1f}x avg)",
                details={
                    "Impressions":  f"{imp:,}",
                    "Reactions":    p.get("reactions", 0),
                    "Comments":     p.get("comments", 0),
                    "Published":    str(p.get("published_at", ""))[:10],
                    "Post URN":     str(p.get("post_urn", ""))[-16:],
                },
            ))
    return alerts


# ─── GA4 / TRAFFIC ALERTS ────────────────────────────────────────
def build_ga4_daily_summary() -> Optional[str]:
    try:
        from pathlib import Path
        import json
        cache = Path("data_output/ga4_traffic_cache.json")
        if not cache.exists():
            return None
        d = json.loads(cache.read_text())

        details = {
            "Total Sessions": f"{d.get('total_sessions', 0):,}",
            "Total Users":    f"{d.get('total_users', 0):,}",
            "Cache Age":      d.get("scraped_at", "?")[:19],
        }
        for i, (src, sess) in enumerate(d.get("top_sources", [])[:5]):
            details[f"Top #{i+1} Source"] = f"{src} ({sess:,} sess)"
        for i, (c, sess) in enumerate(d.get("top_countries", [])[:5]):
            details[f"Top #{i+1} Country"] = f"{c} ({sess:,} sess)"

        return _format_alert(
            icon="🌐",
            level="info",
            title="GA4 TRAFFIC SUMMARY",
            subtitle=f"Website traffic — {date.today().strftime('%A, %B %-d')}",
            details=details,
            audience="Marketing team",
        )
    except Exception:
        return None


# ─── CUSTOMER SUCCESS ALERTS ─────────────────────────────────────
def build_cs_daily_summary() -> Optional[str]:
    total_master = count_docs("customer_success_master")
    total_enriched = count_docs("customer_success_enriched")
    if total_master == 0:
        return None

    return _format_alert(
        icon="🎯",
        level="info",
        title="CUSTOMER SUCCESS SUMMARY",
        subtitle=f"CS snapshot — {date.today().strftime('%A, %B %-d')}",
        details={
            "Master rows":    f"{total_master:,}",
            "Enriched rows":  f"{total_enriched:,}",
        },
        audience="CS team",
    )




# ═════════════════════════════════════════════════════════════════
# EXTENDED ALERTS — Best/Worst/Dead across every system
# ═════════════════════════════════════════════════════════════════

# ─── KPI: best/worst signup sources ──────────────────────────────
def build_kpi_top_source_alert() -> Optional[str]:
    """Top signup source in last 30 days."""
    today = date.today()
    start = (today - timedelta(days=30)).isoformat()
    end   = today.isoformat()
    rows = find_all("signups", filters={
        "final_status": "ACCEPTED",
        "signup_date":  {"$gte": start, "$lte": end},
    }, projection={"lead_source": 1})
    if not rows:
        return None
    by_src: Dict[str, int] = {}
    for r in rows:
        s = (r.get("lead_source") or "Unknown").strip() or "Unknown"
        by_src[s] = by_src.get(s, 0) + 1
    ranked = sorted(by_src.items(), key=lambda x: -x[1])
    top5 = ranked[:5]
    if not top5:
        return None
    details = {"Total signups (30d)": sum(by_src.values())}
    for i, (src, cnt) in enumerate(top5, 1):
        pct = round(cnt / sum(by_src.values()) * 100, 1)
        details[f"#{i} {src}"] = f"{cnt} signups ({pct}%)"
    return _format_alert(
        icon="🏆",
        level="success",
        title="TOP SIGNUP SOURCES (30d)",
        subtitle=f"Best-performing acquisition channels",
        details=details,
        audience="Growth team",
    )


def build_kpi_cold_source_alert() -> Optional[str]:
    """Sources that used to bring signups but are dead now."""
    today = date.today()
    prev_start = (today - timedelta(days=60)).isoformat()
    prev_end   = (today - timedelta(days=30)).isoformat()
    cur_start  = (today - timedelta(days=30)).isoformat()
    end        = today.isoformat()

    def _group(start, end_):
        rows = find_all("signups", filters={
            "final_status": "ACCEPTED",
            "signup_date":  {"$gte": start, "$lte": end_},
        }, projection={"lead_source": 1})
        by: Dict[str, int] = {}
        for r in rows:
            s = (r.get("lead_source") or "Unknown").strip() or "Unknown"
            by[s] = by.get(s, 0) + 1
        return by

    prev = _group(prev_start, prev_end)
    cur  = _group(cur_start, end)

    cold = []
    for src, prv_cnt in prev.items():
        cur_cnt = cur.get(src, 0)
        if prv_cnt >= 3 and cur_cnt == 0:
            cold.append((src, prv_cnt))

    if not cold:
        return None
    cold.sort(key=lambda x: -x[1])
    details = {}
    for src, prv_cnt in cold[:10]:
        details[src] = f"was {prv_cnt}, now 0"
    return _format_alert(
        icon="❄️",
        level="warn",
        title="COLD SIGNUP SOURCES",
        subtitle=f"Sources that stopped bringing signups (60-30d ago → last 30d)",
        details=details,
        audience="Growth team",
    )


# ─── KPI: upload spikes/drops ────────────────────────────────────
def build_upload_trend_alert() -> Optional[str]:
    today = date.today()
    cur_start = (today - timedelta(days=7)).isoformat()
    prev_start = (today - timedelta(days=14)).isoformat()
    prev_end   = cur_start
    end = today.isoformat()

    cur = count_accepted("uploads", "upload_date",
                          date_gte=cur_start, date_lte=end)
    prv = count_accepted("uploads", "upload_date",
                          date_gte=prev_start, date_lte=prev_end)

    if prv == 0 and cur == 0:
        return None

    if prv >= 5 and cur >= prv * 1.5:
        return _format_alert(
            icon="🚀", level="success", title="UPLOAD SPIKE",
            subtitle=f"Uploads jumped: {cur} last 7d vs {prv} prior 7d",
            details={
                "Last 7d":   cur, "Prev 7d": prv,
                "Change":    f"+{cur-prv} ({(cur-prv)/prv*100:.0f}%)",
            },
        )
    if prv >= 5 and cur <= prv * 0.5:
        return _format_alert(
            icon="⚠️", level="warn", title="UPLOAD DROP",
            subtitle=f"Uploads down: {cur} last 7d vs {prv} prior 7d",
            details={
                "Last 7d":   cur, "Prev 7d": prv,
                "Change":    f"{cur-prv} ({(cur-prv)/prv*100:.0f}%)",
            },
        )
    return None


# ─── KPI: revenue spikes/drops ───────────────────────────────────
def build_revenue_trend_alert() -> Optional[str]:
    today = date.today()
    cur_start = (today - timedelta(days=7)).isoformat()
    prev_start = (today - timedelta(days=14)).isoformat()
    prev_end   = cur_start
    end = today.isoformat()

    def _rev(s, e):
        docs = find_all("payments", {
            "final_status": "ACCEPTED",
            "first_payment_date": {"$gte": s, "$lte": e},
        })
        return sum(float(p.get("total_spend", 0) or 0) for p in docs)

    cur = _rev(cur_start, end)
    prv = _rev(prev_start, prev_end)
    if prv == 0 and cur == 0:
        return None

    if prv >= 100 and cur >= prv * 1.5:
        return _format_alert(
            icon="💰", level="success", title="REVENUE SPIKE",
            subtitle=f"Revenue up: ${cur:,.0f} last 7d vs ${prv:,.0f} prior 7d",
            details={
                "Last 7d":   f"${cur:,.2f}", "Prev 7d": f"${prv:,.2f}",
                "Change":    f"+${cur-prv:,.0f} ({(cur-prv)/prv*100:.0f}%)",
            },
        )
    if prv >= 100 and cur <= prv * 0.5:
        return _format_alert(
            icon="🚨", level="danger", title="REVENUE DROP",
            subtitle=f"Revenue down: ${cur:,.0f} last 7d vs ${prv:,.0f} prior 7d",
            details={
                "Last 7d":   f"${cur:,.2f}", "Prev 7d": f"${prv:,.2f}",
                "Change":    f"${cur-prv:,.0f} ({(cur-prv)/prv*100:.0f}%)",
            },
        )
    return None


def build_top_paying_customers_alert() -> Optional[str]:
    """Top 5 paying customers in last 30 days."""
    today = date.today()
    start = (today - timedelta(days=30)).isoformat()
    end   = today.isoformat()
    rows = find_all("payments", {
        "final_status": "ACCEPTED",
        "first_payment_date": {"$gte": start, "$lte": end},
    }, sort=[("total_spend", -1)], limit=5)
    if not rows:
        return None
    details = {}
    for i, r in enumerate(rows, 1):
        email = str(r.get("email_normalized", "?"))[:35]
        spend = float(r.get("total_spend", 0) or 0)
        details[f"#{i} {email}"] = f"${spend:,.2f}"
    return _format_alert(
        icon="💎", level="success",
        title="TOP PAYING CUSTOMERS (30d)",
        subtitle="Highest-spending new paying customers",
        details=details,
        audience="Sales + CS team",
    )


# ─── GA4: traffic source spikes/drops ────────────────────────────
def build_ga4_source_trend_alert() -> List[str]:
    """Compare each GA4 source: last 7d vs prior 7d."""
    try:
        from ga4_connector import is_configured, fetch_utm_traffic
        if not is_configured():
            return []
    except Exception:
        return []

    today = date.today()
    cur_s = (today - timedelta(days=7)).isoformat()
    prv_s = (today - timedelta(days=14)).isoformat()
    prv_e = cur_s
    end   = today.isoformat()

    try:
        cur_df = fetch_utm_traffic(cur_s, end)
        prv_df = fetch_utm_traffic(prv_s, prv_e)
    except Exception:
        return []

    if cur_df.empty and prv_df.empty:
        return []

    import pandas as pd
    def _sum(df):
        if df.empty or "sourceMedium" not in df.columns:
            return {}
        return df.groupby("sourceMedium")["sessions"].sum().to_dict()

    cur_by = _sum(cur_df)
    prv_by = _sum(prv_df)

    alerts = []
    for src in set(cur_by) | set(prv_by):
        c = int(cur_by.get(src, 0))
        p = int(prv_by.get(src, 0))
        if p >= 100 and c >= p * 2:
            alerts.append(_format_alert(
                icon="📈", level="success", title="TRAFFIC SPIKE",
                subtitle=f"'{src}' doubled: {c:,} vs {p:,} sessions",
                details={
                    "Source": src, "Last 7d": f"{c:,}",
                    "Prev 7d": f"{p:,}",
                    "Change": f"+{c-p:,} ({(c-p)/p*100:.0f}%)",
                },
            ))
        elif p >= 100 and c <= p * 0.3:
            alerts.append(_format_alert(
                icon="📉", level="warn", title="TRAFFIC DROP",
                subtitle=f"'{src}' collapsed: {c:,} vs {p:,} sessions",
                details={
                    "Source": src, "Last 7d": f"{c:,}",
                    "Prev 7d": f"{p:,}",
                    "Change": f"{c-p:,} ({(c-p)/p*100:.0f}%)",
                },
            ))
    return alerts[:5]  # cap to 5


# ─── LinkedIn: dead posts ────────────────────────────────────────
def build_linkedin_dead_post_alerts() -> List[str]:
    """Posts published >30 days ago with < 100 impressions."""
    posts = find_all("linkedin_posts", limit=200)
    if not posts:
        return []
    alerts = []
    today = datetime.now()
    for p in posts:
        try:
            pub = datetime.fromisoformat(
                str(p.get("published_at", ""))[:19].replace("Z", ""))
        except Exception:
            continue
        age = (today - pub).days
        if age < 30:
            continue
        imp = int(p.get("impressions", 0) or 0)
        if imp < 100 and age >= 30:
            alerts.append((age, imp, p))
    # Sort worst first (lowest imp/day)
    alerts.sort(key=lambda x: x[1] / max(x[0], 1))
    out = []
    for age, imp, p in alerts[:3]:
        out.append(_format_alert(
            icon="🪦", level="warn", title="DEAD LINKEDIN POST",
            subtitle=f"Post: {imp} impressions after {age} days",
            details={
                "Impressions/day": f"{imp/age:.2f}",
                "Total impressions": imp,
                "Age": f"{age} days",
                "Reactions": p.get("reactions", 0),
                "Post URN": str(p.get("post_urn", ""))[-16:],
            },
        ))
    return out


# ─── YouTube: best videos ────────────────────────────────────────
def build_youtube_top_video_alert() -> Optional[str]:
    videos = find_all("youtube_videos", sort=[("views", -1)], limit=5)
    if not videos:
        return None
    details = {}
    for i, v in enumerate(videos, 1):
        title = str(v.get("title", ""))[:50]
        views = int(v.get("views", 0) or 0)
        details[f"#{i} {title}"] = f"{views:,} views"
    return _format_alert(
        icon="🏆", level="success",
        title="TOP YOUTUBE VIDEOS",
        subtitle="All-time best-performing videos",
        details=details,
        audience="Content team",
    )


# ─── Customer Success: dormant customers ─────────────────────────
def build_cs_dormant_alert() -> Optional[str]:
    """Customers with recent payment history that stopped in last 60 days."""
    today = date.today()
    cutoff = (today - timedelta(days=60)).isoformat()
    docs = find_all("payments", {"final_status": "ACCEPTED"},
                     projection={"email_normalized": 1,
                                 "first_payment_date": 1,
                                 "total_spend": 1,
                                 "payment_count": 1})
    if not docs:
        return None
    dormant = []
    for d in docs:
        last = str(d.get("first_payment_date", ""))[:10]
        if last and last < cutoff:
            spend = float(d.get("total_spend", 0) or 0)
            if spend >= 100:
                dormant.append((spend, d))
    dormant.sort(key=lambda x: -x[0])
    if not dormant:
        return None
    details = {"Total dormant (>60d, >$100)": len(dormant)}
    for i, (spend, d) in enumerate(dormant[:5], 1):
        email = str(d.get("email_normalized", "?"))[:35]
        details[f"#{i} {email}"] = f"${spend:,.0f} (last: {str(d.get('first_payment_date', ''))[:10]})"
    return _format_alert(
        icon="😴", level="warn",
        title="DORMANT PAYING CUSTOMERS",
        subtitle="High-value customers with no activity in 60+ days",
        details=details,
        audience="CS team",
    )


# ─── ORCHESTRATOR ────────────────────────────────────────────────
def send_all_rich_alerts() -> Dict[str, int]:
    """
    Send all daily summaries + anomaly alerts to Telegram.
    Returns count sent per category.
    """
    counts = {}

    # Daily summaries
    for name, builder in [
        ("kpi_summary",       build_kpi_daily_summary),
        ("youtube_summary",   build_youtube_daily_summary),
        ("linkedin_summary",  build_linkedin_daily_summary),
        ("ga4_summary",       build_ga4_daily_summary),
        ("cs_summary",        build_cs_daily_summary),
    ]:
        try:
            msg = builder()
            if msg and _send(msg):
                counts[name] = 1
                print(f"  ✅ Sent {name}")
            else:
                counts[name] = 0
        except Exception as e:
            print(f"  ❌ {name} failed: {e}")
            counts[name] = 0

    # Best-of alerts
    for name, builder in [
        ("kpi_top_sources",     build_kpi_top_source_alert),
        ("kpi_top_paying",       build_top_paying_customers_alert),
        ("yt_top_videos",        build_youtube_top_video_alert),
    ]:
        try:
            msg = builder()
            if msg and _send(msg):
                counts[name] = 1
                print(f"  ✅ Sent {name}")
            else:
                counts[name] = 0
        except Exception as e:
            print(f"  ❌ {name} failed: {e}")
            counts[name] = 0

    # Weekly / monthly digests + team briefs
    from datetime import date as _d
    today_dow = _d.today().weekday()  # 0=Mon
    is_monday = today_dow == 0
    is_first_of_month = _d.today().day == 1

    if is_monday:
        try:
            msg = build_weekly_digest()
            if msg and _send(msg):
                counts["weekly_digest"] = 1
                print("  OK Sent weekly_digest")
        except Exception as e:
            print(f"  weekly_digest failed: {e}")

    if is_first_of_month:
        try:
            msg = build_monthly_digest()
            if msg and _send(msg):
                counts["monthly_digest"] = 1
                print("  OK Sent monthly_digest")
        except Exception as e:
            print(f"  monthly_digest failed: {e}")

    if is_monday:
        for nm, bldr in [("marketing_brief", build_marketing_team_brief),
                          ("sales_brief",     build_sales_team_brief)]:
            try:
                msg = bldr()
                if msg and _send(msg):
                    counts[nm] = 1
                    print(f"  OK Sent {nm}")
            except Exception as e:
                print(f"  {nm} failed: {e}")

    # Trend alerts (spike/drop) — single message each
    for name, builder in [
        ("upload_trend",         build_upload_trend_alert),
        ("revenue_trend",        build_revenue_trend_alert),
        ("kpi_cold_sources",     build_kpi_cold_source_alert),
        ("cs_dormant",           build_cs_dormant_alert),
    ]:
        try:
            msg = builder()
            if msg and _send(msg):
                counts[name] = 1
                print(f"  ✅ Sent {name}")
            else:
                counts[name] = 0
        except Exception as e:
            print(f"  ❌ {name} failed: {e}")
            counts[name] = 0

    # Anomaly / per-item alerts (multi-alert)
    for name, builder in [
        ("kpi_spike_alerts",       build_kpi_spike_alerts),
        ("yt_dead_video_alerts",   build_youtube_dead_video_alerts),
        ("li_viral_post_alerts",   build_linkedin_viral_post_alerts),
        ("li_dead_post_alerts",    build_linkedin_dead_post_alerts),
        ("ga4_source_trends",      build_ga4_source_trend_alert),
    ]:
        try:
            alerts = builder() or []
            sent = 0
            for alert in alerts:
                if _send(alert):
                    sent += 1
            counts[name] = sent
            if sent:
                print(f"  ✅ Sent {sent} {name}")
        except Exception as e:
            print(f"  ❌ {name} failed: {e}")
            counts[name] = 0

    total = sum(counts.values())
    print(f"\n✅ TOTAL: {total} rich alerts sent")
    return counts


if __name__ == "__main__":
    print("Building and sending rich alerts...")
    print()
    r = send_all_rich_alerts()
    print()
    import json
    print(json.dumps(r, indent=2))



# ═════════════════════════════════════════════════════════════════
# WEEKLY & MONTHLY DIGESTS + PER-TEAM BRIEFINGS
# ═════════════════════════════════════════════════════════════════
def build_weekly_digest() -> str:
    """Full 7-day rollup for leadership."""
    today = date.today()
    week_ago = (today - timedelta(days=6)).isoformat()
    prev_week = (today - timedelta(days=13)).isoformat()
    prev_end  = (today - timedelta(days=7)).isoformat()
    end = today.isoformat()

    from mongo_client import count_accepted
    s_cur = count_accepted("signups",  "signup_date",        date_gte=week_ago, date_lte=end)
    u_cur = count_accepted("uploads",  "upload_date",        date_gte=week_ago, date_lte=end)
    p_cur = count_accepted("payments", "first_payment_date", date_gte=week_ago, date_lte=end)
    s_prv = count_accepted("signups",  "signup_date",        date_gte=prev_week, date_lte=prev_end)
    u_prv = count_accepted("uploads",  "upload_date",        date_gte=prev_week, date_lte=prev_end)
    p_prv = count_accepted("payments", "first_payment_date", date_gte=prev_week, date_lte=prev_end)

    def _delta(cur, prv):
        if prv == 0: return f"({cur} new)" if cur else "(=)"
        pct = (cur - prv) / prv * 100
        arrow = "up" if pct > 0 else ("=" if pct == 0 else "down")
        return f"({arrow} {abs(pct):.0f}% vs prev)"

    from mongo_client import find_all as fa
    pay_docs = fa("payments", {"final_status": "ACCEPTED",
                                "first_payment_date": {"$gte": week_ago, "$lte": end}})
    rev_cur = sum(float(p.get("total_spend", 0) or 0) for p in pay_docs)
    pay_prv_docs = fa("payments", {"final_status": "ACCEPTED",
                                    "first_payment_date": {"$gte": prev_week, "$lte": prev_end}})
    rev_prv = sum(float(p.get("total_spend", 0) or 0) for p in pay_prv_docs)

    return _format_alert(
        icon="Weekly",
        level="info",
        title="WEEKLY DIGEST",
        subtitle=f"Full 7-day rollup — {week_ago} to {end}",
        details={
            "Signups (7d)":  f"{s_cur} {_delta(s_cur, s_prv)}",
            "Uploads (7d)":  f"{u_cur} {_delta(u_cur, u_prv)}",
            "Paid (7d)":     f"{p_cur} {_delta(p_cur, p_prv)}",
            "Revenue (7d)":  f"${rev_cur:,.2f} {_delta(rev_cur, rev_prv)}",
            "S→U rate":      f"{u_cur/s_cur*100:.1f}%" if s_cur else "n/a",
            "S→P rate":      f"{p_cur/s_cur*100:.1f}%" if s_cur else "n/a",
        },
        audience="Leadership",
    )


def build_monthly_digest() -> str:
    """30-day rollup vs prior 30 days."""
    today = date.today()
    m_ago = (today - timedelta(days=29)).isoformat()
    prev_m = (today - timedelta(days=59)).isoformat()
    prev_end = (today - timedelta(days=30)).isoformat()
    end = today.isoformat()

    from mongo_client import count_accepted, find_all as fa
    s_cur = count_accepted("signups",  "signup_date",        date_gte=m_ago,  date_lte=end)
    u_cur = count_accepted("uploads",  "upload_date",        date_gte=m_ago,  date_lte=end)
    p_cur = count_accepted("payments", "first_payment_date", date_gte=m_ago,  date_lte=end)
    s_prv = count_accepted("signups",  "signup_date",        date_gte=prev_m, date_lte=prev_end)
    u_prv = count_accepted("uploads",  "upload_date",        date_gte=prev_m, date_lte=prev_end)
    p_prv = count_accepted("payments", "first_payment_date", date_gte=prev_m, date_lte=prev_end)

    def _delta(cur, prv):
        if prv == 0: return f"({cur} new)" if cur else "(=)"
        pct = (cur - prv) / prv * 100
        arrow = "up" if pct > 0 else ("=" if pct == 0 else "down")
        return f"({arrow} {abs(pct):.0f}%)"

    rev_cur = sum(float(x.get("total_spend", 0) or 0) for x in
                   fa("payments", {"final_status": "ACCEPTED",
                                    "first_payment_date": {"$gte": m_ago, "$lte": end}}))
    rev_prv = sum(float(x.get("total_spend", 0) or 0) for x in
                   fa("payments", {"final_status": "ACCEPTED",
                                    "first_payment_date": {"$gte": prev_m, "$lte": prev_end}}))

    return _format_alert(
        icon="Monthly",
        level="info",
        title="MONTHLY DIGEST",
        subtitle=f"30-day rollup vs prior 30 days — {m_ago} to {end}",
        details={
            "Signups (30d)": f"{s_cur} {_delta(s_cur, s_prv)}",
            "Uploads (30d)": f"{u_cur} {_delta(u_cur, u_prv)}",
            "Paid (30d)":    f"{p_cur} {_delta(p_cur, p_prv)}",
            "Revenue (30d)": f"${rev_cur:,.2f} {_delta(rev_cur, rev_prv)}",
        },
        audience="Founders + Leadership",
    )


def build_marketing_team_brief() -> str:
    """Focused brief for marketing team."""
    today = date.today()
    week_ago = (today - timedelta(days=6)).isoformat()
    end = today.isoformat()
    from attribution_tracker import signups_by_source
    sources = signups_by_source(week_ago, end)
    top3 = list(sources.items())[:3]
    total = sum(sources.values())

    details = {"Signups this week": total}
    for i, (src, n) in enumerate(top3, 1):
        pct = round(n/total*100, 1) if total else 0
        details[f"#{i} {src}"] = f"{n} ({pct}%)"

    return _format_alert(
        icon="Marketing",
        level="info",
        title="MARKETING WEEKLY BRIEF",
        subtitle="Top acquisition channels — last 7 days",
        details=details,
        audience="Marketing team",
    )


def build_sales_team_brief() -> str:
    """Focused brief for sales/CS team."""
    today = date.today()
    m_ago = (today - timedelta(days=30)).isoformat()
    end = today.isoformat()
    from mongo_client import find_all
    docs = find_all("payments", {
        "final_status": "ACCEPTED",
        "first_payment_date": {"$gte": m_ago, "$lte": end},
    }, sort=[("total_spend", -1)], limit=10)
    if not docs:
        return None

    details = {"New paying customers (30d)": len(docs)}
    for i, d in enumerate(docs[:5], 1):
        details[f"#{i} {str(d.get('email_normalized',''))[:30]}"] = f"${float(d.get('total_spend',0) or 0):,.0f}"

    return _format_alert(
        icon="Sales",
        level="success",
        title="SALES WEEKLY BRIEF",
        subtitle="Top new paying customers — last 30 days",
        details=details,
        audience="Sales / CS team",
    )
