"""
Source Intelligence - Eagle 3D KPI System
Classifies EVERY traffic source and explains WHY it's high/low.

Categories:
- BUYER:      Real prospects (organic, paid ads, content marketing)
- JOB_SEEKER: Job-related traffic (jobrite, hiring posts)
- INTERNAL:   Your own team (stripe checkout, tag assistant, your IPs)
- BOT:        Crawlers, scrapers, automated tools
- UNCERTAIN:  Need investigation (direct, not set)
"""

import pandas as pd
from typing import Dict, List


# ─────────────────────────────────────────────────────────────────
#  SOURCE CLASSIFICATION RULES
#  Based on Eagle 3D's actual traffic patterns
# ─────────────────────────────────────────────────────────────────

INTERNAL_SOURCES = {
    "checkout.stripe.com":     "Stripe payment redirect — your own checkout flow",
    "stripe.com":               "Stripe payment processor — your billing",
    "stripe":                   "Stripe payment processor",
    "tagassistant.google.com":  "Google Tag Assistant — used by your team for testing GTM",
    "tag-assistant":            "Google Tag Assistant testing tool",
    "googletagmanager.com":     "Google Tag Manager — internal tag testing",
    "localhost":                "Local development testing",
    "127.0.0.1":                "Local development testing",
    "vercel.com":               "Vercel hosting preview",
    "netlify.com":              "Netlify hosting preview",
    "github.com":               "GitHub repo references (internal)",
    "controlpanel.eagle3dstreaming.com": "Eagle's own control panel",
    "eagle3dstreaming.com":     "Your own domain (self-referral)",
}

JOB_SEEKER_SOURCES = {
    "jobrite.ai":               "AI-powered job aggregator — visitors looking for jobs",
    "jobrite":                  "Job aggregator referral",
    "indeed.com":               "Indeed job board",
    "indeed":                   "Indeed job board",
    "glassdoor.com":            "Glassdoor job board",
    "glassdoor":                "Glassdoor reviews + jobs",
    "ziprecruiter.com":         "ZipRecruiter job board",
    "monster.com":              "Monster job board",
    "lever.co":                 "Lever ATS",
    "greenhouse.io":            "Greenhouse ATS",
    "workable.com":             "Workable ATS",
    "remoteok.com":             "Remote OK jobs",
    "weworkremotely.com":       "We Work Remotely jobs",
}

BOT_SOURCES = {
    "bot":          "Generic bot traffic",
    "crawler":      "Web crawler",
    "spider":       "Search spider",
    "scraper":      "Content scraper",
    "ahrefs":       "Ahrefs SEO bot",
    "semrush":      "SEMrush SEO bot",
    "moz":          "Moz crawler",
    "screaming-frog": "Screaming Frog crawler",
}

BUYER_SOURCES = {
    # Search engines (organic)
    "google":         "Google organic search — high-intent buyers searching solutions",
    "bing":           "Bing organic search — buyers (often enterprise)",
    "duckduckgo":     "DuckDuckGo organic — privacy-conscious users",
    "yahoo":          "Yahoo search",
    "yandex":         "Yandex (Russian market)",
    "baidu":          "Baidu (Chinese market)",

    # Paid ads
    "google-ads":     "Google Ads paid traffic",
    "googleads":      "Google Ads paid traffic",
    "facebook":       "Facebook/Meta ads or organic",
    "facebook.com":   "Facebook referral",
    "instagram":      "Instagram traffic",
    "instagram.com":  "Instagram referral",
    "twitter":        "Twitter/X traffic",
    "x.com":          "X (Twitter) referral",
    "t.co":           "Twitter shortened links",

    # B2B sources
    "linkedin":       "LinkedIn — B2B audience (but check intent: jobs vs product)",
    "linkedin.com":   "LinkedIn referral",
    "lnkd.in":        "LinkedIn shortened links",

    # AI / Discovery
    "chatgpt.com":    "ChatGPT recommendation — AI search visibility",
    "perplexity.ai":  "Perplexity AI search",
    "claude.ai":      "Claude AI recommendation",
    "bard.google.com":"Google Bard recommendation",

    # Reviews / Comparison
    "g2.com":         "G2 reviews — B2B SaaS comparison shoppers",
    "capterra.com":   "Capterra reviews — software comparison",
    "trustpilot.com": "Trustpilot reviews",
    "producthunt.com":"Product Hunt launch",

    # Communities
    "reddit.com":     "Reddit community traffic — developer/architect audience",
    "reddit":         "Reddit referral",
    "stackoverflow.com": "Stack Overflow — developer audience",
    "hackernews":     "Hacker News tech audience",
    "news.ycombinator.com": "Hacker News",

    # Email
    "email":          "Email marketing campaigns",
    "newsletter":     "Newsletter subscribers",
    "mailchimp":      "Mailchimp campaign",
    "hubspot":        "HubSpot email/CRM",
    "hs_email":       "HubSpot email click",
    "sendgrid":       "SendGrid email",

    # YouTube
    "youtube.com":    "YouTube video traffic",
    "youtu.be":       "YouTube shortened links",
}

UNCERTAIN_SOURCES = {
    "(direct)":       "Direct traffic — bookmarks, typed URLs, OR untracked sources (email/Slack/messaging apps)",
    "direct":         "Direct traffic",
    "(not set)":      "GA4 couldn't identify source — usually app browsers or stripped referrers",
    "not set":        "Unknown source",
    "(none)":         "No medium specified",
}


def classify_source(source: str, medium: str = "") -> dict:
    """
    Classify a single source into category with explanation.
    Returns: {category, label, explanation, action}
    """
    src = (source or "").lower().strip()
    med = (medium or "").lower().strip()

    # Check internal first (highest priority)
    for pattern, explanation in INTERNAL_SOURCES.items():
        if pattern in src:
            return {
                "category":    "INTERNAL",
                "label":       "🏢 Internal/Self",
                "explanation": explanation,
                "action":      "FILTER OUT — this is not real user traffic",
                "include":     False,
            }

    # Job seekers
    for pattern, explanation in JOB_SEEKER_SOURCES.items():
        if pattern in src:
            return {
                "category":    "JOB_SEEKER",
                "label":       "💼 Job Seeker",
                "explanation": explanation,
                "action":      "Track separately — these are NOT buyers. Use /careers landing page.",
                "include":     True,
            }

    # Bots
    for pattern, explanation in BOT_SOURCES.items():
        if pattern in src:
            return {
                "category":    "BOT",
                "label":       "🤖 Bot/Crawler",
                "explanation": explanation,
                "action":      "FILTER OUT — non-human traffic",
                "include":     False,
            }

    # Uncertain
    for pattern, explanation in UNCERTAIN_SOURCES.items():
        if pattern in src:
            return {
                "category":    "UNCERTAIN",
                "label":       "❓ Uncertain",
                "explanation": explanation,
                "action":      "Investigate — likely email/Slack/messaging apps. Add UTM tags to all outbound links you control.",
                "include":     True,
            }

    # Buyers
    for pattern, explanation in BUYER_SOURCES.items():
        if pattern in src:
            return {
                "category":    "BUYER",
                "label":       "🎯 Potential Buyer",
                "explanation": explanation,
                "action":      "Monitor conversion rate — invest more if converting well.",
                "include":     True,
            }

    # Unknown — assume buyer but flag
    return {
        "category":    "UNKNOWN",
        "label":       "❔ Unknown",
        "explanation": f"Source '{source}' not in classifier database. Likely a referral or new channel.",
        "action":      "Investigate this source manually. Add to classifier if it becomes recurring.",
        "include":     True,
    }


def classify_dataframe(df: pd.DataFrame, source_col: str = "sessionSource",
                       medium_col: str = "sessionMedium") -> pd.DataFrame:
    """Add classification columns to a GA4 DataFrame."""
    if df.empty:
        return df

    df = df.copy()
    classifications = df.apply(
        lambda r: classify_source(
            r.get(source_col, ""),
            r.get(medium_col, "")
        ),
        axis=1,
    )

    df["category"]    = classifications.apply(lambda c: c["category"])
    df["category_label"] = classifications.apply(lambda c: c["label"])
    df["why"]         = classifications.apply(lambda c: c["explanation"])
    df["action"]      = classifications.apply(lambda c: c["action"])
    df["is_real_visitor"] = classifications.apply(lambda c: c["include"])

    return df


def filter_real_visitors(df: pd.DataFrame, source_col: str = "sessionSource",
                          medium_col: str = "sessionMedium") -> pd.DataFrame:
    """Remove internal/bot traffic. Keeps real visitor sessions only."""
    if df.empty:
        return df
    classified = classify_dataframe(df, source_col, medium_col)
    return classified[classified["is_real_visitor"]].drop(
        columns=["category","category_label","why","action","is_real_visitor"]
    )


def explain_top_sources(df: pd.DataFrame, top_n: int = 15) -> str:
    """Generate explanation for top N sources with WHY they're high."""
    if df.empty:
        return "No data to analyze."

    classified = classify_dataframe(df)

    # Group by source
    grouped = classified.groupby("sessionSource").agg(
        sessions=("sessions","sum"),
        conversions=("conversions","sum"),
        category=("category_label","first"),
        why=("why","first"),
        action=("action","first"),
    ).reset_index().sort_values("sessions",ascending=False).head(top_n)

    total_sess = float(classified["sessions"].sum())

    lines = ["## �� Source-by-Source Intelligence", ""]
    lines.append("Every source below explained with WHY and ACTION:")
    lines.append("")

    for _, row in grouped.iterrows():
        share = (row["sessions"] / total_sess * 100) if total_sess > 0 else 0
        conv_rate = (row["conversions"] / row["sessions"] * 100) if row["sessions"] > 0 else 0

        lines.append(f"### {row['category']} **{row['sessionSource']}**")
        lines.append(f"- **Sessions:** {int(row['sessions']):,} ({share:.1f}% of total)")
        lines.append(f"- **Conversions:** {int(row['conversions'])} ({conv_rate:.2f}% rate)")
        lines.append(f"- **Why:** {row['why']}")
        lines.append(f"- **Action:** {row['action']}")
        lines.append("")

    return "\n".join(lines)


def get_category_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate sessions by category. Shows BUYER vs JOB_SEEKER vs INTERNAL split."""
    if df.empty:
        return pd.DataFrame()

    classified = classify_dataframe(df)

    summary = classified.groupby(["category","category_label"]).agg(
        sessions=("sessions","sum"),
        users=("totalUsers","sum"),
        conversions=("conversions","sum"),
    ).reset_index().sort_values("sessions",ascending=False)

    total = float(summary["sessions"].sum())
    summary["share_%"] = (summary["sessions"] / total * 100).round(1)
    summary["conv_rate_%"] = (summary["conversions"] / summary["sessions"].replace(0,1) * 100).round(2)

    return summary


def get_filtered_summary(df: pd.DataFrame) -> dict:
    """Returns clean summary excluding internal/bot traffic."""
    if df.empty:
        return {"total_raw": 0, "total_real": 0, "filtered_out": 0,
                "real_pct": 0, "categories": {}}

    classified = classify_dataframe(df)
    total_raw = float(classified["sessions"].sum())
    real = classified[classified["is_real_visitor"]]
    total_real = float(real["sessions"].sum())
    filtered = total_raw - total_real

    by_cat = classified.groupby("category")["sessions"].sum().to_dict()

    return {
        "total_raw":    int(total_raw),
        "total_real":   int(total_real),
        "filtered_out": int(filtered),
        "real_pct":     round(total_real / total_raw * 100, 1) if total_raw > 0 else 0,
        "categories":   {k: int(v) for k, v in by_cat.items()},
    }


def smart_question_answer(question: str, utm_df: pd.DataFrame,
                          kpi_df: pd.DataFrame = None) -> str:
    """Answer common questions automatically based on classified data."""
    if utm_df.empty:
        return "No data available to analyze."

    classified = classify_dataframe(utm_df)
    q = question.lower()

    # "Why is X high?"
    if "high" in q or "why" in q:
        # Extract source name from question
        for src in classified["sessionSource"].unique():
            if str(src).lower() in q:
                src_data = classified[classified["sessionSource"] == src]
                sess = int(src_data["sessions"].sum())
                cat = src_data["category_label"].iloc[0]
                why = src_data["why"].iloc[0]
                return f"### {cat} **{src}** = {sess:,} sessions\n\n**Why:** {why}\n\n**Action:** {src_data['action'].iloc[0]}"

    # Generic explanation
    return explain_top_sources(utm_df)

