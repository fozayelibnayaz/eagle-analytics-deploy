"""
Strategic Q&A Engine - Eagle 3D KPI System
Answers business questions automatically from GA4 + KPI data
Inspired by team meeting questions: backlinks, direct traffic, LinkedIn intent, etc.
"""

import pandas as pd
from datetime import datetime


def answer_direct_traffic_high(utm_df, kpi_df=None):
    """Q: Why is direct traffic so high?"""
    if utm_df.empty:
        return "No data available to analyze."

    direct = utm_df[utm_df["sessionSource"].str.lower().isin(["(direct)", "direct"])]
    total_sess = float(utm_df["sessions"].sum())
    direct_sess = float(direct["sessions"].sum()) if not direct.empty else 0
    pct = (direct_sess / total_sess * 100) if total_sess > 0 else 0

    direct_conv = float(direct["conversions"].sum()) if not direct.empty else 0
    direct_users = float(direct["totalUsers"].sum()) if not direct.empty else 0
    conv_rate = (direct_conv / direct_sess * 100) if direct_sess > 0 else 0

    return f"""
### 🔍 Why is Direct Traffic So High?

**Current Direct Traffic:** {int(direct_sess):,} sessions ({pct:.1f}% of total)
**Direct Users:** {int(direct_users):,} | **Conversions:** {int(direct_conv)} | **Conv. Rate:** {conv_rate:.2f}%

**Most likely causes (in order):**

1. **Bookmarks & Returning Visitors** — Users who saved your site and return directly. This is GOOD for brand strength.

2. **Untracked Referrals** — Major sources NOT sending UTM parameters:
   - Email clients (Gmail, Outlook) often strip referrer
   - Slack, Discord, WhatsApp messages → appear as "direct"
   - PDFs or documents linking to your site
   - LinkedIn DMs and in-app browser (mobile especially)

3. **HTTPS → HTTP Issue** — If any inbound link comes from HTTPS site to HTTP, referrer is dropped (unlikely if you're HTTPS)

4. **Mobile App Browsers** — Twitter/LinkedIn in-app browsers often hide referrer

**What to do:**

✅ Add UTM parameters to ALL outbound links you control:
   - Email signatures: `?utm_source=email&utm_medium=signature`
   - LinkedIn posts: `?utm_source=linkedin&utm_medium=post&utm_campaign=brand`
   - Newsletter: `?utm_source=newsletter&utm_medium=email&utm_campaign=monthly`

✅ Set up GA4 "Referral Exclusion" for your own subdomains

✅ Check if {conv_rate:.1f}% conversion rate from direct = high quality returning users (good sign of brand awareness)
"""


def answer_linkedin_intent(utm_df, event_df=None):
    """Q: Is LinkedIn traffic from job seekers or potential customers?"""
    if utm_df.empty:
        return "No data available to analyze."

    li = utm_df[utm_df["sessionSource"].str.lower().str.contains("linkedin", na=False)]
    if li.empty:
        return "No LinkedIn traffic detected in this period."

    li_sess = float(li["sessions"].sum())
    li_users = float(li["totalUsers"].sum())
    li_conv = float(li["conversions"].sum())
    li_new = float(li["newUsers"].sum())
    conv_rate = (li_conv / li_sess * 100) if li_sess > 0 else 0
    new_pct = (li_new / li_users * 100) if li_users > 0 else 0

    # Check Jobrite presence
    jobrite = utm_df[utm_df["sessionSource"].str.lower().str.contains("jobrite", na=False)]
    jobrite_sess = float(jobrite["sessions"].sum()) if not jobrite.empty else 0

    # Score
    intent = "🔴 Likely Job Seekers" if conv_rate < 1 else "🟡 Mixed" if conv_rate < 3 else "🟢 Likely Buyers"

    return f"""
### 💼 LinkedIn Traffic Analysis — Job Seekers vs Buyers?

**LinkedIn Traffic:** {int(li_sess):,} sessions | {int(li_users):,} users | {int(li_conv)} conversions
**Conversion Rate:** {conv_rate:.2f}%
**New User Ratio:** {new_pct:.1f}%
**Intent Verdict:** {intent}

**Jobrite.AI Co-traffic:** {int(jobrite_sess):,} sessions

**Analysis:**

{('✅ HIGH-INTENT INDICATOR: ' + f'{conv_rate:.2f}% conversion rate suggests these are real prospects, not job seekers.') if conv_rate >= 2 else ('⚠️ LOW-INTENT INDICATOR: ' + f'{conv_rate:.2f}% conversion rate is very low. Most LinkedIn visitors are likely browsing — possibly job seekers or curious peers, not buyers.')}

{('⚠️ Jobrite correlation detected: ' + f'{int(jobrite_sess):,} Jobrite sessions suggest your job postings ARE driving LinkedIn traffic. These visitors are looking for jobs, not products.') if jobrite_sess > 0 else '✅ No Jobrite traffic — LinkedIn visitors not from job posts.'}

**How to differentiate (action items):**

1. **Add separate UTM tags** to:
   - LinkedIn company posts: `utm_campaign=product`
   - Job posting links: `utm_campaign=careers`

2. **Track which pages they visit:**
   - If they visit /pricing or /features → BUYERS
   - If they visit /careers or /about → JOB SEEKERS

3. **Separate landing pages:**
   - Job post traffic → /jobs (don't pollute conversion data)
   - Product posts → /demo

4. **Add LinkedIn Insight Tag** to your site for retargeting + B2B intent signals
"""


def answer_top_pages_for_signup(pages_df, kpi_df=None):
    """Q: Which pages drive the most sign-ups?"""
    if pages_df.empty:
        return "No page data available."

    converting = pages_df[pages_df["conversions"] > 0].copy()
    if converting.empty:
        return """
### 📝 Top Pages Driving Sign-ups

⚠️ **No pages tracked any conversions in GA4 for this period.**

**Fix this immediately:**

1. **Set up GA4 conversion events** for:
   - Sign-up form submission (`sign_up`)
   - Demo request (`demo_request`)
   - Trial start (`trial_start`)
   - Contact form (`form_submit`)

2. **In GA4 Admin → Events → Mark as conversion:**
   Enable conversion tracking for the events above

3. **GTM Setup needed** on:
   - https://eagle3dstreaming.com/signup (or your registration page)
   - https://controlpanel.eagle3dstreaming.com (post-signup landing)

Once conversions are tracked, this analysis will show which pages drive signups.
"""

    top = converting.groupby("pagePath").agg(
        views=("screenPageViews","sum"),
        sessions=("sessions","sum"),
        conversions=("conversions","sum"),
    ).reset_index().sort_values("conversions",ascending=False).head(10)

    top["conv_rate"] = (top["conversions"] / top["sessions"].replace(0,1) * 100).round(2)

    lines = ["### 📝 Top Pages Driving Sign-ups", "", "| Page | Views | Conversions | Conv. Rate |", "|---|---|---|---|"]
    for _, r in top.iterrows():
        lines.append(f"| `{r['pagePath']}` | {int(r['views']):,} | {int(r['conversions'])} | {r['conv_rate']:.2f}% |")

    lines.append("")
    lines.append(f"**Top converter:** `{top.iloc[0]['pagePath']}` with {int(top.iloc[0]['conversions'])} conversions")
    lines.append("")
    lines.append("**Action items:**")
    lines.append(f"- Drive MORE traffic to `{top.iloc[0]['pagePath']}` — it converts at {top.iloc[0]['conv_rate']:.2f}%")
    lines.append("- Replicate what works on this page across underperforming pages")

    return "\n".join(lines)


def answer_seo_health(pages_df, utm_df):
    """Q: How is our SEO performing?"""
    organic = utm_df[utm_df["sessionMedium"].str.lower() == "organic"] if not utm_df.empty else pd.DataFrame()

    if organic.empty:
        return "### 🔍 SEO Health\n\nNo organic traffic data available."

    org_sess = float(organic["sessions"].sum())
    org_conv = float(organic["conversions"].sum())
    total_sess = float(utm_df["sessions"].sum())
    org_share = (org_sess / total_sess * 100) if total_sess > 0 else 0
    org_conv_rate = (org_conv / org_sess * 100) if org_sess > 0 else 0

    # Top organic sources
    by_src = organic.groupby("sessionSource").agg(
        sessions=("sessions","sum"),
        conversions=("conversions","sum")
    ).sort_values("sessions",ascending=False).head(5)

    src_lines = []
    for src, row in by_src.iterrows():
        src_lines.append(f"   - **{src}**: {int(row['sessions']):,} sessions, {int(row['conversions'])} conversions")

    return f"""
### 🔍 SEO & Organic Search Health

**Total Organic Sessions:** {int(org_sess):,} ({org_share:.1f}% of all traffic)
**Organic Conversions:** {int(org_conv)} | **Conv. Rate:** {org_conv_rate:.2f}%

**Top Organic Sources:**
{chr(10).join(src_lines)}

**SEO Verdict:**
{('🟢 STRONG SEO: ' + f'{org_share:.1f}% organic share is healthy. Continue current strategy.') if org_share > 30 else ('🟡 GROWING SEO: ' + f'{org_share:.1f}% organic. Room to grow with more content + backlinks.') if org_share > 15 else ('🔴 WEAK SEO: ' + f'Only {org_share:.1f}% organic. Major opportunity to invest in SEO content + technical optimization.')}

**Specific Actions (from team's discussion):**

1. **Backlinks (critical)** — Last backlink was 2022. Goal: get 3 new high-DA backlinks per month:
   - Guest post on Unreal Engine blogs
   - Submit to G2, Capterra, Product Hunt
   - Partner with 3D archviz studios for reciprocal links

2. **Meta Titles/Descriptions** — Mark Rafshan is preparing these. Get them deployed ASAP.

3. **Fix H1/H2 tags** — "Develop wants to run everywhere" doesn't match search intent. Test variants like:
   - "Interactive 3D Streaming for Architects & Real Estate"
   - "Pixel Streaming Made Simple — No GPU Required"

4. **Content for AI search** — Create:
   - Detailed comparison pages (Eagle vs Vagon vs ParsecCloud)
   - Reddit answers on r/unrealengine and r/archviz
   - LinkedIn long-form articles with case studies
"""


def answer_ai_recommendation_criteria():
    """Q: Identify AI recommendation criteria and report findings."""
    return """
### 🤖 AI Search Recommendation Criteria — How to Rank

**Why your site doesn't appear in AI search (ChatGPT, Perplexity, Claude):**

AI models recommend brands based on **external signals**, not internal SEO. Here's what they look for:

#### 1. **Citation Sources AI Models Trust:**
   - **Reddit** (massive influence on AI training data)
     - r/unrealengine, r/archviz, r/3Dmodeling, r/architecture
     - Action: Active, helpful presence — answer questions, don't spam
   - **GitHub** — code repos, sample projects, docs
   - **Hacker News** — case studies, technical posts
   - **Stack Overflow** — answer 3D streaming questions
   - **Wikipedia** — backlinks from related articles
   - **Quora** — long-form expert answers
   - **Medium / Dev.to** — technical articles

#### 2. **Press & Industry Mentions:**
   - TechCrunch, The Verge, Engadget (one mention = huge AI boost)
   - Industry-specific: ArchDaily, Dezeen, ArchitectMagazine
   - Podcast appearances (transcribed = indexed by AI)

#### 3. **Comparison Content (BIGGEST OPPORTUNITY):**
   When users ask "best pixel streaming platform," AI looks for:
   - Comparison articles (Eagle vs X)
   - "Top 10 X" listicles that include you
   - Reviews on G2, Capterra, TrustRadius, Software Advice

#### 4. **Structured Data + Schema:**
   - Add Schema.org markup: `Product`, `SoftwareApplication`, `Review`
   - AI scrapers parse this directly

#### 5. **Content Format AI Loves:**
   - Long-form pillar pages (3000+ words)
   - FAQ pages with question-format headers
   - Glossaries (define industry terms)
   - Tutorial content with step-by-step screenshots

### 30-Day AI Visibility Action Plan:

| Week | Action | Outcome |
|---|---|---|
| 1 | Get listed on G2, Capterra, Trustpilot, Product Hunt | Review-site backlinks |
| 2 | Post 5 detailed answers on Reddit (helpful, not promotional) | Reddit signal boost |
| 2 | Write "Eagle 3D vs [Top 3 Competitors]" comparison page | Comparison ranking |
| 3 | Pitch 3 podcast guest appearances on 3D/Unreal podcasts | Transcript indexing |
| 3 | Submit to Hacker News with case study | News.YC backlink |
| 4 | Get 1 paid customer to publish case study + share on LinkedIn | Social proof |
| 4 | Add Schema markup (SoftwareApplication, Review, Organization) | Structured data |

After 30 days, retest AI search with: "best pixel streaming platform for architects"
"""


def answer_competitor_backlinks():
    """Q: Check competitors' backlinks and report what they did."""
    return """
### 🔗 Competitor Backlink Strategy Analysis

**How to analyze competitor backlinks (free tools):**

1. **Ubersuggest** (free tier — 3 searches/day)
   - Enter competitor domain
   - View "Backlinks" report
   - Sort by Domain Authority

2. **Ahrefs Backlink Checker** (free version)
   - https://ahrefs.com/backlink-checker
   - Shows top 100 backlinks per domain

3. **Moz Link Explorer** (free signup)
   - 10 queries/month free
   - Excellent for DA-weighted analysis

### Competitors to Analyze (Eagle 3D Industry):
- **Vagon** (vagon.io)
- **Parsec / Pure Storage** (parsec.app)
- **Furioos** (furioos.com)
- **Hardvine** (hardvine.com)
- **3D Eye Solutions** (3deye.me)

### Common Competitor Backlink Sources (likely findings):

1. **Software Review Sites:**
   - G2.com, Capterra.com, GetApp.com, SoftwareAdvice.com
   - **ACTION**: Get listed on all 4 within 7 days

2. **Industry Publications:**
   - ArchDaily, Dezeen, World Architecture News
   - **ACTION**: Pitch guest articles on "How 3D streaming changes architectural presentation"

3. **Unreal Engine Marketplace + Forums:**
   - Unreal Engine Marketplace listings
   - Unreal Engine forum signatures
   - **ACTION**: Submit Eagle plugin/connector to UE Marketplace

4. **YouTube Video Descriptions:**
   - Tutorial videos with backlinks in description
   - **ACTION**: Sponsor 5 small Unreal YouTubers (cheap, high impact)

5. **Reddit + Forum Mentions:**
   - r/unrealengine, r/archviz, r/architecture
   - **ACTION**: Engaged community presence, not promotional spam

### 60-Day Backlink Goal:
- Week 1-2: G2 + Capterra + Product Hunt listings (3 backlinks)
- Week 3-4: Pitch 10 guest posts to industry blogs (3-5 will accept)
- Week 5-6: Sponsor 3 YouTubers + 2 podcasts (5 backlinks)
- Week 7-8: Case studies + customer testimonials (3 backlinks)

**Total target: 15-20 quality backlinks in 60 days**
"""


def get_all_strategic_questions():
    """Return list of all available strategic questions."""
    return [
        ("🤔 Why is direct traffic so high?", "direct_traffic"),
        ("💼 Is LinkedIn traffic from buyers or job seekers?", "linkedin_intent"),
        ("📝 Which pages drive the most sign-ups?", "top_pages_signup"),
        ("🔍 How is our SEO performing?", "seo_health"),
        ("🤖 How to rank in AI search (ChatGPT, Perplexity)?", "ai_recommendation"),
        ("🔗 Competitor backlink strategy", "competitor_backlinks"),
    ]


def answer_question(question_key, utm_df=None, pages_df=None, events_df=None, kpi_df=None):
    """Route question to appropriate answer function."""
    handlers = {
        "direct_traffic":       lambda: answer_direct_traffic_high(utm_df, kpi_df),
        "linkedin_intent":      lambda: answer_linkedin_intent(utm_df, events_df),
        "top_pages_signup":     lambda: answer_top_pages_for_signup(pages_df, kpi_df),
        "seo_health":           lambda: answer_seo_health(pages_df, utm_df),
        "ai_recommendation":    lambda: answer_ai_recommendation_criteria(),
        "competitor_backlinks": lambda: answer_competitor_backlinks(),
    }
    handler = handlers.get(question_key)
    return handler() if handler else "Question not found."

