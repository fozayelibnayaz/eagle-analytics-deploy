#!/usr/bin/env python3
"""
YouTube OAuth Helper v3 — Complete Setup
=========================================
This script handles the ENTIRE YouTube OAuth setup from start to finish.

STEP 1: Create/Update Google Cloud OAuth Client
STEP 2: Authorize and get tokens
STEP 3: Print secrets to add

Run: python3 youtube_oauth_helper.py
"""

import http.server
import urllib.parse
import urllib.request
import json
import sys
import threading

# ============================================================
# STEP 1: Google Cloud Console Setup Instructions
# ============================================================

SETUP_GUIDE = """
🦅 YouTube OAuth Complete Setup
================================

STEP 1: Go to Google Cloud Console
────────────────────────────────────
URL: https://console.cloud.google.com/apis/credentials

If you DON'T have a project yet:
  1. Click "Select a project" → "New Project"
  2. Name it: "Eagle Analytics Hub"
  3. Click Create

STEP 2: Enable Required APIs
─────────────────────────────
Go to: https://console.cloud.google.com/apis/library
Search and ENABLE each of these:
  ✅ YouTube Data API v3
  ✅ YouTube Analytics API
  ✅ YouTube Reporting API (optional)

STEP 3: Configure OAuth Consent Screen
───────────────────────────────────────
Go to: https://console.cloud.google.com/apis/credentials/consent

  1. User Type: External → Click Create
  2. App name: Eagle Analytics Hub
  3. User support email: your email
  4. Developer contact: your email
  5. Click "Save and Continue"
  6. Scopes → Click "Add or Remove Scopes":
     - Search "YouTube" and add ALL YouTube scopes
     - Or add these manually:
       • youtube.readonly
       • yt-analytics.readonly
       • yt-analytics-monetary.readonly
  7. Click "Save and Continue"
  8. Test Users → Add your email → "Save and Continue"
  9. Click "Back to Dashboard"

STEP 4: Create OAuth 2.0 Client ID
───────────────────────────────────
Go to: https://console.cloud.google.com/apis/credentials

  1. Click "+ CREATE CREDENTIALS" → "OAuth client ID"
  2. Application type: "Web application"
  3. Name: "Eagle Analytics Hub"
  4. Authorized JavaScript origins:
     Click "Add URI" → http://localhost:8089
  5. Authorized redirect URIs:
     Click "Add URI" → http://localhost:8089
  6. Click "Create"
  7. COPY the Client ID and Client Secret shown

⚠️  CRITICAL: The redirect URI MUST be exactly: http://localhost:8089
    No trailing slash, no https, no other port.

If you already have an OAuth client (for the Vercel app):
  → Click on your existing OAuth client
  → Go to "Authorized redirect URIs"
  → Click "ADD URI"
  → Add: http://localhost:8089
  → Click "Save"
  → Wait 5 minutes for Google to propagate the change
"""

REDIRECT_PORT = 8089
SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
]


def main():
    print(SETUP_GUIDE)

    input("\n✅ Done with the steps above? Press Enter to continue...")

    client_id = input("\nEnter your Client ID: ").strip()
    client_secret = input("Enter your Client Secret: ").strip()

    if not client_id or not client_secret:
        print("❌ Both Client ID and Client Secret are required.")
        sys.exit(1)

    redirect_uri = f"http://localhost:{REDIRECT_PORT}"

    # Build auth URL
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        + urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        })
    )

    print()
    print("🔗 Open this URL in your browser:")
    print()
    print(auth_url)
    print()
    print("⚠️  After clicking 'Continue', your browser will redirect to localhost:8089")
    print("    The script will automatically capture the authorization code.")
    print()

    # Start local server to catch redirect
    auth_code = [None]
    auth_error = [None]

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)

            if "code" in params:
                auth_code[0] = params["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"""<html><body style="font-family:Arial;text-align:center;padding-top:100px;background:#1a1a2e;color:#fff">
                    <h1 style="color:#00d4ff">&#9989; Authorization Successful!</h1>
                    <p>You can close this tab now.</p>
                    <p>Return to the terminal to see your tokens.</p>
                    </body></html>""")
            elif "error" in params:
                auth_error[0] = params.get("error", ["unknown"])[0]
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                error_desc = params.get("error_description", [""])[0]
                self.wfile.write(f"""<html><body style="font-family:Arial;text-align:center;padding-top:100px;background:#1a1a2e;color:#fff">
                    <h1 style="color:#ff4444">&#10060; Authorization Failed</h1>
                    <p>Error: {auth_error[0]}</p>
                    <p>{error_desc}</p>
                    <p>Check the terminal for help.</p>
                    </body></html>""".encode())
            else:
                self.send_response(400)
                self.end_headers()

        def log_message(self, format, *args):
            pass

    # Try ports 8089-8093
    server = None
    actual_port = REDIRECT_PORT
    for attempt in range(5):
        try:
            server = http.server.HTTPServer(("localhost", actual_port), Handler)
            break
        except OSError:
            actual_port += 1
            continue

    if not server:
        print("❌ Could not start local server on ports 8089-8093.")
        print("   Close other apps using these ports and try again.")
        sys.exit(1)

    if actual_port != REDIRECT_PORT:
        print(f"⚠️  Port {REDIRECT_PORT} busy, using {actual_port} instead.")
        print(f"   Make sure {redirect_uri} AND http://localhost:{actual_port}")
        print(f"   are both in your OAuth client's redirect URIs.")
        redirect_uri = f"http://localhost:{actual_port}"

    print(f"⏳ Waiting for authorization (listening on localhost:{actual_port})...")
    print("   (Timeout: 2 minutes)")
    print()

    def serve():
        server.handle_request()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    t.join(timeout=120)

    server.server_close()

    if auth_error[0]:
        print(f"\n❌ Authorization error: {auth_error[0]}")
        if "redirect_uri_mismatch" in str(auth_error):
            print()
            print("💡 FIX: The redirect URI doesn't match. Do this:")
            print()
            print("  1. Go to: https://console.cloud.google.com/apis/credentials")
            print("  2. Click your OAuth 2.0 Client")
            print(f"  3. Under 'Authorized redirect URIs', add: {redirect_uri}")
            print("  4. Click Save")
            print("  5. Wait 5 minutes for Google to propagate")
            print("  6. Run this script again")
            print()
            print("⚠️  Common mistakes:")
            print("   - Using 'Desktop app' instead of 'Web application'")
            print("   - Using https instead of http")
            print("   - Adding a trailing slash")
            print("   - Using a different port number")
        elif "access_denied" in str(auth_error):
            print()
            print("💡 You clicked 'Cancel' or your email isn't a test user.")
            print("   Add your email as a test user in the OAuth consent screen.")
        sys.exit(1)

    if not auth_code[0]:
        print("❌ No authorization code received (timeout). Try again.")
        sys.exit(1)

    code = auth_code[0]
    print("✅ Got authorization code!")
    print()

    # Exchange code for tokens
    print("🔄 Exchanging code for tokens...")
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()

    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"❌ Token exchange failed: {body}")
        if "redirect_uri_mismatch" in body:
            print()
            print("💡 The redirect URI in the token exchange doesn't match.")
            print(f"   Expected: {redirect_uri}")
            print("   Go to Google Cloud Console and add this exact URI.")
        sys.exit(1)

    access_token = result.get("access_token", "")
    refresh_token = result.get("refresh_token", "")
    expires_in = result.get("expires_in", 3600)

    if not refresh_token:
        print("⚠️  No refresh token received. This usually means:")
        print("   - You've already authorized this app before")
        print("   - Go to https://myaccount.google.com/permissions")
        print("   - Remove 'Eagle Analytics Hub' from Third-party apps")
        print("   - Run this script again (with prompt=consent)")
        sys.exit(1)

    print("✅ Tokens received!")
    print()

    # Test the token
    channel_name = ""
    if access_token:
        print("🧪 Testing token with YouTube API...")
        try:
            test_req = urllib.request.Request(
                "https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&mine=true",
            )
            test_req.add_header("Authorization", f"Bearer {access_token}")
            with urllib.request.urlopen(test_req, timeout=15) as resp:
                test_data = json.loads(resp.read().decode())
                if test_data.get("items"):
                    ch = test_data["items"][0]
                    channel_name = ch.get("snippet", {}).get("title", "Unknown")
                    subs = ch.get("statistics", {}).get("subscriberCount", "?")
                    vids = ch.get("statistics", {}).get("videoCount", "?")
                    print(f"✅ Connected to: {channel_name}")
                    print(f"   Subscribers: {subs}")
                    print(f"   Videos: {vids}")
        except Exception as e:
            print(f"⚠️  Token test failed: {e}")

    # Test Analytics API
    if access_token:
        print("🧪 Testing YouTube Analytics API...")
        try:
            from datetime import datetime, timedelta
            end = datetime.now().strftime("%Y-%m-%d")
            start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            test_url = (
                f"https://youtubeanalytics.googleapis.com/v2/reports?"
                f"ids=channel==MINE&startDate={start}&endDate={end}"
                f"&metrics=views,subscribersGained&dimensions=day"
            )
            test_req = urllib.request.Request(test_url)
            test_req.add_header("Authorization", f"Bearer {access_token}")
            with urllib.request.urlopen(test_req, timeout=15) as resp:
                test_data = json.loads(resp.read().decode())
                if test_data.get("rows"):
                    print(f"✅ Analytics API working! Got {len(test_data['rows'])} days of data")
                else:
                    print("✅ Analytics API connected (no data for last 7 days)")
        except urllib.error.HTTPError as e:
            print(f"⚠️  Analytics API error: {e.code} — {e.reason}")
            print("   Make sure YouTube Analytics API is enabled in Google Cloud Console")
        except Exception as e:
            print(f"⚠️  Analytics test: {e}")

    print()
    print("=" * 60)
    print("📋 ADD THESE SECRETS TO STREAMLIT CLOUD")
    print("=" * 60)
    print()
    print(f'YOUTUBE_OAUTH_TOKEN = "{access_token}"')
    print(f'YOUTUBE_REFRESH_TOKEN = "{refresh_token}"')
    print(f'YOUTUBE_CLIENT_ID = "{client_id}"')
    print(f'YOUTUBE_CLIENT_SECRET = "{client_secret}"')
    print()
    print("=" * 60)
    print("📋 ALSO ADD TO GITHUB SECRETS (for pipeline)")
    print("=" * 60)
    print("  https://github.com/fozayelibnayaz/eagle3d-kpi-automation/settings/secrets/actions")
    print()
    print("  YOUTUBE_OAUTH_TOKEN")
    print("  YOUTUBE_REFRESH_TOKEN")
    print("  YOUTUBE_CLIENT_ID")
    print("  YOUTUBE_CLIENT_SECRET")
    print()
    print("=" * 60)
    print()
    print(f"⏱️  Access token expires in {expires_in // 60} minutes")
    print("   The refresh token auto-renews on Streamlit Cloud.")
    print(f"   Channel: {channel_name or 'Unknown'}")


if __name__ == "__main__":
    main()
