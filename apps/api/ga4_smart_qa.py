"""
Smart Q&A Engine - Eagle 3D KPI System
Free-text question answering across:
- GA4 traffic data (UTM, sources, pages, events)
- CRM data (Daily_Counts, Verified_FREE, Verified_FIRST_UPLOAD, Verified_STRIPE)
- Lead Source attribution
- Strategic context (job seekers, internal, buyers)

100% rule-based — no paid AI APIs needed
Uses keyword matching + data analysis + templated responses
"""

import pandas as pd
import re
from datetime import datetime, timedelta
from typing import Dict, Any, Optional


# ─────────────────────────────────────────────────────────────────
#  KEYWORD CATEGORIES — what each question type is about
# ─────────────────────────────────────────────────────────────────

KEYWORDS = {
    "signup": [
        "signup","sign-up","sign up","register","registration",
        "new user","new users","new customer","new customers",
        "free user","free account","new account",
    ],
    "upload": [
        "upload","first upload","project","projects","app","apps",
    ],
    "paid": [
        "paid","customer","subscriber","subscription","stripe",
        "revenue","sales","conversion","convert","convert to paid",
        "money","money making","income","mrr","arr",
    ],
    "traffic": [
        "traffic","visitor","visitors","session","sessions",
        "user","users","viewer","viewers","audience",
    ],
    "source": [
        "source","sources","channel","channels","where from",
        "where are","coming from","attribution","referrer",
    ],
    "google": ["google","organic","seo","search","search engine"],
    "linkedin": ["linkedin","li","li.com"],
    "direct": ["direct","bookmark","typed","no referrer"],
    "jobrite": ["jobrite","job","hiring","recruit","applicant"],
    "stripe": ["stripe","checkout","payment","billing"],
    "page": ["page","pages","url","route","path"],
    "event": ["event","events","action","trigger","click"],
    "country": ["country","countries","geo","location","region"],
    "device": ["device","mobile","desktop","tablet","phone"],
    "compare": ["compare","vs","versus","difference","change","trend"],
    "best": ["best","top","highest","most","top performing","winner"],
    "worst": ["worst","bottom","lowest","least","wasted","losing"],
    "why": ["why","reason","cause","explain","what causes"],
    "how_many": ["how many","how much","count","total","number of"],
    "when": ["when","what day","what date","peak","best time"],
    "ai_search": ["ai search","chatgpt","perplexity","claude","ai recommendation"],
    "backlink": ["backlink","link","external link","domain authority","da"],
    "competitor": ["competitor","vagon","parsec","furioos","competition"],
    "predict": ["predict","forecast","next week","future","projection","will"],
    "rate": ["rate","percentage","conversion rate","ratio","%"],
}


def _detect_intent(question: str) -> list:
    """Return matched keyword categories from question."""
    q = question.lower()
    matches = []
    for category, words in KEYWORDS.items():
        if any(w in q for w in words):
            matches.append(category)
    return matches


# ─────────────────────────────────────────────────────────────────
#  ANSWER HANDLERS — each handles a specific type of question
# ─────────────────────────────────────────────────────────────────

def _answer_signup_count(kpi_df, period_label="this period"):
    if kpi_df is None or kpi_df.empty:
        return "❌ No CRM signup data available."
    total = int(kpi_df["signups"].sum())
    days = len(kpi_df)
    daily_avg = total / days if days > 0 else 0
    return f"""
### 📊 Sign-ups {period_label}

- **Total:** {total}
- **Daily average:** {daily_avg:.1f}
- **Days tracked:** {days}
- **Best day:** {int(kpi_df['signups'].max())} signups
- **Slowest day:** {int(kpi_df['signups'].min())} signups
"""


def _answer_paid_count(kpi_df, period_label="this period"):
    if kpi_df is None or kpi_df.empty:
        return "❌ No CRM paid customer data available."
    total_paid = int(kpi_df["paid_customers"].sum())
    total_signups = int(kpi_df["signups"].sum())
    conv_rate = (total_paid/total_signups*100) if total_signups > 0 else 0
    return f"""
### 💰 Paid Customers {period_label}

- **Total paid:** {total_paid}
- **Total signups:** {total_signups}
- **Sign-up → Paid rate:** {conv_rate:.2f}%
- **Best day:** {int(kpi_df['paid_customers'].max())} new paid customers
"""


def _answer_upload_count(kpi_df, period_label="this period"):
    if kpi_df is None or kpi_df.empty:
        return "❌ No CRM upload data available."
    uploads = int(kpi_df["first_uploads"].sum())
    signups = int(kpi_df["signups"].sum())
    rate = (uploads/signups*100) if signups > 0 else 0
    return f"""
### 📤 First Uploads {period_label}

- **Total first uploads:** {uploads}
- **Total signups:** {signups}
- **Sign-up → Upload rate:** {rate:.2f}%
- **Best day:** {int(kpi_df['first_uploads'].max())} uploads
"""


def _answer_top_lead_sources(sources_df):
    if sources_df is None or sources_df.empty:
        return "❌ No Lead Source data available from CRM."
    top5 = sources_df.head(5)
    lines = ["### 🎯 Top Lead Sources (from CRM)\n"]
    for _, row in top5.iterrows():
        lines.append(f"- **{row['Lead Source']}**: {int(row['Signups'])} signups ({row['% of Total']:.1f}%)")
    return "\n".join(lines)


def _answer_traffic_sources(utm_df, period_label="this period"):
    if utm_df is None or utm_df.empty:
        return "❌ No GA4 traffic data available."

    by_src = utm_df.groupby("sessionSource").agg(
        sessions=("sessions","sum"),
        users=("totalUsers","sum"),
        conversions=("conversions","sum"),
    ).sort_values("sessions",ascending=False).head(10)

    total = float(by_src["sessions"].sum())
    lines = [f"### 🌐 Traffic Sources {period_label}\n"]
    lines.append(f"**Total sessions:** {int(total):,}\n")
    for src, row in by_src.iterrows():
        share = row["sessions"]/total*100 if total > 0 else 0
        lines.append(f"- **{src}**: {int(row['sessions']):,} sessions ({share:.1f}%)")
    return "\n".join(lines)


def _answer_specific_source(question, utm_df, kpi_df=None):
    """Answer about a specific source mentioned in the question."""
    q = question.lower()

    # Try to find which source was asked about
    if utm_df is None or utm_df.empty:
        return None

    for src in utm_df["sessionSource"].dropna().unique():
        src_lower = str(src).lower()
        # Strip common chars
        clean = re.sub(r'[()\[\]]','', src_lower)
        if clean in q or src_lower in q:
            src_data = utm_df[utm_df["sessionSource"] == src]
            total_sess = float(src_data["sessions"].sum())
            total_conv = float(src_data["conversions"].sum())
            total_users = float(src_data["totalUsers"].sum())
            conv_rate = (total_conv/total_sess*100) if total_sess > 0 else 0
            total_all = float(utm_df["sessions"].sum())
            share = (total_sess/total_all*100) if total_all > 0 else 0

            return f"""
### 🔍 Analysis of source: **{src}**

- **Sessions:** {int(total_sess):,} ({share:.1f}% of all traffic)
- **Users:** {int(total_users):,}
- **Conversions:** {int(total_conv)}
- **Conversion rate:** {conv_rate:.2f}%

{_get_source_context(src)}
"""
    return None


def _get_source_context(source):
    """Add context about what type of source this is."""
    src = str(source).lower()

    if "google" in src:
        return "✅ **Type:** Organic search — high-intent buyers searching for solutions."
    if "linkedin" in src:
        return "⚠️ **Type:** Mixed — could be buyers OR job seekers. Check if traffic comes after job posts."
    if "jobrite" in src or "indeed" in src or "glassdoor" in src:
        return "🚫 **Type:** JOB SEEKERS — not buyers. Filter from product analytics."
    if "stripe" in src or "tagassistant" in src:
        return "🚫 **Type:** INTERNAL — your own checkout/tools. Should be filtered out."
    if "direct" in src:
        return "❓ **Type:** Direct — bookmarks, typed URLs, or untracked email/Slack/messaging links."
    if "(not set)" in src or "not set" in src:
        return "❓ **Type:** GA4 couldn't identify — usually mobile app browsers or stripped referrers."
    if "facebook" in src or "instagram" in src or "twitter" in src:
        return "📱 **Type:** Social media referral."
    if "reddit" in src or "stackoverflow" in src:
        return "💬 **Type:** Community/forum — high-quality developer traffic."
    if "chatgpt" in src or "perplexity" in src:
        return "🤖 **Type:** AI search recommendation — great signal for AI visibility."
    return "**Type:** Unknown — investigate this referrer."


def _answer_pages(pages_df):
    if pages_df is None or pages_df.empty:
        return "❌ No page data available."
    top = pages_df.groupby("pagePath").agg(
        views=("screenPageViews","sum"),
        conv=("conversions","sum"),
    ).sort_values("views",ascending=False).head(10)
    lines = ["### 📄 Top Pages by Views\n"]
    for path, row in top.iterrows():
        lines.append(f"- `{path}`: {int(row['views']):,} views, {int(row['conv'])} conversions")
    return "\n".join(lines)


def _answer_events(events_df):
    if events_df is None or events_df.empty:
        return "❌ No event data available."
    top = events_df.groupby("eventName")["eventCount"].sum().sort_values(ascending=False).head(10)
    lines = ["### ⚡ Top Events\n"]
    for ev, count in top.items():
        lines.append(f"- **{ev}**: {int(count):,} times")
    return "\n".join(lines)


def _answer_best_day(kpi_df):
    if kpi_df is None or kpi_df.empty:
        return "❌ No CRM data available."
    best = kpi_df.loc[kpi_df["signups"].idxmax()]
    return f"""
### 📅 Best Day for Sign-ups

- **Date:** {best['date']}
- **Sign-ups:** {int(best['signups'])}
- **Uploads:** {int(best['first_uploads'])}
- **Paid:** {int(best['paid_customers'])}
"""


def _answer_funnel(kpi_df):
    if kpi_df is None or kpi_df.empty:
        return "❌ No CRM data available."
    s = int(kpi_df["signups"].sum())
    u = int(kpi_df["first_uploads"].sum())
    p = int(kpi_df["paid_customers"].sum())
    s2u = (u/s*100) if s > 0 else 0
    u2p = (p/u*100) if u > 0 else 0
    s2p = (p/s*100) if s > 0 else 0
    return f"""
### 📈 Complete Funnel

| Stage | Count | Rate |
|---|---|---|
| Sign-ups | {s} | — |
| First Uploads | {u} | {s2u:.2f}% from signups |
| Paid Customers | {p} | {u2p:.2f}% from uploads |
| **Sign-up → Paid** | — | **{s2p:.2f}%** |

**Biggest drop:** {'Sign-up → Upload' if s2u < u2p else 'Upload → Paid'}
"""


def _answer_compare(kpi_df, p_kpi_df):
    if kpi_df is None or p_kpi_df is None or kpi_df.empty or p_kpi_df.empty:
        return "❌ Need current + previous period data to compare."

    curr_s = int(kpi_df["signups"].sum())
    prev_s = int(p_kpi_df["signups"].sum())
    curr_p = int(kpi_df["paid_customers"].sum())
    prev_p = int(p_kpi_df["paid_customers"].sum())

    s_change = ((curr_s - prev_s) / prev_s * 100) if prev_s > 0 else 0
    p_change = ((curr_p - prev_p) / prev_p * 100) if prev_p > 0 else 0

    return f"""
### 📊 Period Comparison

| Metric | Previous | Current | Change |
|---|---|---|---|
| Sign-ups | {prev_s} | {curr_s} | {s_change:+.1f}% |
| Paid | {prev_p} | {curr_p} | {p_change:+.1f}% |

{'📈 Growing!' if s_change > 0 else '📉 Declining — investigate cause' if s_change < -5 else '➡️ Stable'}
"""


def _answer_top_country(geo_df):
    if geo_df is None or geo_df.empty:
        return "❌ No geographic data available."
    top = geo_df.groupby("country")["sessions"].sum().sort_values(ascending=False).head(5)
    lines = ["### 🌍 Top Countries by Traffic\n"]
    for c, sess in top.items():
        lines.append(f"- **{c}**: {int(sess):,} sessions")
    return "\n".join(lines)


def _answer_device_breakdown(dev_df):
    if dev_df is None or dev_df.empty:
        return "❌ No device data available."
    by_dev = dev_df.groupby("deviceCategory")["sessions"].sum()
    total = by_dev.sum()
    lines = ["### 📱 Device Breakdown\n"]
    for dev, sess in by_dev.items():
        pct = (sess/total*100) if total > 0 else 0
        lines.append(f"- **{dev}**: {int(sess):,} sessions ({pct:.1f}%)")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
#  MAIN ROUTER — picks the right answer based on question
# ─────────────────────────────────────────────────────────────────

def answer_free_text_question(
    question: str,
    utm_df=None,
    pages_df=None,
    events_df=None,
    geo_df=None,
    dev_df=None,
    kpi_df=None,
    p_kpi_df=None,
    lead_sources_df=None,
) -> str:
    """
    Free-text Q&A — analyzes any question and returns data-driven answer.
    """
    if not question or len(question.strip()) < 3:
        return "Please ask a question (at least 3 characters)."

    intents = _detect_intent(question)
    q = question.lower()

    # Build answer parts
    answers = []

    # ── Try specific source first ────────────────────────────────
    specific = _answer_specific_source(question, utm_df, kpi_df)
    if specific:
        answers.append(specific)

    # ── Then by intent ───────────────────────────────────────────
    if not specific:
        if "compare" in intents or "trend" in q:
            answers.append(_answer_compare(kpi_df, p_kpi_df))

        if "signup" in intents and ("how_many" in intents or "count" in q or "total" in q):
            answers.append(_answer_signup_count(kpi_df))

        if "paid" in intents and ("how_many" in intents or "count" in q or "total" in q):
            answers.append(_answer_paid_count(kpi_df))

        if "upload" in intents and ("how_many" in intents or "count" in q or "total" in q):
            answers.append(_answer_upload_count(kpi_df))

        if "source" in intents and "signup" in intents:
            answers.append(_answer_top_lead_sources(lead_sources_df))

        if "source" in intents and "traffic" in intents:
            answers.append(_answer_traffic_sources(utm_df))

        if "page" in intents:
            answers.append(_answer_pages(pages_df))

        if "event" in intents:
            answers.append(_answer_events(events_df))

        if "country" in intents:
            answers.append(_answer_top_country(geo_df))

        if "device" in intents:
            answers.append(_answer_device_breakdown(dev_df))

        if "best" in intents and ("day" in q or "when" in intents):
            answers.append(_answer_best_day(kpi_df))

        if "rate" in intents or "funnel" in q or "conversion" in q:
            answers.append(_answer_funnel(kpi_df))

    # ── Strategic / explanatory questions ────────────────────────
    if "why" in intents:
        if "direct" in q:
            answers.append(_explain_direct_traffic(utm_df))
        elif "linkedin" in q:
            answers.append(_explain_linkedin(utm_df))
        elif "low" in q or "drop" in q or "decreas" in q:
            answers.append(_explain_decline(kpi_df, p_kpi_df))
        elif "high" in q or "increase" in q or "spike" in q:
            answers.append(_explain_growth(kpi_df, p_kpi_df))

    if "ai_search" in intents:
        answers.append(_answer_ai_search_strategy())

    if "backlink" in intents:
        answers.append(_answer_backlink_strategy())

    if "competitor" in intents:
        answers.append(_answer_competitor_analysis())

    if "predict" in intents:
        answers.append(_answer_prediction(kpi_df))

    # ── Fallback ─────────────────────────────────────────────────
    if not answers:
        answers.append(_default_summary(utm_df, kpi_df, lead_sources_df))

    return "\n\n---\n\n".join(answers)


# ─────────────────────────────────────────────────────────────────
#  EXPLANATORY ANSWERS
# ─────────────────────────────────────────────────────────────────

def _explain_direct_traffic(utm_df):
    if utm_df is None or utm_df.empty:
        return ""
    direct = utm_df[utm_df["sessionSource"].str.lower().str.contains("direct", na=False)]
    if direct.empty:
        return "No direct traffic to analyze."
    sess = int(direct["sessions"].sum())
    total = int(utm_df["sessions"].sum())
    pct = (sess/total*100) if total > 0 else 0
    return f"""
### ❓ Why is Direct Traffic High?

**Current:** {sess:,} sessions ({pct:.1f}% of all traffic)

**Top causes:**
1. **Bookmarks & returning users** (good — brand strength)
2. **Untracked links** — email clients, Slack, WhatsApp, LinkedIn DMs strip the referrer
3. **Mobile app browsers** — LinkedIn/Twitter/Instagram apps don't pass referrer
4. **Copy-pasted URLs** from PDFs, documents
5. **HTTPS → HTTP referrer loss** (unlikely if you're full HTTPS)

**Fix this week:**
- Add UTM params to all email signatures: `?utm_source=email&utm_medium=signature`
- Add UTM to LinkedIn posts: `?utm_source=linkedin&utm_medium=post`
- Add to newsletter: `?utm_source=newsletter&utm_medium=email`
"""


def _explain_linkedin(utm_df):
    if utm_df is None or utm_df.empty:
        return ""
    li = utm_df[utm_df["sessionSource"].str.lower().str.contains("linkedin", na=False)]
    if li.empty:
        return "No LinkedIn traffic in this period."
    sess = int(li["sessions"].sum())
    conv = int(li["conversions"].sum())
    rate = (conv/sess*100) if sess > 0 else 0
    intent = "🔴 Likely Job Seekers" if rate < 1 else "🟡 Mixed" if rate < 3 else "🟢 Buyers"
    return f"""
### 💼 LinkedIn Traffic Analysis

**Sessions:** {sess:,} | **Conversions:** {conv} | **Rate:** {rate:.2f}%
**Verdict:** {intent}

If conversion rate is low (<1%), LinkedIn visitors are likely:
- Job seekers (clicked your job postings)
- Curious peers/competitors browsing
- People reading your content but not buyers

**Fix:**
- Tag job post URLs: `?utm_campaign=careers`
- Tag product URLs: `?utm_campaign=product`
- Create `/careers` separate landing page
"""


def _explain_decline(kpi_df, p_kpi_df):
    if kpi_df is None or p_kpi_df is None or kpi_df.empty or p_kpi_df.empty:
        return "Need both current + previous data."
    curr = int(kpi_df["signups"].sum())
    prev = int(p_kpi_df["signups"].sum())
    change = ((curr-prev)/prev*100) if prev > 0 else 0
    return f"""
### 📉 Decline Analysis

Sign-ups: {prev} → {curr} ({change:+.1f}%)

**Common causes of decline:**
1. Reduced ad spend / campaign paused
2. Page broken (check /signup, /pricing)
3. SEO ranking dropped (check Search Console)
4. Negative review or PR issue
5. Site speed regression

**Action:** Check GA4 page views for {kpi_df.iloc[0]['date'] if not kpi_df.empty else 'recent dates'} — sudden drops in /signup or /pricing views = funnel issue.
"""


def _explain_growth(kpi_df, p_kpi_df):
    if kpi_df is None or p_kpi_df is None or kpi_df.empty or p_kpi_df.empty:
        return ""
    curr = int(kpi_df["signups"].sum())
    prev = int(p_kpi_df["signups"].sum())
    change = ((curr-prev)/prev*100) if prev > 0 else 0
    return f"""
### 📈 Growth Analysis

Sign-ups: {prev} → {curr} ({change:+.1f}%)

**Likely drivers:**
1. New marketing campaign launched
2. Content went viral / picked up by news
3. SEO ranking improvement
4. New product feature drove word-of-mouth
5. Seasonal demand

**Action:** Identify WHICH source grew most this period (check Lead Sources tab) and double down on it.
"""


def _answer_ai_search_strategy():
    return """
### 🤖 AI Search (ChatGPT, Perplexity, Claude) Strategy

AI models recommend based on EXTERNAL signals, not your SEO:

**Top citations AI trusts:**
1. **Reddit** — r/unrealengine, r/archviz, r/3Dmodeling
2. **G2, Capterra, TrustRadius** — review aggregators
3. **Wikipedia** + comparison articles
4. **Hacker News** + Medium technical posts
5. **Industry press** — ArchDaily, Dezeen, TechCrunch
6. **YouTube transcripts** — tutorials & demos

**30-day plan:**
- Week 1: List on G2, Capterra, Product Hunt
- Week 2: Answer 5 Reddit questions helpfully
- Week 2: Write "Eagle 3D vs Vagon vs Parsec" comparison
- Week 3: Pitch podcast appearances
- Week 4: Get customer case study published
"""


def _answer_backlink_strategy():
    return """
### 🔗 Backlink Strategy

**Free tools to analyze competitors:**
- Ubersuggest (3 searches/day free)
- Ahrefs Backlink Checker (free)
- Moz Link Explorer (10 queries/month free)

**Competitors to analyze:**
- vagon.io, parsec.app, furioos.com, hardvine.com

**60-day goal: 15-20 backlinks**
- Software directories (G2, Capterra): 3-5 links
- Guest posts on industry blogs: 5-7 links
- Sponsor 3 YouTubers/podcasts: 5 links
- Customer case studies: 3 links
"""


def _answer_competitor_analysis():
    return """
### 🥊 Competitor Analysis Quick Wins

**Eagle 3D competitors:**
- Vagon (vagon.io)
- Parsec/Pure Storage (parsec.app)
- Furioos (furioos.com)
- Hardvine (hardvine.com)
- 3D Eye Solutions (3deye.me)

**Action items:**
1. Create comparison page: `/eagle-vs-vagon`, `/eagle-vs-parsec`
2. Identify their backlink sources (use Ahrefs)
3. Find where they're listed (G2, Capterra) — list yourself there too
4. Monitor their pricing/features quarterly
5. Steal their content angles — write better versions
"""


def _answer_prediction(kpi_df):
    if kpi_df is None or kpi_df.empty:
        return "Need historical data to predict."
    daily_avg = kpi_df["signups"].mean()
    next_week = daily_avg * 7
    next_month = daily_avg * 30
    return f"""
### 🔮 Forecast Based on Current Trend

Daily average sign-ups: {daily_avg:.1f}

**Projections:**
- Next 7 days: ~{int(next_week)} sign-ups
- Next 30 days: ~{int(next_month)} sign-ups

**Note:** This is a simple linear projection. Actual numbers depend on marketing activities, seasonality, and external factors.
"""


def _default_summary(utm_df, kpi_df, lead_sources_df):
    parts = ["### 🤔 Here's a summary of your data:\n"]

    if kpi_df is not None and not kpi_df.empty:
        s = int(kpi_df["signups"].sum())
        u = int(kpi_df["first_uploads"].sum())
        p = int(kpi_df["paid_customers"].sum())
        parts.append(f"**CRM:** {s} signups, {u} uploads, {p} paid customers")

    if utm_df is not None and not utm_df.empty:
        total = int(utm_df["sessions"].sum())
        sources = utm_df["sessionSource"].nunique()
        parts.append(f"**GA4:** {total:,} sessions from {sources} sources")

    if lead_sources_df is not None and not lead_sources_df.empty:
        top = lead_sources_df.iloc[0]["Lead Source"]
        parts.append(f"**Top Lead Source:** {top}")

    parts.append("\n**Try asking:**")
    parts.append("- 'How many signups today?'")
    parts.append("- 'Why is direct traffic so high?'")
    parts.append("- 'What's the conversion rate?'")
    parts.append("- 'Compare signups to previous period'")
    parts.append("- 'Where are signups coming from?'")
    parts.append("- 'How can I rank in AI search?'")
    parts.append("- 'Tell me about google traffic'")

    return "\n".join(parts)

