#!/usr/bin/env python3
"""
YOUTUBE OAUTH SETUP v2
Generates OAuth refresh token with all required scopes:
  - youtube.readonly
  - yt-analytics.readonly  (watch hours, views, demographics)
  - yt-analytics-monetary.readonly  (revenue, CPM, ad data)

USAGE:
  python3 youtube_oauth_setup_v2.py

Will:
  1. Open browser to Google OAuth consent screen
  2. Ask you to log in with YouTube channel owner account
  3. Print refresh_token to add to Streamlit secrets
"""

import os
import sys
import json
import webbrowser
import urllib.parse
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading


SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
]

PORT = 8765
REDIRECT_URI = f"http://localhost:{PORT}/callback"

_auth_code = {"code": None, "error": None}


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if "/callback" in self.path:
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in params:
                _auth_code["code"] = params["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h1>Success!</h1><p>You can close this tab. Return to terminal.</p>")
            elif "error" in params:
                _auth_code["error"] = params["error"][0]
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(f"<h1>Error: {params['error'][0]}</h1>".encode())
            else:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # silence


def main():
    print("=" * 70)
    print("YouTube OAuth Setup - All Scopes (Analytics + Monetary)")
    print("=" * 70)

    client_id     = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()

    if not client_id:
        client_id = input("\nEnter YOUTUBE_CLIENT_ID: ").strip()
    if not client_secret:
        client_secret = input("Enter YOUTUBE_CLIENT_SECRET: ").strip()

    if not client_id or not client_secret:
        print("ERROR: client_id and client_secret are required")
        print("\nTo get these:")
        print("  1. Go to https://console.cloud.google.com")
        print("  2. APIs & Services -> Credentials")
        print("  3. Create OAuth 2.0 Client ID (type: Desktop or Web)")
        print("  4. Add redirect URI: " + REDIRECT_URI)
        print("  5. Copy Client ID and Client Secret")
        sys.exit(1)

    # Build auth URL
    auth_params = {
        "client_id":     client_id,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
        "scope":         " ".join(SCOPES),
        "access_type":   "offline",
        "prompt":        "consent",
    }
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(auth_params)

    print("\nStarting local callback server on port", PORT)
    print("\nOpening browser to Google OAuth consent...")
    print("\nIf browser does not open, copy this URL:\n")
    print(auth_url)
    print()

    # Start local server
    server = HTTPServer(("localhost", PORT), _CallbackHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    # Open browser
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    print("Waiting for OAuth callback (will timeout after 5 minutes)...")
    import time
    start = time.time()
    while time.time() - start < 300:
        if _auth_code["code"] or _auth_code["error"]:
            break
        time.sleep(0.5)

    server.shutdown()

    if _auth_code["error"]:
        print(f"\nOAuth error: {_auth_code['error']}")
        sys.exit(1)

    if not _auth_code["code"]:
        print("\nTimeout - no code received")
        sys.exit(1)

    print(f"\nReceived auth code: {_auth_code['code'][:20]}...")

    # Exchange code for tokens
    print("\nExchanging code for refresh token...")
    token_data = urllib.parse.urlencode({
        "code":          _auth_code["code"],
        "client_id":     client_id,
        "client_secret": client_secret,
        "redirect_uri":  REDIRECT_URI,
        "grant_type":    "authorization_code",
    }).encode()

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=token_data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            tokens = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"\nToken exchange failed: {e.code}")
        print(body)
        sys.exit(1)

    print("\n" + "=" * 70)
    print("SUCCESS - OAuth tokens generated")
    print("=" * 70)

    refresh_token = tokens.get("refresh_token", "")
    access_token  = tokens.get("access_token", "")
    expires_in    = tokens.get("expires_in", 0)

    if not refresh_token:
        print("\nWARNING: No refresh_token in response.")
        print("This usually means you already authorized this client.")
        print("To get a new refresh_token:")
        print("  1. Go to https://myaccount.google.com/permissions")
        print("  2. Remove Eagle3D / your app")
        print("  3. Run this script again")
        sys.exit(1)

    print(f"\nAccess token (valid {expires_in}s): {access_token[:30]}...")
    print(f"\nRefresh token (PERMANENT): {refresh_token}")

    # Save to local file
    secrets_file = ".streamlit/youtube_oauth.json"
    os.makedirs(".streamlit", exist_ok=True)
    with open(secrets_file, "w") as f:
        json.dump({
            "YOUTUBE_REFRESH_TOKEN": refresh_token,
            "YOUTUBE_CLIENT_ID":     client_id,
            "YOUTUBE_CLIENT_SECRET": client_secret,
            "scopes":                SCOPES,
        }, f, indent=2)
    print(f"\nSaved to: {secrets_file}")

    print("\n" + "=" * 70)
    print("NEXT STEP: Add these to Streamlit Cloud secrets")
    print("=" * 70)
    print()
    print("Go to: https://share.streamlit.io")
    print("App: eagle3d-kpi-automation")
    print("Settings -> Secrets -> add/update these lines (BEFORE any [section]):")
    print()
    print(f'YOUTUBE_REFRESH_TOKEN = "{refresh_token}"')
    print(f'YOUTUBE_CLIENT_ID = "{client_id}"')
    print(f'YOUTUBE_CLIENT_SECRET = "{client_secret}"')
    print()
    print("Save -> app reboots automatically -> YouTube page will show full analytics")


if __name__ == "__main__":
    main()
