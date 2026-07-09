#!/bin/bash
# migration_env.sh — Load secrets from your shell environment.
#
# HOW TO USE:
#   1. Put your real secrets in ~/.eagle_secrets (chmod 600 for safety)
#      Format:
#        export GROQ_API_KEY="gsk_..."
#        export GEMINI_API_KEY="AIza..."
#        ...
#   2. source ~/.eagle_secrets  # loads into your shell
#   3. source migration_env.sh  # re-exports them for python scripts
#
# NEVER hardcode real API keys in this file — GitHub secret scanning
# blocks the push and the keys become instantly compromised.

# ── AI providers ──
export GROQ_API_KEY="${GROQ_API_KEY:-}"
export GEMINI_API_KEY="${GEMINI_API_KEY:-}"

# ── Telegram alerts ──
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
export TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"

# ── Email alerts ──
export EMAIL_FROM="${EMAIL_FROM:-}"
export EMAIL_TO="${EMAIL_TO:-}"
export EMAIL_APP_PASSWORD="${EMAIL_APP_PASSWORD:-}"

# ── Google service account (for GA4 + Sheets) ──
export type="service_account"
export project_id="${GCP_PROJECT_ID:-}"
export private_key_id="${GCP_PRIVATE_KEY_ID:-}"
export private_key="${GCP_PRIVATE_KEY:-}"
export client_email="${GCP_CLIENT_EMAIL:-}"
export client_id="${GCP_CLIENT_ID:-}"
export auth_uri="https://accounts.google.com/o/oauth2/auth"
export token_uri="https://oauth2.googleapis.com/token"
export auth_provider_x509_cert_url="https://www.googleapis.com/oauth2/v1/certs"
export client_x509_cert_url="${GCP_CLIENT_X509_CERT_URL:-}"
export universe_domain="googleapis.com"

# ── GA4 ──
export GA4_PROPERTY_ID="${GA4_PROPERTY_ID:-}"

# ── Verify all critical secrets are set ──
missing=()
for k in GROQ_API_KEY GEMINI_API_KEY TELEGRAM_BOT_TOKEN GA4_PROPERTY_ID; do
    if [ -z "${!k}" ]; then
        missing+=("$k")
    fi
done

if [ ${#missing[@]} -gt 0 ]; then
    echo "[warn] Missing env vars: ${missing[*]}"
    echo "       Source ~/.eagle_secrets first, or set them in your shell."
fi
