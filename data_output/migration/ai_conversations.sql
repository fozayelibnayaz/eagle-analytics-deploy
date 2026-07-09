
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS ai_conversations (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_email  TEXT NOT NULL,
    platform    TEXT,
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL,
    model_used  TEXT,
    feedback    TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ai_conv_user ON ai_conversations(user_email);
CREATE INDEX IF NOT EXISTS idx_ai_conv_platform ON ai_conversations(platform);
CREATE INDEX IF NOT EXISTS idx_ai_conv_created ON ai_conversations(created_at DESC);
ALTER TABLE ai_conversations ENABLE ROW LEVEL SECURITY;
