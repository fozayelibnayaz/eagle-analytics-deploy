#!/usr/bin/env python3
"""
YouTube OAuth Setup — Complete Step-by-Step Guide
==================================================
Run: python3 youtube_oauth_setup.py
"""

print("""
🦅 YouTube OAuth Setup — Complete Guide
========================================

PROBLEM: YouTube Audience/Revenue/Traffic tabs show "OAuth unavailable"
SOLUTION: Get YouTube OAuth tokens and add to secrets

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STEP 1: Create Google OAuth Client
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Go to: https://console.cloud.google.com/apis/credentials
2. Click "+ CREATE CREDENTIALS" → "OAuth client ID"
3. If prompted, configure OAuth consent screen first:
   - User Type: External
   - App name: Eagle Analytics Hub
   - User support email: your email
   - Developer contact: your email
   - Add test user: your email
   - Save and continue through all steps
4. Back to Credentials → Create OAuth client ID:
   - Application type: **Web application** (NOT Desktop!)
   - Name: Eagle Analytics Hub
   - Authorized redirect URIs: Click "Add URI"
     → http://localhost:8089
   - Click "Create"
5. Copy the Client ID and Client Secret

STEP 2: Run the OAuth Helper
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Run this command:
    python3 youtube_oauth_helper.py

It will ask for Client ID and Client Secret.
Then it gives you a URL to open in your browser.

STEP 3: Authorize in Browser
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Open the URL in your browser
2. Sign in with your Google account
3. Click "Continue" to authorize
4. The browser will redirect to localhost:8089
5. The script captures the authorization code automatically
6. It prints your tokens!

STEP 4: Add Tokens to Secrets
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Add these to Streamlit Cloud Secrets:
    YOUTUBE_OAUTH_TOKEN = "<token-from-script>"
    YOUTUBE_OAUTH_REFRESH_TOKEN = "<refresh-token-from-script>"

Add to GitHub Secrets (for pipeline):
    YOUTUBE_OAUTH_TOKEN = "<token>"
    YOUTUBE_OAUTH_REFRESH_TOKEN = "<refresh-token>"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TROUBLESHOOTING:
- "command not found: python" → Use: python3 youtube_oauth_helper.py
- "redirect_uri_mismatch" → Make sure redirect URI is http://localhost:8089
- "access_denied" → Make sure you added your email as test user
- Port 8089 busy → Script auto-tries 8090, 8091, etc.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")
