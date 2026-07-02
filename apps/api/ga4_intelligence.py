"""
GA4 Intelligence Engine - Eagle 3D KPI System
100% Free - Smart rule-based analysis, no paid AI needed
Produces same quality decisions as AI from pure data logic
"""

import pandas as pd
from datetime import datetime
from typing import Optional


def score_signup_probability(source, medium, conversions, sessions):
    score = 0
    src = (source or "").lower()
    med = (medium or "").lower()

    if any(h in src for h in ["google", "bing", "linkedin"]):
        score += 30
    if any(m in med for m in ["email", "newsletter", "referral"]):
        score += 20
    if med in ["cpc", "paid", "ppc"]:
        score += 25
    if med == "organic":
        score += 15
    if "direct" in src:
        score += 10

    conv_rate = (conversions / sessions * 100) if sessions > 0 else 0
    if conv_rate > 5:
        score += 25
    elif conv_rate > 2:
        score += 15
    elif conv_rate > 0.5:
        score += 8

    score = min(score, 100)

    if score >= 70:
        label = "�� High Intent"
    elif score >= 40:
        label = "🟡 Medium Intent"
    else:
        label = "�� Low Intent"

    return {
        "score": score,
        "label": label,
        "conv_rate": round(conv_rate, 2),
    }


def _pct(new_val, old_val):
    if old_val == 0:
        return 100.0 if new_val > 0 else 0.0
    return round((new_val - old_val) / old_val * 100, 1)


def generate_traffic_analysis(utm_df, page_df, event_df, signups_external=None):
    today = datetime.now().strftime("%B %d, %Y")
    lines = []
    lines.append(f"## 📊 Eagle 3D Traffic Analysis — {today}")
    lines.append("")

    # ── Traffic Health ──────────────────────────────────────────────
    lines.append("### 1️⃣ Traffic Health by Channel")
    if not utm_df.empty:
        src = (
            utm_df.groupby("sessionSource")
            .agg(sessions=("sessions","sum"),
                 new_users=("newUsers","sum"),
                 conversions=("conversions","sum"))
            .sort_values("sessions", ascending=False)
        )
        total_sess = src["sessions"].sum()
        for source, row in src.head(6).iterrows():
            share = (row["sessions"] / total_sess * 100) if total_sess > 0 else 0
            conv_r = (row["conversions"] / row["sessions"] * 100) if row["sessions"] > 0 else 0
            icon = "🔥" if share > 30 else ("📈" if share > 10 else "📉")
            lines.append(
                f"- {icon} **{source}**: {int(row['sessions']):,} sessions "
                f"({share:.1f}% of total) | {int(row['new_users']):,} new users | "
                f"Conv: {conv_r:.2f}%"
            )
    else:
        lines.append("- No UTM data available for this period")
    lines.append("")

    # ── Signup Attribution ──────────────────────────────────────────
    lines.append("### 2️⃣ Signup Attribution — Where Signups Come From")
    if not utm_df.empty:
        conv_src = (
            utm_df.groupby(["sessionSource","sessionMedium"])
            .agg(sessions=("sessions","sum"),
                 conversions=("conversions","sum"))
            .reset_index()
            .sort_values("conversions", ascending=False)
        )
        top_conv = conv_src[conv_src["conversions"] > 0].head(5)
        if not top_conv.empty:
            for _, row in top_conv.iterrows():
                scored = score_signup_probability(
                    row["sessionSource"], row["sessionMedium"],
                    row["conversions"], row["sessions"]
                )
                lines.append(
                    f"- **{row['sessionSource']} / {row['sessionMedium']}**: "
                    f"{int(row['conversions'])} conversions | "
                    f"{scored['conv_rate']:.2f}% rate | {scored['label']}"
                )
        else:
            lines.append("- No conversion events tracked yet — set up GA4 conversion events")

        if signups_external and signups_external > 0:
            ga4_total = float(utm_df["conversions"].sum())
            gap = signups_external - ga4_total
            if gap > 2:
                lines.append(
                    f"\n⚠️ **Tracking Gap**: CRM shows {signups_external} signups but "
                    f"GA4 tracked only {ga4_total:.0f}. "
                    f"Missing {gap:.0f} signups — check GA4 conversion event setup."
                )
    lines.append("")

    # ── Page Insights ───────────────────────────────────────────────
    lines.append("### 3️⃣ Page Insights")
    if not page_df.empty:
        pages = (
            page_df.groupby("pagePath")
            .agg(views=("screenPageViews","sum"),
                 sessions=("sessions","sum"),
                 conversions=("conversions","sum"),
                 bounce=("bounceRate","mean"),
                 engagement=("engagementRate","mean"))
            .sort_values("views", ascending=False)
        )
        lines.append("**Top Performing Pages:**")
        for path, row in pages.head(5).iterrows():
            eng = row["engagement"] * 100 if row["engagement"] <= 1 else row["engagement"]
            flag = "🌟" if eng > 50 else ("⚠️" if eng < 20 else "✅")
            lines.append(
                f"- {flag} **{path}**: {int(row['views']):,} views | "
                f"Engagement: {eng:.1f}% | Conversions: {int(row['conversions'])}"
            )

        # Low performers
        low = pages[(pages["views"] > 10) & (pages["engagement"] < 0.2)].head(3)
        if not low.empty:
            lines.append("\n**Pages Needing Improvement (low engagement):**")
            for path, row in low.iterrows():
                lines.append(f"- ⚠️ **{path}**: High views but low engagement — review content/CTA")
    lines.append("")

    # ── Event Insights ──────────────────────────────────────────────
    lines.append("### 4️⃣ Event Intelligence — Purchase Intent Signals")
    if not event_df.empty:
        signup_signals = [
            "sign_up","signup","registration","form_submit",
            "begin_checkout","purchase","trial_start","demo_request",
            "contact","quote","subscribe","click"
        ]
        events = (
            event_df.groupby("eventName")
            .agg(count=("eventCount","sum"),
                 conversions=("conversions","sum"))
            .sort_values("count", ascending=False)
        )
        lines.append("**High-Intent Events:**")
        found_signals = False
        for event_name, row in events.iterrows():
            is_signal = any(s in event_name.lower() for s in signup_signals)
            if is_signal:
                found_signals = True
                lines.append(
                    f"- 🎯 **{event_name}**: {int(row['count']):,} times | "
                    f"Conversions: {int(row['conversions'])}"
                )
        if not found_signals:
            lines.append(
                "- No signup-signal events found. "
                "Set up GA4 events for form_submit, sign_up, demo_request"
            )

        lines.append("\n**Top 5 Events Overall:**")
        for event_name, row in events.head(5).iterrows():
            lines.append(f"- **{event_name}**: {int(row['count']):,} occurrences")
    lines.append("")

    # ── Top 3 Actions ───────────────────────────────────────────────
    lines.append("### 5️⃣ Top 3 Actions for Today")

    actions = []

    if not utm_df.empty:
        src_conv = utm_df.groupby("sessionSource")["conversions"].sum()
        top_converting = src_conv.idxmax() if not src_conv.empty else None
        if top_converting:
            actions.append(
                f"1. 🚀 **Double down on {top_converting}** — it's your top converting source. "
                f"Increase budget/effort there immediately."
            )

    if not page_df.empty:
        pages_agg = page_df.groupby("pagePath").agg(
            views=("screenPageViews","sum"),
            eng=("engagementRate","mean")
        )
        high_views_low_eng = pages_agg[
            (pages_agg["views"] > pages_agg["views"].median()) &
            (pages_agg["eng"] < 0.3)
        ]
        if not high_views_low_eng.empty:
            worst_page = high_views_low_eng["eng"].idxmin()
            actions.append(
                f"2. 🔧 **Fix {worst_page}** — high traffic but low engagement. "
                f"Add clear CTA, improve content, or A/B test the headline."
            )

    if not event_df.empty:
        all_events = event_df["eventName"].unique()
        missing = [
            s for s in ["sign_up","form_submit","demo_request"]
            if not any(s in e.lower() for e in all_events)
        ]
        if missing:
            actions.append(
                f"3. 📊 **Set up missing GA4 events**: {', '.join(missing)} — "
                f"without these you cannot track where signups come from."
            )

    if len(actions) < 3:
        actions.append(
            "3. 📧 **Retarget pricing page visitors** — "
            "anyone who visited /pricing but did not sign up is a hot lead. "
            "Set up a retargeting campaign for them."
        )

    for action in actions[:3]:
        lines.append(action)
    lines.append("")
    lines.append("---")
    lines.append(
        "*Analysis generated by Eagle 3D KPI System — "
        "Rule-based intelligence engine (100% free)*"
    )

    return "\n".join(lines)


def generate_daily_notification(page_df, event_df, utm_df, prev_page_df=None):
    today = datetime.now().strftime("%A, %B %d %Y")
    lines = []
    lines.append(f"## 📬 Daily Traffic Briefing — {today}")
    lines.append("")

    # Top sources
    lines.append("### 📊 Today's Traffic Pulse")
    if not utm_df.empty:
        top = (
            utm_df.groupby("sessionSource")["sessions"]
            .sum()
            .sort_values(ascending=False)
            .head(5)
        )
        for src, sess in top.items():
            bar_len = min(int(sess / max(top.values) * 20), 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            lines.append(f"- **{src}** `{bar}` {int(sess):,} sessions")
    lines.append("")

    # Conversion signals
    lines.append("### 🎯 Conversion Signals")
    if not event_df.empty:
        signals = ["sign_up","signup","form_submit","registration",
                   "begin_checkout","trial_start","demo_request","purchase"]
        sig_events = event_df[
            event_df["eventName"].str.lower().apply(
                lambda x: any(s in x for s in signals)
            )
        ]
        if not sig_events.empty:
            sig_agg = sig_events.groupby("eventName")["eventCount"].sum()
            for event_name, count in sig_agg.items():
                lines.append(f"- 🎯 **{event_name}**: {int(count):,} times today")
        else:
            lines.append("- No conversion events detected. Check GA4 event setup.")
    lines.append("")

    # Key recommendation
    lines.append("### 💡 Today's Key Recommendation")
    if not utm_df.empty:
        src_data = utm_df.groupby("sessionSource").agg(
            sessions=("sessions","sum"),
            conversions=("conversions","sum")
        )
        best_conv_rate = (
            (src_data["conversions"] / src_data["sessions"].replace(0,1) * 100)
            .sort_values(ascending=False)
        )
        if not best_conv_rate.empty:
            best_src = best_conv_rate.index[0]
            rate = best_conv_rate.iloc[0]
            lines.append(
                f"**Focus on {best_src}** — it has the highest conversion rate "
                f"({rate:.2f}%) among all your sources. "
                f"Consider increasing investment or creating more content for this channel."
            )
    lines.append("")

    # Tomorrow watchlist
    lines.append("### 📅 Tomorrow's Watch List")
    lines.append("- 👀 Monitor organic sessions — are they growing day over day?")
    lines.append("- 👀 Watch sign_up event count — compare to this week's average")
    lines.append("")
    lines.append("---")
    lines.append("*Eagle 3D KPI — Daily Briefing | Rule-Based Intelligence*")

    return "\n".join(lines)

