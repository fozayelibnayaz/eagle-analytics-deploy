-- ACCESS CONTROL + CUSTOMER SUCCESS TABLES
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ACCESS CONTROL
CREATE TABLE IF NOT EXISTS access_control (
    email          TEXT PRIMARY KEY,
    role           TEXT DEFAULT 'viewer',
    added_by       TEXT,
    notes          TEXT,
    is_active      BOOLEAN DEFAULT TRUE,
    added_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW(),
    removed_by     TEXT,
    removed_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_access_active ON access_control(is_active);

-- ACCESS LOG
CREATE TABLE IF NOT EXISTS access_log (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email      TEXT NOT NULL,
    action     TEXT,
    success    BOOLEAN,
    ip         TEXT,
    timestamp  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_access_log_email ON access_log(email);
CREATE INDEX IF NOT EXISTS idx_access_log_ts ON access_log(timestamp DESC);

-- CUSTOMER SUCCESS MASTER (raw rows from all tabs of CS sheet)
CREATE TABLE IF NOT EXISTS customer_success_master (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tab_name    TEXT,
    tab_slug    TEXT,
    email       TEXT,
    row_data    JSONB,
    scraped_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cs_tab ON customer_success_master(tab_slug);
CREATE INDEX IF NOT EXISTS idx_cs_email ON customer_success_master(email);

-- CUSTOMER SUCCESS ENRICHED (one row per email, joined with signups/uploads/payments/stripe)
CREATE TABLE IF NOT EXISTS customer_success_enriched (
    email                  TEXT PRIMARY KEY,
    signup_date            DATE,
    signup_status          TEXT,
    lead_source            TEXT,
    first_upload_date      DATE,
    upload_status          TEXT,
    first_payment_date     DATE,
    total_spend            NUMERIC DEFAULT 0,
    payment_count          INTEGER DEFAULT 0,
    payment_status         TEXT,
    days_signup_to_upload  INTEGER,
    days_signup_to_paid    INTEGER,
    stripe_customer_id     TEXT,
    stripe_created         TIMESTAMPTZ,
    stripe_balance         NUMERIC,
    stripe_currency        TEXT,
    stripe_delinquent      BOOLEAN,
    subscription_status    TEXT,
    mrr                    NUMERIC DEFAULT 0,
    enriched_at            TIMESTAMPTZ DEFAULT NOW(),
    stripe_enriched_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_cse_status ON customer_success_enriched(subscription_status);
CREATE INDEX IF NOT EXISTS idx_cse_paid ON customer_success_enriched(first_payment_date);

ALTER TABLE access_control               ENABLE ROW LEVEL SECURITY;
ALTER TABLE access_log                   ENABLE ROW LEVEL SECURITY;
ALTER TABLE customer_success_master      ENABLE ROW LEVEL SECURITY;
ALTER TABLE customer_success_enriched    ENABLE ROW LEVEL SECURITY;

-- Seed default admin emails (REPLACE with real ones)
INSERT INTO access_control (email, role, added_by, notes)
VALUES
    ('ayaz@eagle3dstreaming.com', 'admin', 'system', 'Initial admin'),
    ('admin@eagle3dstreaming.com', 'admin', 'system', 'Default admin')
ON CONFLICT (email) DO NOTHING;
