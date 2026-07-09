"""
youtube_oauth_helper.py — Eagle 3D Streaming Analytics Hub
============================================================
Thin wrapper — most logic now lives in youtube_connector.py.
Kept for backward compatibility with any code that imports it.
"""

from youtube_connector import (
    _refresh_access_token,
    has_analytics_access,
    get_daily_analytics,
)


def get_access_token():
    """Return a fresh access token or None."""
    return _refresh_access_token()


def is_ready() -> bool:
    return has_analytics_access()


if __name__ == "__main__":
    print(f"Ready: {is_ready()}")
    tok = get_access_token()
    print(f"Access token: {'✅ obtained (' + str(len(tok)) + ' chars)' if tok else '❌ failed'}")
