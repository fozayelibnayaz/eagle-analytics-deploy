
-- LINKEDIN ANALYTICS TABLES
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- POSTS (latest snapshot, upserted by URN/hash)
DROP TABLE IF EXISTS linkedin_posts CASCADE;
CREATE TABLE linkedin_posts (
    urn               TEXT PRIMARY KEY,
    title             TEXT,
    post_type         TEXT,
    audience          TEXT,
    published_at      TIMESTAMPTZ,
    impressions       INTEGER DEFAULT 0,
    views             INTEGER DEFAULT 0,
    clicks            INTEGER DEFAULT 0,
    ctr               NUMERIC DEFAULT 0,
    reactions         INTEGER DEFAULT 0,
    comments          INTEGER DEFAULT 0,
    reposts           INTEGER DEFAULT 0,
    follows           INTEGER DEFAULT 0,
    engagement_rate   NUMERIC DEFAULT 0,
    url               TEXT,
    first_seen        TIMESTAMPTZ DEFAULT NOW(),
    last_updated      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_li_posts_pub ON linkedin_posts(published_at DESC);

-- POSTS DAILY HISTORY (one row per post per day - tracks growth)
DROP TABLE IF EXISTS linkedin_posts_daily CASCADE;
CREATE TABLE linkedin_posts_daily (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_urn          TEXT NOT NULL,
    snapshot_date     DATE NOT NULL,
    impressions       INTEGER DEFAULT 0,
    clicks            INTEGER DEFAULT 0,
    reactions         INTEGER DEFAULT 0,
    comments          INTEGER DEFAULT 0,
    reposts           INTEGER DEFAULT 0,
    engagement_rate   NUMERIC DEFAULT 0,
    delta_impressions INTEGER DEFAULT 0,
    delta_reactions   INTEGER DEFAULT 0,
    delta_comments    INTEGER DEFAULT 0,
    captured_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(post_urn, snapshot_date)
);
CREATE INDEX idx_li_posts_daily_urn ON linkedin_posts_daily(post_urn);
CREATE INDEX idx_li_posts_daily_date ON linkedin_posts_daily(snapshot_date DESC);

-- FOLLOWERS DAILY
DROP TABLE IF EXISTS linkedin_followers_daily CASCADE;
CREATE TABLE linkedin_followers_daily (
    snapshot_date  DATE PRIMARY KEY,
    total          INTEGER DEFAULT 0,
    organic_gains  INTEGER DEFAULT 0,
    paid_gains     INTEGER DEFAULT 0,
    delta_total    INTEGER DEFAULT 0,
    captured_at    TIMESTAMPTZ DEFAULT NOW()
);

-- VISITORS DAILY
DROP TABLE IF EXISTS linkedin_visitors_daily CASCADE;
CREATE TABLE linkedin_visitors_daily (
    snapshot_date     DATE PRIMARY KEY,
    page_views        INTEGER DEFAULT 0,
    unique_visitors   INTEGER DEFAULT 0,
    custom_button     INTEGER DEFAULT 0,
    delta_views       INTEGER DEFAULT 0,
    captured_at       TIMESTAMPTZ DEFAULT NOW()
);

-- COMPETITORS DAILY
DROP TABLE IF EXISTS linkedin_competitors_daily CASCADE;
CREATE TABLE linkedin_competitors_daily (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    snapshot_date     DATE NOT NULL,
    name              TEXT NOT NULL,
    followers         INTEGER DEFAULT 0,
    follower_growth   TEXT,
    post_engagements  INTEGER DEFAULT 0,
    engagement_rate   TEXT,
    posts             INTEGER DEFAULT 0,
    captured_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(snapshot_date, name)
);

-- NEWSLETTER ARTICLES
DROP TABLE IF EXISTS linkedin_newsletter_articles CASCADE;
CREATE TABLE linkedin_newsletter_articles (
    urn            TEXT PRIMARY KEY,
    title          TEXT,
    published_at   TIMESTAMPTZ,
    views          INTEGER DEFAULT 0,
    reactions      INTEGER DEFAULT 0,
    comments       INTEGER DEFAULT 0,
    shares         INTEGER DEFAULT 0,
    last_updated   TIMESTAMPTZ DEFAULT NOW()
);

-- SEARCH APPEARANCES
DROP TABLE IF EXISTS linkedin_search_keywords CASCADE;
CREATE TABLE linkedin_search_keywords (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    snapshot_date   DATE NOT NULL,
    keyword         TEXT NOT NULL,
    count           INTEGER DEFAULT 0,
    captured_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(snapshot_date, keyword)
);

-- HIGHLIGHTS DAILY SNAPSHOT (totals from each page)
DROP TABLE IF EXISTS linkedin_highlights_daily CASCADE;
CREATE TABLE linkedin_highlights_daily (
    snapshot_date         DATE PRIMARY KEY,
    impressions           INTEGER DEFAULT 0,
    reactions             INTEGER DEFAULT 0,
    comments              INTEGER DEFAULT 0,
    reposts               INTEGER DEFAULT 0,
    clicks                INTEGER DEFAULT 0,
    page_views            INTEGER DEFAULT 0,
    unique_visitors       INTEGER DEFAULT 0,
    total_followers       INTEGER DEFAULT 0,
    newsletter_subscribers INTEGER DEFAULT 0,
    captured_at           TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE linkedin_posts                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE linkedin_posts_daily           ENABLE ROW LEVEL SECURITY;
ALTER TABLE linkedin_followers_daily       ENABLE ROW LEVEL SECURITY;
ALTER TABLE linkedin_visitors_daily        ENABLE ROW LEVEL SECURITY;
ALTER TABLE linkedin_competitors_daily     ENABLE ROW LEVEL SECURITY;
ALTER TABLE linkedin_newsletter_articles   ENABLE ROW LEVEL SECURITY;
ALTER TABLE linkedin_search_keywords       ENABLE ROW LEVEL SECURITY;
ALTER TABLE linkedin_highlights_daily      ENABLE ROW LEVEL SECURITY;
