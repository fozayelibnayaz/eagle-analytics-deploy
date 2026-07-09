"""
source_normalizer.py — Intelligent Lead Source Normalization
=============================================================
Normalizes lead source strings from CRM (Verified_FREE Lead Source field)
and GA4 (sessionSource) into canonical names.

Problems solved:
  - "Google", "google", "Google Search", "Google search", "GOOGLE", 
    "Google, Instagram", "(Not Specified)" etc. all need to be unified
  - "Linkedin" / "linkedin" / "LinkedIn" / "LinkedIn" → one canonical
  - "Youtube" / "youtube" / "YOUTUBE" / "YouTube" → one canonical
  - "ai" / "AI" / "Ai" → one canonical  
  - "bob" / "Bob" / "alice" etc. are test/sample entries
  - Google Console / Google Search Console / Google Search → "Google"
  - "from the designer", "e3ds", "both" etc. → mapped intelligently

Architecture:
  TIER 1: Exact fuzzy match against known canonical map
  TIER 2: Keyword-based classification
  TIER 3: Pattern detection (AI tools, search engines, social)
  TIER 4: Unknown — kept as-is but flagged
"""

import re
from typing import Tuple

# ══════════════════════════════════════════════════════════════
# CANONICAL MAP — all known variants mapped to canonical name
# ══════════════════════════════════════════════════════════════

# Format: {canonical_name: [list of known variants (lowercase)]}
CANONICAL_MAP = {
    "Google": [
        "google", "google search", "google search console", "google console",
        "google search cosoe", "google console", "googlesearch",
        "google.com", "www.google.com", "google search console (gsc)",
        "google seo", "google organic", "google, instagram",
        "google search console (seo tool)",
        "google ads", "google adwords", "google ad",
    ],
    "LinkedIn": [
        "linkedin", "linkedin.com", "www.linkedin.com", "lnkd.in",
        "linkedin post", "linkedin ad", "linkedin article",
        "linkedin recommendation", "linkedin group", "linkedin message",
    ],
    "YouTube": [
        "youtube", "youtube.com", "www.youtube.com", "youtu.be",
        "youtube video", "youtube ad", "youtube channel",
        "youtube tutorial", "youtube recommendation",
    ],
    "Instagram": [
        "instagram", "instagram.com", "www.instagram.com",
        "instagram ad", "instagram post", "instagram story",
        "instagram reel", "ig", "insta",
    ],
    "Facebook": [
        "facebook", "facebook.com", "www.facebook.com",
        "facebook ad", "facebook post", "facebook group", "fb", "meta",
    ],
    "Twitter/X": [
        "twitter", "twitter.com", "www.twitter.com", "x.com",
        "x", "tweet", "twitter ad", "t.co",
    ],
    "AI Tools": [
        "ai", "ai tools", "ai search", "chatgpt", "chatgpt.com",
        "gpt", "gpt-4", "openai", "perplexity", "perplexity.ai",
        "claude", "claude.ai", "claude research", "claude's research",
        "gemini", "bard", "google gemini", "bard.google.com",
        "copilot", "bing copilot", "microsoft copilot",
        "ai recommendation", "ai assistant", "ai chat",
    ],
    "Reddit": [
        "reddit", "reddit.com", "www.reddit.com",
        "reddit post", "reddit thread", "reddit ad",
    ],
    "Direct/Bookmark": [
        "direct", "(direct)", "(none)", "(not set)", "(not specified)",
        "(Not Specified)", "bookmark", "typed", "none",
        "not specified", "not set", "",
    ],
    "Email/Newsletter": [
        "email", "newsletter", "mail", "email marketing",
        "mailchimp", "mail campaign", "email campaign",
        "sendgrid", "hubspot email",
    ],
    "Internal": [
        "internal", "test", "demo", "sample", "staff", "team",
        "employee", "eagle3d", "e3ds", "eagle", "eagle 3d",
        "eagle3dstreaming", "eagle3d streaming", "from the designer",
        "from designer", "developer", "already customer, additional account",
        "both", "l", "internal test", "e3ds internal",
    ],
    "Referral": [
        "referral", "refer", "referred", "friend", "colleague",
        "word of mouth", "recommendation", "recommend", "recommended",
        "associate", "amigo", "from a friend", "peer recommendation",
    ],
    "Bing": [
        "bing", "bing.com", "www.bing.com", "bing search",
        "bing organic", "microsoft bing",
    ],
    "DuckDuckGo": [
        "duckduckgo", "duckduckgo.com", "ddg",
    ],
    "Quora": [
        "quora", "quora.com", "www.quora.com",
    ],
    "Medium/Blog": [
        "medium", "medium.com", "blog", "blog post", "article",
        "dev.to", "devto", "hashnode",
    ],
    "Product Hunt": [
        "product hunt", "producthunt", "producthunt.com",
    ],
    "Review Sites": [
        "g2", "g2.com", "capterra", "capterra.com", "trustpilot",
        "software advice", "softwareadvice", "g2 crowd",
    ],
    "WhatsApp": [
        "whatsapp", "whatsapp.com", "wa.me",
    ],
    "Discord": [
        "discord", "discord.com", "discord.gg",
    ],
    "Telegram": [
        "telegram", "telegram.org", "t.me",
    ],
    "Slack": [
        "slack", "slack.com",
    ],
    "GitHub": [
        "github", "github.com", "stackoverflow", "stack overflow",
    ],
    "Hacker News": [
        "hacker news", "hackernews", "news.ycombinator.com", "hn",
    ],
}

# ══════════════════════════════════════════════════════════════
# Test/Sample entry detection
# ══════════════════════════════════════════════════════════════

TEST_PATTERNS = [
    r'^bob$', r'^alice$', r'^test', r'^demo', r'^sample', r'^fake',
    r'^asdf', r'^qwerty', r'^xxx', r'^abc123', r'^aaa@',
    r'^developer$', r'^the designer$',
]

def is_test_entry(source: str) -> bool:
    """Check if this looks like a test/sample/fake entry."""
    s = (source or "").strip().lower()
    if not s:
        return False
    for pattern in TEST_PATTERNS:
        if re.match(pattern, s):
            return True
    return False


# ══════════════════════════════════════════════════════════════
# NORMALIZATION ENGINE
# ══════════════════════════════════════════════════════════════

def normalize_source(source: str) -> Tuple[str, str]:
    """
    Normalize a lead source string.
    
    Returns:
        (canonical_name, category)
        category is one of: "search", "social", "ai", "referral", 
                           "direct", "email", "internal", "paid",
                           "community", "review", "messaging", "unknown"
    
    Examples:
        "Google Search" → ("Google", "search")
        "linkedin" → ("LinkedIn", "social")
        "Gemini" → ("AI Tools", "ai")
        "chatgpt" → ("AI Tools", "ai")
        "(Not Specified)" → ("Direct/Bookmark", "direct")
        "recommendation" → ("Referral", "referral")
        "bob" → ("Internal", "internal")
        "e3ds" → ("Internal", "internal")
    """
    if not source or not str(source).strip():
        return "Direct/Bookmark", "direct"
    
    raw = str(source).strip()
    s = raw.lower().strip()
    
    # Remove common prefixes/suffixes
    s = re.sub(r'^(from\s+|via\s+|through\s+)', '', s)
    s = re.sub(r'(\s+search$|\s+seo$)', '', s)
    
    # ── TIER 1: Exact match against canonical map ───────────────
    for canonical, variants in CANONICAL_MAP.items():
        if s in variants:
            return canonical, _get_category(canonical)
        # Also check if raw (case-insensitive) matches
        if s == canonical.lower():
            return canonical, _get_category(canonical)
    
    # ── TIER 1b: Contains match (for compound sources) ──────────
    # "Google, Instagram" → Google is primary, note both
    for canonical, variants in CANONICAL_MAP.items():
        for variant in variants:
            if variant in s and len(variant) >= 4:  # avoid short matches
                return canonical, _get_category(canonical)
    
    # ── TIER 2: Keyword-based classification ────────────────────
    # AI tools
    ai_keywords = ["chatgpt", "gpt", "claude", "gemini", "perplexity", 
                    "openai", "bard", "copilot", "ai search", "ai tool",
                    "ai recommend"]
    for kw in ai_keywords:
        if kw in s:
            return "AI Tools", "ai"
    
    # Search engines
    search_keywords = ["google", "bing", "yahoo", "duckduckgo", "baidu", 
                       "yandex", "search engine", "seo"]
    for kw in search_keywords:
        if kw in s:
            return "Google", "search"  # default search to Google if ambiguous
    
    # Social media
    social_keywords = ["linkedin", "facebook", "instagram", "twitter", 
                       "youtube", "tiktok", "pinterest", "snapchat",
                       "reddit", "tumblr", "weibo", "threads"]
    for kw in social_keywords:
        if kw in s:
            canonical_map = {
                "linkedin": "LinkedIn", "facebook": "Facebook",
                "instagram": "Instagram", "twitter": "Twitter/X",
                "youtube": "YouTube", "tiktok": "TikTok",
                "pinterest": "Pinterest", "reddit": "Reddit",
                "threads": "Threads",
            }
            return canonical_map.get(kw, "Social Media"), "social"
    
    # Email/newsletter
    email_keywords = ["email", "newsletter", "mail", "campaign"]
    for kw in email_keywords:
        if kw in s:
            return "Email/Newsletter", "email"
    
    # Referral
    referral_keywords = ["recommend", "referral", "friend", "colleague",
                         "word of mouth", "associate", "peer", "amigo"]
    for kw in referral_keywords:
        if kw in s:
            return "Referral", "referral"
    
    # Internal/test
    internal_keywords = ["internal", "test", "demo", "eagle3d", "e3ds",
                         "eagle", "developer", "designer", "staff",
                         "employee", "sample", "fake"]
    for kw in internal_keywords:
        if kw in s:
            return "Internal", "internal"
    
    # ── TIER 3: Test entry detection ────────────────────────────
    if is_test_entry(s):
        return "Internal", "internal"
    
    # ── TIER 4: Unknown — keep original (title-cased) ───────────
    return raw.title(), "unknown"


def _get_category(canonical: str) -> str:
    """Get the category for a canonical source name."""
    categories = {
        "Google": "search",
        "Bing": "search",
        "DuckDuckGo": "search",
        "LinkedIn": "social",
        "YouTube": "social",
        "Instagram": "social",
        "Facebook": "social",
        "Twitter/X": "social",
        "Reddit": "community",
        "Discord": "messaging",
        "Telegram": "messaging",
        "WhatsApp": "messaging",
        "Slack": "messaging",
        "AI Tools": "ai",
        "Direct/Bookmark": "direct",
        "Email/Newsletter": "email",
        "Internal": "internal",
        "Referral": "referral",
        "Quora": "community",
        "Medium/Blog": "community",
        "Product Hunt": "community",
        "Review Sites": "review",
        "GitHub": "community",
        "Hacker News": "community",
    }
    return categories.get(canonical, "unknown")


def normalize_dataframe_sources(df, source_col="Lead Source"):
    """
    Normalize all source values in a DataFrame.
    Adds columns: 'Source_Normalized', 'Source_Category'
    """
    if df is None or df.empty:
        return df
    
    df = df.copy()
    
    if source_col not in df.columns:
        return df
    
    normalized = []
    categories = []
    
    for val in df[source_col]:
        if pd.isna(val) if hasattr(val, '__class__') and val.__class__.__name__ == 'NAType' else not val:
            canonical, cat = "Direct/Bookmark", "direct"
        else:
            canonical, cat = normalize_source(str(val))
        normalized.append(canonical)
        categories.append(cat)
    
    df["Source_Normalized"] = normalized
    df["Source_Category"] = categories
    
    return df


# Import pandas conditionally
try:
    import pandas as pd
except ImportError:
    pass


def aggregate_normalized_sources(df, source_col="Lead Source"):
    """
    Group by normalized source and aggregate counts.
    Returns DataFrame with: Source_Normalized, Source_Category, Signups, % of Total
    """
    if df is None or df.empty:
        return df
    
    df = normalize_dataframe_sources(df, source_col)
    
    # Fill NaN/empty sources
    df[source_col] = df[source_col].fillna("").replace("", "(Not Specified)")
    
    # Re-normalize after fill
    normalized = []
    categories = []
    for val in df[source_col]:
        canonical, cat = normalize_source(str(val))
        normalized.append(canonical)
        categories.append(cat)
    df["Source_Normalized"] = normalized
    df["Source_Category"] = categories
    
    # Group by normalized source
    grouped = (
        df.groupby(["Source_Normalized", "Source_Category"])
        .size()
        .reset_index(name="Signups")
        .sort_values("Signups", ascending=False)
    )
    
    total = grouped["Signups"].sum()
    grouped["% of Total"] = (grouped["Signups"] / total * 100).round(2) if total > 0 else 0
    
    # Rename for display
    grouped = grouped.rename(columns={"Source_Normalized": "Lead Source"})
    grouped = grouped[["Lead Source", "Source_Category", "Signups", "% of Total"]].reset_index(drop=True)
    
    return grouped


if __name__ == "__main__":
    # Test with the exact variants from the user's list
    test_sources = [
        "(Not Specified)", "Google", "Google Search", "Linkedin", "Gemini",
        "youtube", "Google search", "linkedin", "gpt", "Claude's research",
        "Bob", "Developer", "Claude", "Already customer, additional account",
        "AI", "YOUTUBE", "LinkedIn", "Google, Instagram", "Associate",
        "Youtube", "ai", "alice", "amigo", "from the designer", "e3ds",
        "both", "bob", "l", "internal", "recommendation", "Google Search Cosoe",
        "s", "Google Search Console",
    ]
    
    print("=" * 70)
    print("SOURCE NORMALIZATION TEST")
    print("=" * 70)
    
    for source in test_sources:
        canonical, category = normalize_source(source)
        print(f"  '{source:45s}' → {canonical:20s} ({category})")
    
    print("\n" + "=" * 70)
    print("DEDUPLICATION SUMMARY")
    print("=" * 70)
    
    # Show how many map to same canonical
    from collections import Counter
    results = [normalize_source(s)[0] for s in test_sources]
    counts = Counter(results)
    for name, count in counts.most_common():
        print(f"  {name}: {count} entries")
