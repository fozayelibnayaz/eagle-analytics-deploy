"""
youtube_get_refresh_token.py — Eagle 3D Streaming Analytics Hub
=================================================================
One-time script to obtain a YouTube OAuth refresh token.
The refresh token never expires (unlike access tokens which last 1 hour).

Steps:
  1. Ensure YOUTUBE_CLIENT_ID + YOUTUBE_CLIENT_SECRET in secrets.toml
  2. Run: python3 youtube_get_refresh_token.py
  3. Browser opens Google consent screen
  4. Approve -> refresh_token printed
  5. Answer 'y' to auto-save to secrets.toml
  6. Restart app -> full YouTube Analytics now available
"""

import http.server
import json
import os
import socketserver
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
]
REDIRECT_URI = "http://localhost:8765/callback"
_captured_code = {"code": None}


def _get_secret(key: str, default: str = "") -> str:
    val = os.environ.get(key, "").strip()
    if val:
        return val
    try:
        import streamlit as st
        return str(st.secrets.get(key, "") or default).strip()
    except Exception:
        return default


SUCCESS_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Authorized</title></head>
<body style="font-family:sans-serif;background:#111;color:#fff;padding:60px;text-align:center;">
  <h1 style="color:#9EFF2F;">Authorization Complete</h1>
  <p>You can close this tab. Return to your terminal.</p>
</body></html>"""


class OAuthHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if "code" in qs:
            _captured_code["code"] = qs["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            # Encode HTML to UTF-8 bytes (safe for any characters)
            self.wfile.write(SUCCESS_HTML.encode("utf-8"))
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def main():
    client_id     = _get_secret("YOUTUBE_CLIENT_ID")
    client_secret = _get_secret("YOUTUBE_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("[ERR] YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_SECRET missing in secrets.toml")
        return

    print("=" * 60)
    print("YouTube OAuth Refresh Token Generator")
    print("=" * 60)
    print(f"Client ID: {client_id[:20]}...")
    print()

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id":              client_id,
        "redirect_uri":           REDIRECT_URI,
        "response_type":          "code",
        "scope":                  " ".join(SCOPES),
        "access_type":            "offline",
        "prompt":                 "consent",
        "include_granted_scopes": "true",
    })

    print("Opening browser for Google consent...")
    print(f"If browser doesn't open, paste this URL manually:\n{auth_url}\n")

    server = socketserver.TCPServer(("localhost", 8765), OAuthHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    webbrowser.open(auth_url)

    print("Waiting for authorization (5 min timeout)...")
    timeout = 300
    waited = 0
    while _captured_code["code"] is None and waited < timeout:
        time.sleep(0.5)
        waited += 0.5

    server.shutdown()

    if _captured_code["code"] is None:
        print("[ERR] Timed out waiting for auth code")
        return

    code = _captured_code["code"]
    print(f"\n[OK] Got auth code ({len(code)} chars)")

    print("Exchanging code for tokens...")
    data = urllib.parse.urlencode({
        "code":          code,
        "client_id":     client_id,
        "client_secret": client_secret,
        "redirect_uri":  REDIRECT_URI,
        "grant_type":    "authorization_code",
    }).encode()

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            tokens = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"[ERR] Token exchange failed: {e.read().decode()}")
        return

    access_token  = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")

    print()
    print("=" * 60)
    print("SUCCESS")
    print("=" * 60)
    print(f"Access token:  {access_token[:30]}... ({len(access_token)} chars)")
    print(f"Refresh token: {refresh_token[:30]}... ({len(refresh_token)} chars)")
    print()

    if not refresh_token:
        print("[WARN] No refresh_token returned. This happens if you've already")
        print("       authorized this app before. Revoke access first at:")
        print("       https://myaccount.google.com/permissions")
        print("       Then re-run this script.")
        return

    print("-" * 60)
    print("ADD TO .streamlit/secrets.toml:")
    print("-" * 60)
    print(f'YOUTUBE_OAUTH_TOKEN   = "{access_token}"')
    print(f'YOUTUBE_REFRESH_TOKEN = "{refresh_token}"')
    print("-" * 60)
    print()

    ans = input("Auto-update .streamlit/secrets.toml? [y/N]: ").strip().lower()
    if ans == "y":
        secrets_path = Path(".streamlit/secrets.toml")
        if not secrets_path.exists():
            print("[ERR] secrets.toml not found")
            return

        content = secrets_path.read_text()
        import re as _re
        for key, value in [
            ("YOUTUBE_OAUTH_TOKEN",   access_token),
            ("YOUTUBE_REFRESH_TOKEN", refresh_token),
        ]:
            new_line = f'{key} = "{value}"'
            pattern = rf'^{key}\s*=.*$'
            if _re.search(pattern, content, flags=_re.MULTILINE):
                content = _re.sub(pattern, new_line, content, flags=_re.MULTILINE)
            else:
                content += f"\n{new_line}\n"

        secrets_path.write_text(content)
        print("[OK] secrets.toml updated. Restart Streamlit to apply.")
    else:
        print("Skipped auto-update. Copy the values manually.")


if __name__ == "__main__":
    main()
