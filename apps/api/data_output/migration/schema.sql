-- EAGLE3D KPI SUPABASE SCHEMA
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS signups (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email              TEXT NOT NULL,
    email_normalized   TEXT NOT NULL UNIQUE,
    signup_date        DATE,
    lead_source        TEXT,
    final_status       TEXT NOT NULL DEFAULT 'PENDING',
    category           TEXT,
    rejection_reason   TEXT,
    verify_score       NUMERIC,
    scraped_date       DATE,
    override_status    TEXT,
    override_reason    TEXT,
    override_user      TEXT,
    override_timestamp TIMESTAMPTZ,
    is_overridden      BOOLEAN DEFAULT FALSE,
    processed_at       TIMESTAMPTZ DEFAULT NOW(),
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS uploads (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email              TEXT NOT NULL,
    email_normalized   TEXT NOT NULL UNIQUE,
    upload_date        DATE,
    final_status       TEXT NOT NULL DEFAULT 'PENDING',
    category           TEXT,
    rejection_reason   TEXT,
    signup_id          UUID REFERENCES signups(id),
    override_status    TEXT,
    override_reason    TEXT,
    override_user      TEXT,
    override_timestamp TIMESTAMPTZ,
    is_overridden      BOOLEAN DEFAULT FALSE,
    processed_at       TIMESTAMPTZ DEFAULT NOW(),
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS payments (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email               TEXT NOT NULL,
    email_normalized    TEXT NOT NULL UNIQUE,
    first_payment_date  DATE,
    total_spend         NUMERIC DEFAULT 0,
    payment_count       INTEGER DEFAULT 0,
    final_status        TEXT NOT NULL DEFAULT 'PENDING',
    category            TEXT,
    stripe_customer_id  TEXT,
    override_status     TEXT,
    override_reason     TEXT,
    override_user       TEXT,
    override_timestamp  TIMESTAMPTZ,
    is_overridden       BOOLEAN DEFAULT FALSE,
    processed_at        TIMESTAMPTZ DEFAULT NOW(),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS manual_overrides (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email_normalized   TEXT NOT NULL UNIQUE,
    action             TEXT NOT NULL,
    final_status       TEXT NOT NULL,
    category           TEXT NOT NULL,
    reason             TEXT NOT NULL,
    override_user      TEXT NOT NULL,
    override_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_tab         TEXT,
    is_active          BOOLEAN DEFAULT TRUE,
    extra_data         JSONB,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS override_audit_log (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    email_normalized TEXT NOT NULL,
    action           TEXT NOT NULL,
    previous_action  TEXT,
    previous_status  TEXT,
    new_status       TEXT NOT NULL,
    reason           TEXT NOT NULL,
    override_user    TEXT NOT NULL,
    source_tab       TEXT,
    change_type      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_kpis (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    date             DATE NOT NULL UNIQUE,
    year             INTEGER,
    month            TEXT,
    signups_accepted INTEGER DEFAULT 0,
    uploads_accepted INTEGER DEFAULT 0,
    paid_accepted    INTEGER DEFAULT 0,
    signup_details   TEXT,
    upload_details   TEXT,
    paid_details     TEXT,
    last_updated     TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS analytics_cache (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source       TEXT NOT NULL,
    metric_date  DATE,
    period_type  TEXT,
    period_start DATE,
    period_end   DATE,
    data         JSONB NOT NULL,
    fetched_at   TIMESTAMPTZ DEFAULT NOW(),
    is_valid     BOOLEAN DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS report_history (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    report_date       DATE NOT NULL,
    report_type       TEXT NOT NULL,
    content           TEXT,
    is_warning        BOOLEAN DEFAULT FALSE,
    validation_passed BOOLEAN DEFAULT FALSE,
    sent_at           TIMESTAMPTZ DEFAULT NOW(),
    error             TEXT
);
CREATE TABLE IF NOT EXISTS data_coverage (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    metric         TEXT NOT NULL UNIQUE,
    coverage_start DATE,
    coverage_end   DATE,
    record_count   INTEGER DEFAULT 0,
    last_computed  TIMESTAMPTZ DEFAULT NOW(),
    notes          TEXT
);
ALTER TABLE signups            ENABLE ROW LEVEL SECURITY;
ALTER TABLE uploads            ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments           ENABLE ROW LEVEL SECURITY;
ALTER TABLE manual_overrides   ENABLE ROW LEVEL SECURITY;
ALTER TABLE override_audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_kpis         ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics_cache    ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_history     ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_coverage      ENABLE ROW LEVEL SECURITY;
CREATE OR REPLACE VIEW v_effective_signups AS
SELECT s.*, COALESCE(o.final_status, s.final_status) AS effective_status
FROM signups s
LEFT JOIN manual_overrides o ON s.email_normalized = o.email_normalized AND o.is_active = TRUE;
CREATE OR REPLACE VIEW v_effective_uploads AS
SELECT u.*, COALESCE(o.final_status, u.final_status) AS effective_status
FROM uploads u
LEFT JOIN manual_overrides o ON u.email_normalized = o.email_normalized AND o.is_active = TRUE;
CREATE OR REPLACE VIEW v_effective_payments AS
SELECT p.*, COALESCE(o.final_status, p.final_status) AS effective_status
FROM payments p
LEFT JOIN manual_overrides o ON p.email_normalized = o.email_normalized AND o.is_active = TRUE;
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $func$ BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $func$ LANGUAGE plpgsql;
CREATE TRIGGER trg_signups_upd   BEFORE UPDATE ON signups          FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_uploads_upd   BEFORE UPDATE ON uploads          FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_payments_upd  BEFORE UPDATE ON payments         FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_overrides_upd BEFORE UPDATE ON manual_overrides FOR EACH ROW EXECUTE FUNCTION update_updated_at();
