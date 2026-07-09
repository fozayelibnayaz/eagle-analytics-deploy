
-- PERFORMANCE INDEXES FOR EAGLE3D KPI
-- Run these in Supabase SQL Editor for faster queries

-- Signups: fast date + status filtering
CREATE INDEX IF NOT EXISTS idx_signups_date_status ON signups(signup_date, final_status);
CREATE INDEX IF NOT EXISTS idx_signups_status ON signups(final_status);
CREATE INDEX IF NOT EXISTS idx_signups_date ON signups(signup_date);

-- Uploads: fast date + status filtering
CREATE INDEX IF NOT EXISTS idx_uploads_date_status ON uploads(upload_date, final_status);
CREATE INDEX IF NOT EXISTS idx_uploads_status ON uploads(final_status);
CREATE INDEX IF NOT EXISTS idx_uploads_date ON uploads(upload_date);

-- Payments: fast date + status filtering
CREATE INDEX IF NOT EXISTS idx_payments_date_status ON payments(first_payment_date, final_status);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(final_status);
CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(first_payment_date);

-- Daily KPIs: fast date range queries
CREATE INDEX IF NOT EXISTS idx_daily_kpis_date ON daily_kpis(date);

-- Overrides: fast lookup by email
CREATE INDEX IF NOT EXISTS idx_overrides_email_active ON manual_overrides(email_normalized, is_active);

-- Analytics cache: fast source lookup
CREATE INDEX IF NOT EXISTS idx_analytics_source_date ON analytics_cache(source, metric_date);

-- Analyze tables for query planner
ANALYZE signups;
ANALYZE uploads;
ANALYZE payments;
ANALYZE daily_kpis;
ANALYZE manual_overrides;
