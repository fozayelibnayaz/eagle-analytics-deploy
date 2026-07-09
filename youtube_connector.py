"""
youtube_connector.py — Eagle 3D Streaming Analytics Hub
=========================================================
YouTube Data API v3 (public) + YouTube Analytics API (OAuth).

Uses:
  - YOUTUBE_API_KEY, YOUTUBE_CHANNEL_ID (public)
  - YOUTUBE_OAUTH_TOKEN, YOUTUBE_REFRESH_TOKEN,
    YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET (analytics)

Public functions:
  - is_configured()
  - has_analytics_access()
  - get_channel_info() → dict
  - get_channel_videos(max_videos) → List[dict]
  - get_daily_analytics(start_date, end_date) → DataFrame
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import requests


# ─────────────────────────────────────────────────────────────────
# SECRETS
# ─────────────────────────────────────────────────────────────────
def _secret(name: str, default: str = "") -> str:
    val = os.environ.get(name, "").strip()
    if val:
        return val
    try:
        import streamlit as st
        return str(st.secrets.get(name, "") or default).strip()
    except Exception:
        return default


def _api_key() -> str:
    return _secret("YOUTUBE_API_KEY")


def _channel_id() -> str:
    return _secret("YOUTUBE_CHANNEL_ID")


def is_configured() -> bool:
    return bool(_api_key() and _channel_id())


def has_analytics_access() -> bool:
    return bool(_secret("YOUTUBE_REFRESH_TOKEN")
                and _secret("YOUTUBE_CLIENT_ID")
                and _secret("YOUTUBE_CLIENT_SECRET"))


# ─────────────────────────────────────────────────────────────────
# CHANNEL INFO
# ─────────────────────────────────────────────────────────────────
def get_channel_info() -> Dict[str, Any]:
    if not is_configured():
        return {}
    url = "https://www.googleapis.com/youtube/v3/channels"
    params = {
        "key":  _api_key(),
        "id":   _channel_id(),
        "part": "snippet,statistics,contentDetails",
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])
        if not items:
            return {}
        item = items[0]
        snip = item.get("snippet", {})
        stats = item.get("statistics", {})
        return {
            "channel_id":       item.get("id", _channel_id()),
            "title":            snip.get("title", ""),
            "description":      snip.get("description", ""),
            "published_at":     snip.get("publishedAt", ""),
            "country":          snip.get("country", ""),
            "custom_url":       snip.get("customUrl", ""),
            "thumbnail":        snip.get("thumbnails", {}).get("default", {}).get("url", ""),
            "subscribers":      int(stats.get("subscriberCount", 0) or 0),
            "views":            int(stats.get("viewCount", 0) or 0),
            "video_count":      int(stats.get("videoCount", 0) or 0),
            "uploads_playlist": item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", ""),
            "fetched_at":       datetime.utcnow().isoformat(),
        }
    except Exception as e:
        print(f"[youtube_connector] get_channel_info failed: {e}")
        return {}


# ─────────────────────────────────────────────────────────────────
# VIDEO LIST
# ─────────────────────────────────────────────────────────────────
def get_channel_videos(max_videos: int = 200) -> List[Dict[str, Any]]:
    if not is_configured():
        return []

    ch = get_channel_info()
    uploads = ch.get("uploads_playlist", "")
    if not uploads:
        return []

    video_ids: List[str] = []
    page_token = ""
    while len(video_ids) < max_videos:
        params = {
            "key":         _api_key(),
            "playlistId":  uploads,
            "part":        "contentDetails",
            "maxResults":  50,
        }
        if page_token:
            params["pageToken"] = page_token
        try:
            r = requests.get(
                "https://www.googleapis.com/youtube/v3/playlistItems",
                params=params, timeout=15,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"[youtube_connector] playlistItems failed: {e}")
            break

        for item in data.get("items", []):
            vid = item.get("contentDetails", {}).get("videoId")
            if vid:
                video_ids.append(vid)

        page_token = data.get("nextPageToken", "")
        if not page_token:
            break

    video_ids = video_ids[:max_videos]

    # Now fetch stats in batches of 50
    videos: List[Dict[str, Any]] = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        params = {
            "key":  _api_key(),
            "id":   ",".join(batch),
            "part": "snippet,statistics,contentDetails",
        }
        try:
            r = requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params=params, timeout=15,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"[youtube_connector] videos batch failed: {e}")
            continue

        for v in data.get("items", []):
            snip = v.get("snippet", {})
            stats = v.get("statistics", {})
            videos.append({
                "video_id":     v.get("id", ""),
                "title":        snip.get("title", ""),
                "description":  snip.get("description", "")[:500],
                "published_at": snip.get("publishedAt", ""),
                "channel_id":   snip.get("channelId", ""),
                "thumbnail":    snip.get("thumbnails", {}).get("high", {}).get("url", ""),
                "duration":     v.get("contentDetails", {}).get("duration", ""),
                "views":        int(stats.get("viewCount", 0) or 0),
                "likes":        int(stats.get("likeCount", 0) or 0),
                "comments":     int(stats.get("commentCount", 0) or 0),
                "favorites":    int(stats.get("favoriteCount", 0) or 0),
                "fetched_at":   datetime.utcnow().isoformat(),
            })

    videos.sort(key=lambda v: v.get("published_at", ""), reverse=True)
    return videos


# ─────────────────────────────────────────────────────────────────
# ANALYTICS API (OAuth-required)
# ─────────────────────────────────────────────────────────────────
def _refresh_access_token() -> Optional[str]:
    """Get a fresh access token using the refresh token."""
    refresh_token = _secret("YOUTUBE_REFRESH_TOKEN")
    client_id     = _secret("YOUTUBE_CLIENT_ID")
    client_secret = _secret("YOUTUBE_CLIENT_SECRET")
    if not all((refresh_token, client_id, client_secret)):
        return None
    try:
        r = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "refresh_token": refresh_token,
                "client_id":     client_id,
                "client_secret": client_secret,
                "grant_type":    "refresh_token",
            },
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("access_token")
    except Exception as e:
        print(f"[youtube_connector] token refresh failed: {e}")
        return None


def get_daily_analytics(start_date: str, end_date: str) -> pd.DataFrame:
    """Requires YouTube Analytics API + OAuth. Returns per-day metrics."""
    if not has_analytics_access():
        return pd.DataFrame()

    token = _refresh_access_token()
    if not token:
        return pd.DataFrame()

    channel = _channel_id()
    if not channel:
        return pd.DataFrame()

    url = "https://youtubeanalytics.googleapis.com/v2/reports"
    params = {
        "ids":        f"channel=={channel}",
        "startDate":  start_date,
        "endDate":    end_date,
        "metrics":    "views,likes,comments,shares,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost",
        "dimensions": "day",
    }
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[youtube_connector] analytics failed: {e}")
        return pd.DataFrame()

    columns = [c.get("name") for c in data.get("columnHeaders", [])]
    rows = data.get("rows", []) or []
    if not rows or not columns:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=columns)
    if "day" in df.columns:
        df["date"] = pd.to_datetime(df["day"], errors="coerce")
    return df


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Configured: {is_configured()}")
    print(f"Analytics access: {has_analytics_access()}")

    if is_configured():
        ch = get_channel_info()
        print(f"\nChannel: {ch.get('title')}")
        print(f"Subscribers: {ch.get('subscribers'):,}")
        print(f"Videos:      {ch.get('video_count')}")
        print(f"Total views: {ch.get('views'):,}")

        vids = get_channel_videos(max_videos=10)
        print(f"\nTop 5 recent videos:")
        for v in vids[:5]:
            print(f"  • {v['title'][:60]:60s} views={v['views']:>7,}  likes={v['likes']:>5}")

        if has_analytics_access():
            end = datetime.now().strftime("%Y-%m-%d")
            start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            print(f"\n7-day analytics:")
            df = get_daily_analytics(start, end)
            if df.empty:
                print("  (no data)")
            else:
                print(df.to_string(index=False))
