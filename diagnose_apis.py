"""
diagnose_apis.py — check which APIs are configured
Run: python3 diagnose_apis.py
"""
from pathlib import Path
import os

def _secret(name, default=""):
    val = os.environ.get(name, "").strip()
    if val: return val
    try:
        import streamlit as st
        return str(st.secrets.get(name, "") or default).strip()
    except:
        return default

print("=" * 60)
print("Eagle 3D Streaming — API Configuration Diagnostic")
print("=" * 60)

# GA4
print("\n📈 Google Analytics 4:")
prop = _secret("GA4_PROPERTY_ID")
print(f"  GA4_PROPERTY_ID: {'✅ ' + prop if prop else '❌ MISSING'}")
try:
    import streamlit as st
    sa = st.secrets.get("ga4_service_account", {}) or st.secrets.get("GOOGLE_CREDS", {})
    if sa and sa.get("client_email"):
        print(f"  Service account: ✅ {sa['client_email']}")
    else:
        print(f"  Service account: ❌ MISSING (add [ga4_service_account] table)")
except Exception as e:
    print(f"  Service account: ❌ {e}")

try:
    from ga4_connector import is_configured
    print(f"  Connector.is_configured(): {'✅ YES' if is_configured() else '❌ NO'}")
except Exception as e:
    print(f"  Connector import: ❌ {e}")

# YouTube
print("\n▶ YouTube:")
yt_key = _secret("YOUTUBE_API_KEY")
yt_ch  = _secret("YOUTUBE_CHANNEL_ID")
print(f"  YOUTUBE_API_KEY:    {'✅ SET' if yt_key else '❌ MISSING'}")
print(f"  YOUTUBE_CHANNEL_ID: {'✅ ' + yt_ch if yt_ch else '❌ MISSING'}")

oauth = _secret("YOUTUBE_OAUTH_TOKEN")
refresh = _secret("YOUTUBE_REFRESH_TOKEN")
cid = _secret("YOUTUBE_CLIENT_ID")
cs = _secret("YOUTUBE_CLIENT_SECRET")

print(f"  OAuth token:        {'✅ SET' if oauth else '❌ MISSING (needed for Analytics)'}")
print(f"  Refresh token:      {'✅ SET' if refresh else '❌ MISSING'}")
print(f"  Client ID:          {'✅ SET' if cid else '❌ MISSING'}")
print(f"  Client secret:      {'✅ SET' if cs else '❌ MISSING'}")

if all([oauth, refresh, cid, cs]):
    print("  → OAuth complete. Full YouTube Analytics available.")
elif yt_key and yt_ch:
    print("  → Public API only. Basic video stats work, no analytics/revenue.")
else:
    print("  → Not configured.")

# Test YouTube fetch
try:
    from youtube_connector import is_configured as yt_conf, get_channel_info
    print(f"  is_configured():    {'✅ YES' if yt_conf() else '❌ NO'}")
    if yt_conf():
        try:
            info = get_channel_info()
            print(f"  Channel test:       ✅ {info.get('title', '?')} ({info.get('subscribers', 0):,} subs)")
        except Exception as e:
            print(f"  Channel test:       ❌ {e}")
except Exception as e:
    print(f"  Connector import: ❌ {e}")

# LinkedIn
print("\n💼 LinkedIn:")
li_page = _secret("LINKEDIN_COMPANY_PAGE")
li_cookies = _secret("LINKEDIN_COOKIES_JSON")
print(f"  Company page:  {'✅ ' + li_page if li_page else '❌ MISSING'}")
print(f"  Cookies:       {'✅ SET (' + str(len(li_cookies)) + ' chars)' if li_cookies else '❌ MISSING'}")

# Telegram
print("\n📤 Telegram:")
tg_tok = _secret("TELEGRAM_BOT_TOKEN")
tg_chat = _secret("TELEGRAM_CHAT_ID")
print(f"  Bot token: {'✅ SET' if tg_tok else '❌ MISSING'}")
print(f"  Chat ID:   {'✅ ' + tg_chat if tg_chat else '❌ MISSING'}")

# Groq / Gemini
print("\n🤖 AI:")
groq = _secret("GROQ_API_KEY")
gem = _secret("GEMINI_API_KEY")
print(f"  Groq:   {'✅ SET' if groq else '❌ MISSING'}")
print(f"  Gemini: {'✅ SET' if gem else '❌ MISSING'}")

print("\n" + "=" * 60)
print("Fix missing keys in .streamlit/secrets.toml")
print("=" * 60)
