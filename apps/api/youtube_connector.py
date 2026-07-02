"""
YouTube Connector — Eagle 3D KPI System v7
=============================================
Complete YouTube analytics matching AI YouTube Command Center features:
  - Channel info, video library, performance scoring
  - YouTube Data API v3 (public data)
  - YouTube Analytics API v2 (private data via OAuth)
  - Retention curves, demographics, traffic sources
  - Revenue, playlist analytics, sharing data
  - Video scoring & diagnostics engine
  - Smart caching with auto-refresh

Required secrets:
  YOUTUBE_API_KEY      — YouTube Data API key (free)
  YOUTUBE_CHANNEL_ID   — Channel ID (UCxxxxx)
  YOUTUBE_OAUTH_TOKEN  — OAuth2 access/refresh token for Analytics API (optional)
"""

import os
import json
import re
import time
import math
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
import urllib.request
import urllib.parse
import urllib.error

DATA_DIR = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)

# ── Cache paths ──
YT_CACHE = DATA_DIR / "youtube_cache.json"
YT_VIDEO_CACHE = DATA_DIR / "youtube_videos.json"
YT_ANALYTICS_CACHE = DATA_DIR / "youtube_analytics.json"
YT_DAILY_CACHE = DATA_DIR / "youtube_daily.json"


def _get_secret(key: str, default: str = "") -> str:
    """Get secret from env, then Streamlit secrets."""
    val = os.environ.get(key, "")
    if val:
        return val
    try:
        import streamlit as st
        if key in st.secrets:
            val = st.secrets[key]
            if val is not None and str(val).strip():
                return str(val).strip()
    except Exception:
        pass
    return default


def _load_cache(path: Path, max_age_hours: int = 6) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        ts = data.get("_cached_at", "")
        if ts:
            cached_time = datetime.fromisoformat(ts)
            if datetime.now() - cached_time < timedelta(hours=max_age_hours):
                return data
    except Exception:
        pass
    return None


def _save_cache(path: Path, data: dict):
    data["_cached_at"] = datetime.now().isoformat()
    path.write_text(json.dumps(data, default=str, indent=2))


def _api_request(url: str, params: dict = None) -> Optional[dict]:
    api_key = _get_secret("YOUTUBE_API_KEY")
    if not api_key:
        return None
    if params is None:
        params = {}
    params["key"] = api_key
    full_url = url + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(full_url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"[YouTube] API error: {e}")
        return None


def _analytics_request(params: dict) -> Optional[dict]:
    """Make YouTube Analytics API request. Always refreshes token first if refresh_token available."""
    base_url = "https://youtubeanalytics.googleapis.com/v2/reports"
    
    # Always try to get a fresh access token via refresh if refresh_token is available
    access_token = None
    refresh_token = _get_refresh_token()
    client_id = _get_secret("YOUTUBE_CLIENT_ID")
    client_secret = _get_secret("YOUTUBE_CLIENT_SECRET")
    
    if refresh_token and client_id and client_secret:
        # Prefer refreshed token (access tokens expire in ~1hr)
        access_token = _try_refresh_token()
        if access_token:
            # Save the fresh token for this session
            os.environ["YOUTUBE_OAUTH_TOKEN"] = access_token
    
    if not access_token:
        # Fallback to stored access token (may be expired)
        access_token = _get_oauth_token()
    
    if not access_token:
        return None
    
    full_url = base_url + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(full_url)
        req.add_header("Authorization", f"Bearer {access_token}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode()[:500]
        except Exception:
            pass
        print(f"[YouTube Analytics] HTTP {e.code}: {e.reason} | {error_body}")
        if e.code == 401 and refresh_token and client_id and client_secret:
            # One more retry with fresh token
            try:
                fresh = _try_refresh_token()
                if fresh:
                    req2 = urllib.request.Request(full_url)
                    req2.add_header("Authorization", f"Bearer {fresh}")
                    os.environ["YOUTUBE_OAUTH_TOKEN"] = fresh
                    with urllib.request.urlopen(req2, timeout=30) as resp2:
                        return json.loads(resp2.read().decode())
            except Exception as e2:
                print(f"[YouTube Analytics] Retry failed: {e2}")
        return None
    except Exception as e:
        print(f"[YouTube Analytics] API error: {e}")
        return None


def _parse_analytics_rows(data: dict) -> List[dict]:
    if not data or "rows" not in data or "columnHeaders" not in data:
        return []
    headers = [h["name"] for h in data["columnHeaders"]]
    return [dict(zip(headers, row)) for row in data["rows"]]


def _get_oauth_token() -> str:
    return _get_secret("YOUTUBE_OAUTH_TOKEN")


def _get_refresh_token() -> str:
    return _get_secret("YOUTUBE_REFRESH_TOKEN")


def _try_refresh_token() -> Optional[str]:
    """Try to refresh OAuth token using refresh_token + client_id/secret.
    This is the PRIMARY way to get a valid access token — access tokens expire in ~1hr."""
    refresh = _get_refresh_token()
    client_id = _get_secret("YOUTUBE_CLIENT_ID")
    client_secret = _get_secret("YOUTUBE_CLIENT_SECRET")
    if not all([refresh, client_id, client_secret]):
        missing = []
        if not refresh:
            missing.append("YOUTUBE_REFRESH_TOKEN")
        if not client_id:
            missing.append("YOUTUBE_CLIENT_ID")
        if not client_secret:
            missing.append("YOUTUBE_CLIENT_SECRET")
        print(f"[YouTube OAuth] Cannot refresh — missing: {', '.join(missing)}")
        return None
    try:
        data = urllib.parse.urlencode({
            "refresh_token": refresh,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        }).encode()
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            new_token = result.get("access_token")
            if new_token:
                print(f"[YouTube OAuth] Token refreshed successfully (expires in {result.get('expires_in', '?')}s)")
                return new_token
            else:
                print(f"[YouTube OAuth] Refresh response missing access_token: {list(result.keys())}")
                return None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:500]
        except Exception:
            pass
        print(f"[YouTube OAuth] Refresh failed HTTP {e.code}: {e.reason} | {body}")
        return None
    except Exception as e:
        print(f"[YouTube OAuth] Refresh failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# CHANNEL INFO
# ═══════════════════════════════════════════════════════════════

def get_channel_info() -> Dict[str, Any]:
    cache = _load_cache(YT_CACHE, max_age_hours=6)
    if cache:
        return {k: v for k, v in cache.items() if k != "_cached_at"}

    channel_id = _get_secret("YOUTUBE_CHANNEL_ID")
    if not channel_id:
        return {"error": "YOUTUBE_CHANNEL_ID not configured", "demo": True}

    data = _api_request(
        "https://www.googleapis.com/youtube/v3/channels",
        {"part": "snippet,statistics,brandingSettings,contentDetails", "id": channel_id},
    )
    if not data or not data.get("items"):
        return {"error": "Channel not found", "demo": True}

    ch = data["items"][0]
    stats = ch.get("statistics", {})
    snippet = ch.get("snippet", {})
    branding = ch.get("brandingSettings", {})

    result = {
        "channel_id": channel_id,
        "title": snippet.get("title", ""),
        "description": snippet.get("description", "")[:500],
        "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
        "banner": branding.get("image", {}).get("bannerExternalUrl", ""),
        "published_at": snippet.get("publishedAt", ""),
        "subscribers": int(stats.get("subscriberCount", 0)),
        "total_views": int(stats.get("viewCount", 0)),
        "video_count": int(stats.get("videoCount", 0)),
        "custom_url": snippet.get("customUrl", ""),
        "keywords": branding.get("channel", {}).get("keywords", []),
        "demo": False,
        "fetched_at": datetime.now().isoformat(),
    }

    _save_cache(YT_CACHE, result)
    return result


# ═══════════════════════════════════════════════════════════════
# VIDEO LIBRARY
# ═══════════════════════════════════════════════════════════════

def get_channel_videos(max_videos: int = 300) -> List[Dict]:
    cache = _load_cache(YT_VIDEO_CACHE, max_age_hours=6)
    if cache and "videos" in cache:
        return cache["videos"]

    channel_id = _get_secret("YOUTUBE_CHANNEL_ID")
    if not channel_id:
        return []

    # Get uploads playlist ID
    ch_data = _api_request(
        "https://www.googleapis.com/youtube/v3/channels",
        {"part": "contentDetails", "id": channel_id},
    )
    if not ch_data or not ch_data.get("items"):
        return []
    uploads_id = ch_data["items"][0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", "")
    if not uploads_id:
        return []

    # Paginate playlist items
    video_ids = []
    next_page = None
    safety = 0
    while len(video_ids) < max_videos and safety < 60:
        params = {"part": "contentDetails", "playlistId": uploads_id, "maxResults": min(50, max_videos - len(video_ids))}
        if next_page:
            params["pageToken"] = next_page
        pl_data = _api_request("https://www.googleapis.com/youtube/v3/playlistItems", params)
        if not pl_data or not pl_data.get("items"):
            break
        for item in pl_data["items"]:
            vid = item.get("contentDetails", {}).get("videoId", "")
            if vid:
                video_ids.append(vid)
        next_page = pl_data.get("nextPageToken")
        if not next_page:
            break
        safety += 1
        time.sleep(0.15)

    # Batch get video details
    all_videos = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        vid_data = _api_request(
            "https://www.googleapis.com/youtube/v3/videos",
            {"part": "snippet,statistics,contentDetails", "id": ",".join(batch)},
        )
        if not vid_data or not vid_data.get("items"):
            continue
        for v in vid_data["items"]:
            sv = v.get("statistics", {})
            sn = v.get("snippet", {})
            dur = v.get("contentDetails", {}).get("duration", "PT0S")
            duration_sec = _parse_duration(dur)
            views = int(sv.get("viewCount", 0))
            likes = int(sv.get("likeCount", 0))
            comments = int(sv.get("commentCount", 0))

            all_videos.append({
                "video_id": v["id"],
                "title": sn.get("title", ""),
                "published_at": sn.get("publishedAt", ""),
                "thumbnail": sn.get("thumbnails", {}).get("high", {}).get("url", ""),
                "duration_seconds": duration_sec,
                "duration_label": _format_duration(duration_sec),
                "views": views,
                "likes": likes,
                "comments": comments,
                "engagement_rate": round((likes + comments) / views * 100, 3) if views > 0 else 0,
                "like_rate": round(likes / views * 100, 3) if views > 0 else 0,
                "tags": sn.get("tags", []),
                "category_id": sn.get("categoryId", ""),
                "demo": False,
            })
        time.sleep(0.25)

    all_videos.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    _save_cache(YT_VIDEO_CACHE, {"videos": all_videos})
    return all_videos


# ═══════════════════════════════════════════════════════════════
# ANALYTICS API (Requires OAuth)
# ═══════════════════════════════════════════════════════════════

def get_daily_analytics(start_date: str, end_date: str) -> pd.DataFrame:
    """Get daily analytics from YouTube Analytics API (requires OAuth).
    Returns empty DataFrame if Analytics API not available - NO estimated fallbacks."""
    channel_id = _get_secret("YOUTUBE_CHANNEL_ID")
    if not channel_id:
        print("[YouTube] YOUTUBE_CHANNEL_ID not configured")
        return pd.DataFrame()
    
    # Check if we have valid OAuth credentials for Analytics API
    if not has_analytics_access():
        print("[YouTube] Analytics API not available - OAuth credentials missing. Returning empty data.")
        print("[YouTube] Add YOUTUBE_REFRESH_TOKEN, YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET to enable Analytics API")
        return pd.DataFrame()
    
    params = {
        "ids": f"channel=={channel_id}",
        "startDate": start_date, "endDate": end_date,
        "metrics": "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,comments,shares,subscribersGained,subscribersLost,views,ctr",
        "dimensions": "day", "sort": "day",
    }
    data = _analytics_request(params)
    if not data:
        print(f"[YouTube] Analytics API returned no data for {start_date} to {end_date}")
        return pd.DataFrame()
    rows = _parse_analytics_rows(data)
    if not rows:
        print(f"[YouTube] Analytics API returned empty rows for {start_date} to {end_date}")
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    for col in df.columns:
        if col != "day":
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def _build_estimated_daily_analytics(start_date: str, end_date: str) -> pd.DataFrame:
    """DEPRECATED: Estimated analytics removed. Returns empty DataFrame.
    Use get_daily_analytics() which requires YouTube Analytics API (OAuth)."""
    print("[YouTube] WARNING: Estimated analytics deprecated. Configure OAuth for real data.")
    return pd.DataFrame()


def get_subscriber_growth(start_date: str, end_date: str) -> pd.DataFrame:
    channel_id = _get_secret("YOUTUBE_CHANNEL_ID")
    params = {
        "ids": f"channel=={channel_id}" if channel_id else "channel==MINE",
        "startDate": start_date, "endDate": end_date,
        "metrics": "subscribersGained,subscribersLost,views",
        "dimensions": "day", "sort": "day",
    }
    data = _analytics_request(params)
    rows = _parse_analytics_rows(data)
    df = pd.DataFrame(rows) if rows else pd.DataFrame()
    if not df.empty:
        for col in df.columns:
            if col != "day":
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def get_video_analytics_batch(video_ids: List[str], start_date: str, end_date: str) -> Dict[str, Dict]:
    channel_id = _get_secret("YOUTUBE_CHANNEL_ID")
    result = {}
    for vid in video_ids[:50]:
        params = {
            "ids": f"channel=={channel_id}" if channel_id else "channel==MINE",
            "startDate": start_date, "endDate": end_date,
            "metrics": "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,comments,shares,subscribersGained,subscribersLost,views,ctr",
            "dimensions": "video", "filters": f"video=={vid}",
        }
        data = _analytics_request(params)
        rows = _parse_analytics_rows(data)
        if rows:
            result[vid] = rows[0]
        time.sleep(0.25)
    return result


def get_retention_curve(video_id: str) -> List[Dict]:
    channel_id = _get_secret("YOUTUBE_CHANNEL_ID")
    params = {
        "ids": f"channel=={channel_id}" if channel_id else "channel==MINE",
        "startDate": (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"),
        "endDate": datetime.now().strftime("%Y-%m-%d"),
        "metrics": "audienceWatchRatio,relativeRetentionPerformance",
        "dimensions": "elapsedVideoTimeRatio",
        "filters": f"video=={video_id}", "sort": "elapsedVideoTimeRatio",
    }
    data = _analytics_request(params)
    return _parse_analytics_rows(data) if data else []


def get_traffic_sources(start_date: str, end_date: str, video_id: str = "") -> pd.DataFrame:
    channel_id = _get_secret("YOUTUBE_CHANNEL_ID")
    params = {
        "ids": f"channel=={channel_id}" if channel_id else "channel==MINE",
        "startDate": start_date, "endDate": end_date,
        "metrics": "views,estimatedMinutesWatched,averageViewDuration",
        "dimensions": "insightTrafficSourceType", "sort": "-views",
    }
    if video_id:
        params["filters"] = f"video=={video_id}"
    data = _analytics_request(params)
    rows = _parse_analytics_rows(data)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def get_demographics(start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
    channel_id = _get_secret("YOUTUBE_CHANNEL_ID")
    ch = f"channel=={channel_id}" if channel_id else "channel==MINE"
    results = {}
    queries = {
        "age_gender": {"metrics": "viewerPercentage", "dimensions": "ageGroup,gender"},
        "geography": {"metrics": "views,estimatedMinutesWatched", "dimensions": "country", "sort": "-views", "maxResults": "20"},
        "devices": {"metrics": "views,estimatedMinutesWatched", "dimensions": "deviceType"},
        "os": {"metrics": "views", "dimensions": "operatingSystem", "sort": "-views", "maxResults": "10"},
        "subscribed_status": {"metrics": "views", "dimensions": "subscribedStatus"},
    }
    for name, q in queries.items():
        params = {"ids": ch, "startDate": start_date, "endDate": end_date, **q}
        data = _analytics_request(params)
        rows = _parse_analytics_rows(data)
        results[name] = pd.DataFrame(rows) if rows else pd.DataFrame()
        time.sleep(0.25)
    return results


def get_revenue(start_date: str, end_date: str) -> Dict:
    channel_id = _get_secret("YOUTUBE_CHANNEL_ID")
    params = {
        "ids": f"channel=={channel_id}" if channel_id else "channel==MINE",
        "startDate": start_date, "endDate": end_date,
        "metrics": "estimatedRevenue,estimatedAdRevenue,grossRevenue,cpm,playbackBasedCpm,adImpressions,monetizedPlaybacks",
    }
    data = _analytics_request(params)
    rows = _parse_analytics_rows(data)
    return rows[0] if rows else {}


def get_revenue_daily(start_date: str, end_date: str) -> pd.DataFrame:
    channel_id = _get_secret("YOUTUBE_CHANNEL_ID")
    params = {
        "ids": f"channel=={channel_id}" if channel_id else "channel==MINE",
        "startDate": start_date, "endDate": end_date,
        "metrics": "estimatedRevenue,cpm,adImpressions",
        "dimensions": "day", "sort": "day",
    }
    data = _analytics_request(params)
    rows = _parse_analytics_rows(data)
    df = pd.DataFrame(rows) if rows else pd.DataFrame()
    if not df.empty:
        for col in df.columns:
            if col != "day":
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def get_top_videos(metric: str = "views", start_date: str = "", end_date: str = "", limit: int = 10) -> pd.DataFrame:
    channel_id = _get_secret("YOUTUBE_CHANNEL_ID")
    params = {
        "ids": f"channel=={channel_id}" if channel_id else "channel==MINE",
        "startDate": start_date or (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
        "endDate": end_date or datetime.now().strftime("%Y-%m-%d"),
        "metrics": metric, "dimensions": "video", "sort": f"-{metric}", "maxResults": str(limit),
    }
    data = _analytics_request(params)
    rows = _parse_analytics_rows(data)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def get_search_terms(start_date: str, end_date: str, video_id: str = "") -> pd.DataFrame:
    channel_id = _get_secret("YOUTUBE_CHANNEL_ID")
    filters = "insightTrafficSourceType==YT_SEARCH"
    if video_id:
        filters += f";video=={video_id}"
    params = {
        "ids": f"channel=={channel_id}" if channel_id else "channel==MINE",
        "startDate": start_date, "endDate": end_date,
        "metrics": "views", "dimensions": "insightTrafficSourceDetail",
        "filters": filters, "sort": "-views", "maxResults": "50",
    }
    data = _analytics_request(params)
    rows = _parse_analytics_rows(data)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def get_views_by_playback(start_date: str, end_date: str) -> pd.DataFrame:
    channel_id = _get_secret("YOUTUBE_CHANNEL_ID")
    params = {
        "ids": f"channel=={channel_id}" if channel_id else "channel==MINE",
        "startDate": start_date, "endDate": end_date,
        "metrics": "views,estimatedMinutesWatched",
        "dimensions": "insightPlaybackLocationType", "sort": "-views",
    }
    data = _analytics_request(params)
    rows = _parse_analytics_rows(data)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def get_sharing_services(start_date: str, end_date: str) -> pd.DataFrame:
    channel_id = _get_secret("YOUTUBE_CHANNEL_ID")
    params = {
        "ids": f"channel=={channel_id}" if channel_id else "channel==MINE",
        "startDate": start_date, "endDate": end_date,
        "metrics": "shares", "dimensions": "sharingService", "sort": "-shares", "maxResults": "20",
    }
    data = _analytics_request(params)
    rows = _parse_analytics_rows(data)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def get_playlist_analytics(start_date: str, end_date: str) -> pd.DataFrame:
    channel_id = _get_secret("YOUTUBE_CHANNEL_ID")
    params = {
        "ids": f"channel=={channel_id}" if channel_id else "channel==MINE",
        "startDate": start_date, "endDate": end_date,
        "metrics": "views,estimatedMinutesWatched,averageViewDuration,playlistStarts,viewsPerPlaylistStart,averageTimeInPlaylist",
        "dimensions": "playlist", "sort": "-views", "maxResults": "25",
    }
    data = _analytics_request(params)
    rows = _parse_analytics_rows(data)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # Try to enrich with playlist titles
    if "playlist" in df.columns:
        ids = df["playlist"].tolist()
        titles = _get_playlist_titles(ids)
        if titles:
            df["playlist_title"] = df["playlist"].map(titles)
    return df


def _get_playlist_titles(playlist_ids: List[str]) -> Dict[str, str]:
    titles = {}
    for pid in playlist_ids[:25]:
        data = _api_request(
            "https://www.googleapis.com/youtube/v3/playlists",
            {"part": "snippet", "id": pid},
        )
        if data and data.get("items"):
            titles[pid] = data["items"][0].get("snippet", {}).get("title", pid)
        time.sleep(0.1)
    return titles


# ═══════════════════════════════════════════════════════════════
# SCORING ENGINE (from YouTube Command Center)
# ═══════════════════════════════════════════════════════════════

def calculate_performance_score(
    views: int, likes: int, comments: int,
    published_at: str = "", subscribers: int = 1000,
    ctr: float = None, retention: float = None,
) -> int:
    """
    Calculate video performance score (0-100).
    Path A (has OAuth CTR+Retention): CTR(35) + Retention(35) + Engagement(20) + Velocity(10)
    Path B (public data only): Velocity(40) + Engagement(40) + Reach(20)
    """
    if views == 0:
        return 0

    days_since = 1
    if published_at:
        try:
            pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            days_since = max(1, (datetime.now(pub.tzinfo) - pub).total_seconds() / 86400)
        except Exception:
            pass

    views_per_day = views / days_since
    engagement_rate = ((likes + comments) / views) * 100
    views_vs_subs = (views / max(subscribers, 1)) * 100

    # Path A: Has real CTR + Retention
    if ctr is not None and retention is not None:
        # CTR score (35 max)
        if ctr >= 10: ctr_s = 35
        elif ctr >= 7: ctr_s = 28 + ((ctr - 7) / 3) * 7
        elif ctr >= 4: ctr_s = 18 + ((ctr - 4) / 3) * 10
        elif ctr >= 2: ctr_s = 8 + ((ctr - 2) / 2) * 10
        else: ctr_s = (ctr / 2) * 8

        # Retention score (35 max)
        if retention >= 50: ret_s = 35
        elif retention >= 40: ret_s = 28 + ((retention - 40) / 10) * 7
        elif retention >= 30: ret_s = 18 + ((retention - 30) / 10) * 10
        elif retention >= 20: ret_s = 8 + ((retention - 20) / 10) * 10
        else: ret_s = (retention / 20) * 8

        # Engagement (20 max)
        if engagement_rate >= 8: eng_s = 20
        elif engagement_rate >= 5: eng_s = 15 + ((engagement_rate - 5) / 3) * 5
        elif engagement_rate >= 2: eng_s = 8 + ((engagement_rate - 2) / 3) * 7
        elif engagement_rate >= 0.5: eng_s = 3 + ((engagement_rate - 0.5) / 1.5) * 5
        else: eng_s = (engagement_rate / 0.5) * 3

        # Velocity (10 max)
        if views_per_day >= 1000: vpd_s = 10
        elif views_per_day >= 100: vpd_s = 7 + ((views_per_day - 100) / 900) * 3
        elif views_per_day >= 10: vpd_s = 3 + ((views_per_day - 10) / 90) * 4
        else: vpd_s = (views_per_day / 10) * 3

        return round(ctr_s + ret_s + eng_s + vpd_s)

    # Path B: Public data only
    if views_per_day >= 1000: vpd_s = 40
    elif views_per_day >= 100: vpd_s = 30 + ((views_per_day - 100) / 900) * 10
    elif views_per_day >= 20: vpd_s = 20 + ((views_per_day - 20) / 80) * 10
    elif views_per_day >= 5: vpd_s = 10 + ((views_per_day - 5) / 15) * 10
    elif views_per_day >= 1: vpd_s = 5 + ((views_per_day - 1) / 4) * 5
    else: vpd_s = views_per_day * 5

    if engagement_rate >= 8: eng_s = 40
    elif engagement_rate >= 5: eng_s = 30 + ((engagement_rate - 5) / 3) * 10
    elif engagement_rate >= 3: eng_s = 20 + ((engagement_rate - 3) / 2) * 10
    elif engagement_rate >= 1.5: eng_s = 10 + ((engagement_rate - 1.5) / 1.5) * 10
    elif engagement_rate >= 0.5: eng_s = 5 + ((engagement_rate - 0.5) / 1) * 5
    else: eng_s = engagement_rate * 10

    if views_vs_subs >= 100: reach_s = 20
    elif views_vs_subs >= 50: reach_s = 15 + ((views_vs_subs - 50) / 50) * 5
    elif views_vs_subs >= 20: reach_s = 10 + ((views_vs_subs - 20) / 30) * 5
    elif views_vs_subs >= 10: reach_s = 5 + ((views_vs_subs - 10) / 10) * 5
    else: reach_s = (views_vs_subs / 10) * 5

    return round(vpd_s + eng_s + reach_s)


def get_engagement_rating(rate: float) -> Dict[str, str]:
    if rate >= 8: return {"label": "Excellent", "color": "🟢", "desc": "Top 5% of creators"}
    if rate >= 5: return {"label": "Very Good", "color": "🔵", "desc": "Strong engagement"}
    if rate >= 3: return {"label": "Good", "color": "🟣", "desc": "Above average"}
    if rate >= 1.5: return {"label": "Average", "color": "🟡", "desc": "Industry average"}
    if rate >= 0.5: return {"label": "Below Avg", "color": "🟠", "desc": "Needs improvement"}
    if rate > 0: return {"label": "Low", "color": "🔴", "desc": "Audience not engaging"}
    return {"label": "No data", "color": "⚪", "desc": "Need views to measure"}


def get_retention_rating(retention: float) -> Dict[str, str]:
    if retention >= 60: return {"label": "Excellent", "desc": "Top creator level"}
    if retention >= 45: return {"label": "Good", "desc": "Above average retention"}
    if retention >= 30: return {"label": "Fair", "desc": "Average retention"}
    if retention >= 20: return {"label": "Poor", "desc": "Below average retention"}
    return {"label": "Critical", "desc": "Critical retention issues"}


def diagnose_video(
    views: int, likes: int, comments: int,
    published_at: str = "", subscribers: int = 1000,
    ctr: float = None, retention: float = None,
) -> List[Dict[str, str]]:
    issues = []
    if views == 0:
        return [{"issue": "Video has 0 views", "severity": "critical",
                  "fix": "Check if public/unlisted. Promote on social. Update thumbnail & title."}]

    days_since = 1
    if published_at:
        try:
            pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            days_since = max(1, (datetime.now(pub.tzinfo) - pub).total_seconds() / 86400)
        except Exception:
            pass
    vpd = views / days_since
    eng = ((likes + comments) / views) * 100
    reach = (views / max(subscribers, 1)) * 100

    if ctr is not None:
        if ctr < 2:
            issues.append({"issue": f"CTR critically low: {ctr:.1f}% (target: >4%)", "severity": "critical",
                           "fix": f"Thumbnail failing. {(100-ctr):.0f}% skip your video. Redesign thumbnail."})
        elif ctr < 4:
            issues.append({"issue": f"CTR below average: {ctr:.1f}%", "severity": "warning",
                           "fix": "Try A/B testing thumbnails. Make titles more specific."})
    if retention is not None:
        if retention < 20:
            issues.append({"issue": f"Retention critically low: {retention:.1f}%", "severity": "critical",
                           "fix": "Viewer drop-off is severe. Improve hook in first 30 seconds."})
        elif retention < 40:
            issues.append({"issue": f"Retention below average: {retention:.1f}%", "severity": "warning",
                           "fix": "Add pattern interrupts, tighter editing, or chapter markers."})

    if eng < 1:
        issues.append({"issue": f"Engagement very low: {eng:.2f}%", "severity": "warning",
                       "fix": "Ask questions, add CTAs, create controversy or emotional hook."})
    if vpd < 1 and days_since > 7:
        issues.append({"issue": f"Views velocity low: {vpd:.1f}/day", "severity": "minor",
                       "fix": "Share on social media, optimize SEO, cross-promote."})
    if reach < 5 and subscribers > 100:
        issues.append({"issue": f"Only reaching {reach:.1f}% of subscribers", "severity": "minor",
                       "fix": "Check if notifications are on. YouTube may not push to all subs."})

    if not issues:
        issues.append({"issue": "No major issues detected", "severity": "good",
                       "fix": "This video is performing well. Keep this content style."})
    return issues


def get_score_label(score: int) -> str:
    if score >= 70: return "🔥 Excellent"
    if score >= 50: return "✅ Good"
    if score >= 30: return "⚠️ Fair"
    if score > 0: return "❌ Poor"
    return "⚪ No data"


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _parse_duration(iso: str) -> int:
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "PT0S")
    if not m: return 0
    return (int(m.group(1) or 0) * 3600) + (int(m.group(2) or 0) * 60) + int(m.group(3) or 0)


def _format_duration(seconds: int) -> str:
    if seconds >= 3600:
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}"
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


def format_number(num: int) -> str:
    if num >= 1_000_000_000: return f"{num/1e9:.1f}B"
    if num >= 1_000_000: return f"{num/1e6:.1f}M"
    if num >= 1_000: return f"{num/1e3:.1f}K"
    return str(num)


def is_configured() -> bool:
    return bool(_get_secret("YOUTUBE_API_KEY") and _get_secret("YOUTUBE_CHANNEL_ID"))


def has_analytics_access() -> bool:
    """Check if OAuth credentials exist (access token OR refresh token + client credentials).
    Returns True if we have the minimum required to attempt an analytics API call."""
    access_token = _get_oauth_token()
    refresh_token = _get_refresh_token()
    client_id = _get_secret("YOUTUBE_CLIENT_ID")
    client_secret = _get_secret("YOUTUBE_CLIENT_SECRET")
    # Have access if: access_token exists, OR refresh_token + client creds exist
    return bool(access_token or (refresh_token and client_id and client_secret))


def get_status() -> Dict[str, Any]:
    has_api_key = bool(_get_secret("YOUTUBE_API_KEY"))
    has_channel = bool(_get_secret("YOUTUBE_CHANNEL_ID"))
    has_access_token = bool(_get_oauth_token())
    has_refresh_token = bool(_get_refresh_token())
    has_client_creds = bool(_get_secret("YOUTUBE_CLIENT_ID") and _get_secret("YOUTUBE_CLIENT_SECRET"))
    return {
        "data_api": has_api_key,
        "channel_id": has_channel,
        "analytics_api": has_access_token or (has_refresh_token and has_client_creds),
        "has_refresh_token": has_refresh_token,
        "has_client_creds": has_client_creds,
        "configured": bool(has_api_key and has_channel),
        "full_access": bool(has_api_key and has_channel and has_access_token),
    }


# ═══════════════════════════════════════════════════════════════
# SMART NOTIFICATIONS — Event detection engine (v4.0 port)
# 25+ alert types with per-type caps, dedup, priority sorting
# ═══════════════════════════════════════════════════════════════

_MILESTONE_VIEWS = [100, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000]
_MILESTONE_SUBS = [100, 500, 1000, 2000, 5000, 10000, 25000, 50000, 100000, 500000, 1000000]
_MILESTONE_WATCH = [100, 500, 1000, 5000, 10000, 50000, 100000]

_MAX_PER_TYPE = {
    "critical_retention": 3, "critical_engagement": 3, "dead_video": 3,
    "rising": 4, "views_dropped": 3, "likes_spike": 3, "comments_spike": 3,
    "shares_spike": 3, "watch_time_milestone": 2, "new_video": 5, "strong_launch": 3,
    "hidden_gem": 3, "high_ctr_low_views": 3, "low_ctr_warning": 3,
    "re_engagement": 2, "momentum_loss": 3, "consistency_warning": 1,
    "channel_engagement_drop": 1, "upload_streak": 1,
}


def detect_video_events(videos, prev_snapshot=None, channel_subs=0):
    """Detect events from video list. Returns list of event dicts sorted by priority."""
    events = []
    type_counts = {}
    has_prev = bool(prev_snapshot)
    active = [v for v in videos if (v.get("views") or 0) > 0]
    now_ts = datetime.now().timestamp()

    def _age_days(pub):
        if not pub:
            return 999
        try:
            pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            return max(0.001, (datetime.now(pub_dt.tzinfo) - pub_dt).total_seconds() / 86400)
        except Exception:
            return 999

    def _pct(n, p):
        if p == 0:
            return 100 if n > 0 else 0
        return (n - p) / p * 100

    def _eng(l, c, v):
        if v == 0:
            return 0
        return (l + c) / v * 100

    def _add(e):
        mx = _MAX_PER_TYPE.get(e["type"])
        if mx == 0:
            return
        cnt = type_counts.get(e["type"], 0)
        if mx is not None and cnt >= mx:
            return
        type_counts[e["type"]] = cnt + 1
        events.append(e)

    for v in videos:
        vid = v.get("video_id", v.get("youtube_id", ""))
        title = (v.get("title") or "Untitled")[:60]
        p = (prev_snapshot or {}).get(vid)

        views = v.get("views") or 0
        likes = v.get("likes") or 0
        comments = v.get("comments") or 0
        va = v.get("analytics") or {}
        shares = va.get("shares") or v.get("shares") or 0
        ctr = va.get("ctr")
        retention = va.get("avg_view_percentage") or va.get("averageViewPercentage")
        watch_min = va.get("watch_time_minutes") or va.get("estimatedMinutesWatched")
        subs_g = va.get("subscribers_gained") or va.get("subscribersGained") or 0
        has_real = v.get("has_real_analytics", False)
        er = _eng(likes, comments, views)
        age = _age_days(v.get("published_at"))
        vpd = views / max(age, 0.001) if views > 0 else 0

        def _is_real_ret(r):
            return bool(has_real and r is not None and r > 0 and r >= 1.5 and views >= 100)

        # NEW VIDEO <48h
        if age <= 2:
            _add({
                "type": "new_video", "video_id": vid, "title": title,
                "emoji": "🆕", "priority": 4, "severity": "info",
                "message": f"New video live — push in first 24h for algorithm boost",
                "data": {"Video": title, "Hours Live": f"{int(age * 24)}h", "Views": views},
            })
            continue

        if views == 0:
            continue

        # SNAPSHOT-BASED
        if p and has_prev:
            v_delta = views - (p.get("views") or 0)
            l_delta = likes - (p.get("likes") or 0)
            c_delta = comments - (p.get("comments") or 0)
            s_delta = shares - (p.get("shares") or 0)
            sub_delta = subs_g - (p.get("subscribers_gained") or 0)
            v_pct = _pct(views, p.get("views") or 0)
            l_pct = _pct(likes, p.get("likes") or 0)

            if v_pct >= 200 and v_delta >= 1000:
                _add({"type": "viral_explosion", "video_id": vid, "title": title, "emoji": "🔥", "priority": 1,
                      "severity": "critical",
                      "message": f"VIRAL EXPLOSION! +{v_delta:,} views ({v_pct:.0f}% surge) — promote NOW",
                      "data": {"Video": title, "New Views": f"+{v_delta:,}", "Growth": f"+{v_pct:.0f}%"}})
            elif v_pct >= 100 and v_delta >= 500:
                _add({"type": "viral", "video_id": vid, "title": title, "emoji": "🚀", "priority": 2,
                      "severity": "critical",
                      "message": f"Going viral! +{v_delta:,} views ({v_pct:.0f}% growth)",
                      "data": {"Video": title, "New Views": f"+{v_delta:,}", "Growth": f"+{v_pct:.0f}%"}})
            elif v_pct >= 30 and v_delta >= 50:
                _add({"type": "rising", "video_id": vid, "title": title, "emoji": "📈", "priority": 7,
                      "severity": "success",
                      "message": f"Rising! +{v_delta:,} views ({v_pct:.0f}% growth)",
                      "data": {"Video": title, "New Views": f"+{v_delta:,}"}})

            if v_delta < 0 and abs(v_delta) >= 100 and abs(v_pct) >= 40:
                _add({"type": "views_dropped", "video_id": vid, "title": title, "emoji": "📉", "priority": 3,
                      "severity": "warning",
                      "message": f"Views dropped {abs(v_pct):.0f}% — lost {abs(v_delta):,} views",
                      "data": {"Video": title, "Lost": f"{abs(v_delta):,}"}})

            if l_delta >= 10 and l_pct >= 50:
                _add({"type": "likes_spike", "video_id": vid, "title": title, "emoji": "👍", "priority": 6,
                      "severity": "success",
                      "message": f"Likes spiking! +{l_delta} ({l_pct:.0f}% increase)",
                      "data": {"Video": title, "New Likes": f"+{l_delta}"}})

            if c_delta >= 3:
                _add({"type": "comments_spike", "video_id": vid, "title": title, "emoji": "💬", "priority": 5,
                      "severity": "info",
                      "message": f"Comments spiking! +{c_delta} — reply fast for algo boost",
                      "data": {"Video": title, "New Comments": f"+{c_delta}"}})

            if s_delta >= 5:
                _add({"type": "shares_spike", "video_id": vid, "title": title, "emoji": "🔗", "priority": 5,
                      "severity": "success",
                      "message": f"+{s_delta} new shares — content spreading!",
                      "data": {"Video": title, "New Shares": f"+{s_delta}"}})

            if sub_delta >= 10:
                _add({"type": "subscriber_gained", "video_id": vid, "title": title, "emoji": "👥", "priority": 4,
                      "severity": "success",
                      "message": f"+{sub_delta} subscribers from this video — growth driver!",
                      "data": {"Video": title, "New Subs": f"+{sub_delta}"}})

            # Milestone detection
            for m in _MILESTONE_VIEWS:
                if views >= m and (p.get("views") or 0) < m:
                    _add({"type": "milestone", "video_id": vid, "title": title, "emoji": "🏆", "priority": 2,
                          "severity": "success",
                          "message": f"Crossed {m:,} views milestone!",
                          "data": {"Video": title, "Milestone": f"{m:,} views"}})
                    break

            if watch_min and watch_min > 0:
                wh = watch_min / 60
                pwh = (p.get("watch_time_minutes") or 0) / 60
                for m in _MILESTONE_WATCH:
                    if wh >= m and pwh < m:
                        _add({"type": "watch_time_milestone", "video_id": vid, "title": title, "emoji": "⌚", "priority": 5,
                              "severity": "success",
                              "message": f"{m:,} watch hours milestone!",
                              "data": {"Video": title, "Watch Hours": f"{m:,}"}})
                        break

            if v_pct < -10 and v_delta < -20 and 7 < age < 60:
                _add({"type": "momentum_loss", "video_id": vid, "title": title, "emoji": "📉", "priority": 8,
                      "severity": "warning",
                      "message": f"Momentum slowing: {v_pct:.0f}% view change",
                      "data": {"Video": title, "Change": f"{v_pct:.0f}%"}})

            if age >= 60 and v_delta >= 200 and v_pct >= 20:
                _add({"type": "re_engagement", "video_id": vid, "title": title, "emoji": "🔄", "priority": 6,
                      "severity": "success",
                      "message": f"Old video resurging! +{v_delta:,} views on {int(age)}-day-old video",
                      "data": {"Video": title, "New Views": f"+{v_delta:,}"}})

        # NON-SNAPSHOT
        if 1 < age <= 7 and vpd >= 100:
            _add({"type": "strong_launch", "video_id": vid, "title": title, "emoji": "🎉", "priority": 3,
                  "severity": "success",
                  "message": f"Strong launch! {vpd:.0f} views/day in first {int(age)} days",
                  "data": {"Video": title, "Views/Day": f"{vpd:.0f}"}})

        if _is_real_ret(retention) and retention < 15:
            _add({"type": "critical_retention", "video_id": vid, "title": title, "emoji": "⏱️", "priority": 9,
                  "severity": "critical",
                  "message": f"Critical retention: {retention:.1f}% — viewers leaving immediately",
                  "data": {"Video": title, "Retention": f"{retention:.1f}%"}})

        if er < 0.5 and er > 0 and views >= 500:
            _add({"type": "critical_engagement", "video_id": vid, "title": title, "emoji": "❌", "priority": 10,
                  "severity": "critical",
                  "message": f"Critical engagement: {er:.2f}% — add CTA or refresh thumbnail",
                  "data": {"Video": title, "Engagement": f"{er:.2f}%"}})

        if age >= 30 and vpd < 1 and views > 0:
            _add({"type": "dead_video", "video_id": vid, "title": title, "emoji": "🪦", "priority": 14,
                  "severity": "warning",
                  "message": f"Dead video: {vpd:.2f} views/day after {int(age)} days",
                  "data": {"Video": title, "Views/Day": f"{vpd:.2f}"}})

        if _is_real_ret(retention) and retention >= 50 and views < 500 and age > 7:
            _add({"type": "hidden_gem", "video_id": vid, "title": title, "emoji": "💎", "priority": 8,
                  "severity": "info",
                  "message": f"{retention:.0f}% retention but only {views:,} views — promote this!",
                  "data": {"Video": title, "Retention": f"{retention:.1f}%", "Views": f"{views:,}"}})

        if ctr is not None and ctr >= 8 and views < 300 and age > 3:
            _add({"type": "high_ctr_low_views", "video_id": vid, "title": title, "emoji": "🎯", "priority": 8,
                  "severity": "info",
                  "message": f"High CTR ({ctr:.1f}%) but only {views:,} views — share externally",
                  "data": {"Video": title, "CTR": f"{ctr:.1f}%", "Views": f"{views:,}"}})

        if ctr is not None and ctr < 2 and views >= 200:
            _add({"type": "low_ctr_warning", "video_id": vid, "title": title, "emoji": "📊", "priority": 9,
                  "severity": "warning",
                  "message": f"Low CTR: {ctr:.1f}% — thumbnail or title needs A/B test",
                  "data": {"Video": title, "CTR": f"{ctr:.1f}%"}})

    # ─── CHANNEL-WIDE ─────────────────────────────────────────
    if len(active) > 2:
        by_score = sorted(active, key=lambda v: v.get("score") or v.get("views") or 0, reverse=True)
        top_v = by_score[0]
        worst_v = by_score[-1]

        total_views = sum(v.get("views") or 0 for v in videos)
        total_likes = sum(v.get("likes") or 0 for v in videos)
        total_comments = sum(v.get("comments") or 0 for v in videos)
        total_shares = sum(v.get("analytics", {}).get("shares") or v.get("shares") or 0 for v in videos)
        total_watch = sum(v.get("analytics", {}).get("watch_time_minutes") or 0 for v in videos)
        avg_eng = _eng(total_likes, total_comments, total_views) if total_views > 0 else 0
        avg_score = sum(v.get("score") or 0 for v in active) / max(len(active), 1)

        day_vids = [v for v in videos if _age_days(v.get("published_at")) <= 1]
        week_vids = [v for v in videos if _age_days(v.get("published_at")) <= 7]
        month_vids = [v for v in videos if _age_days(v.get("published_at")) <= 30]
        dead_count = len([v for v in videos if _age_days(v.get("published_at")) >= 30 and (v.get("views") or 0) / max(_age_days(v.get("published_at")), 1) < 1])
        low_eng_count = len([v for v in active if _eng(v.get("likes") or 0, v.get("comments") or 0, v.get("views") or 0) < 0.5 and (v.get("views") or 0) >= 200])

        health = "🟢 Excellent" if avg_score >= 60 else "🟡 Good" if avg_score >= 40 else "🟠 Needs Work" if avg_score >= 25 else "🔴 Critical"

        if top_v and (top_v.get("views") or 0) >= 100:
            events.append({"type": "top_performer", "video_id": top_v.get("video_id"), "title": (top_v.get("title") or "")[:60],
                           "emoji": "🥇", "priority": 11, "severity": "success",
                           "message": f"Top performing video: {(top_v.get('title') or '')[:40]}",
                           "data": {"Score": f"{top_v.get('score') or 0}/100", "Views": f"{top_v.get('views') or 0:,}"}})

        if worst_v and (worst_v.get("score") or 0) < (top_v.get("score") or 100) - 30 and (worst_v.get("views") or 0) >= 50:
            events.append({"type": "worst_performer", "video_id": worst_v.get("video_id"), "title": (worst_v.get("title") or "")[:60],
                           "emoji": "🔴", "priority": 12, "severity": "warning",
                           "message": f"Lowest scoring video — refresh title and thumbnail",
                           "data": {"Score": f"{worst_v.get('score') or 0}/100"}})

        events.append({"type": "daily_summary", "video_id": "channel", "title": "Channel Daily Summary",
                       "emoji": "📊", "priority": 15, "severity": "info",
                       "message": f"Full channel snapshot — {datetime.now().strftime('%A, %B %d')}",
                       "data": {"Active Videos": len(active), "Total Views": f"{total_views:,}",
                                "Avg Engagement": f"{avg_eng:.2f}%", "Health": health,
                                "Uploads (7d)": len(week_vids), "Uploads (30d)": len(month_vids)}})

        newest = max(videos, key=lambda v: v.get("published_at") or "") if videos else None
        if newest:
            gap = _age_days(newest.get("published_at"))
            if gap > 14:
                events.append({"type": "upload_gap", "video_id": "channel", "title": "Upload Gap Warning",
                               "emoji": "📅", "priority": 13, "severity": "warning",
                               "message": f"No upload in {int(gap)} days — algorithm is cooling down",
                               "data": {"Days": int(gap), "Last Video": (newest.get("title") or "")[:45]}})

        if len(week_vids) >= 7:
            _add({"type": "upload_streak", "video_id": "channel", "title": "Upload Streak",
                  "emoji": "🔥", "priority": 6, "severity": "success",
                  "message": f"{len(week_vids)} uploads this week — algorithm will reward this!",
                  "data": {"Uploads": len(week_vids)}})

        if avg_eng < 0.3 and total_views > 1000:
            _add({"type": "channel_engagement_drop", "video_id": "channel", "title": "Channel Engagement Low",
                  "emoji": "📉", "priority": 10, "severity": "critical",
                  "message": f"Channel avg engagement {avg_eng:.2f}% — below healthy threshold",
                  "data": {"Avg Engagement": f"{avg_eng:.2f}%", "Total Views": f"{total_views:,}"}})

        if len(month_vids) < 2:
            _add({"type": "consistency_warning", "video_id": "channel", "title": "Low Upload Frequency",
                  "emoji": "⚠️", "priority": 13, "severity": "warning",
                  "message": f"Only {len(month_vids)} upload(s) this month — aim for 4+ per month",
                  "data": {"Uploads": len(month_vids)}})

    # SUBSCRIBER MILESTONE
    if channel_subs:
        for m in _MILESTONE_SUBS:
            if channel_subs >= m and channel_subs < m * 1.05:
                events.append({"type": "sub_milestone", "video_id": "channel", "title": "Subscriber Milestone",
                               "emoji": "🎉", "priority": 3, "severity": "success",
                               "message": f"{m:,} subscribers reached! Incredible milestone!",
                               "data": {"Milestone": f"{m:,} subs", "Current": channel_subs}})
                break

    # Dedup + sort + cap
    seen = set()
    unique = []
    for e in events:
        key = f"{e['type']}:{e['video_id']}"
        if key not in seen:
            seen.add(key)
            unique.append(e)
    unique.sort(key=lambda x: x.get("priority", 50))
    return unique[:15]


def generate_daily_digest(videos, channel_subs=0):
    """Generate structured daily digest data."""
    now_ts = datetime.now().timestamp()
    active = [v for v in videos if (v.get("views") or 0) > 0]
    by_views = sorted(active, key=lambda v: v.get("views") or 0, reverse=True)
    total_views = sum(v.get("views") or 0 for v in videos)
    total_likes = sum(v.get("likes") or 0 for v in videos)
    total_comments = sum(v.get("comments") or 0 for v in videos)
    avg_eng = ((total_likes + total_comments) / max(total_views, 1)) * 100 if total_views > 0 else 0
    day_uploads = [v for v in videos if _age_days_s(v.get("published_at")) <= 1]
    newest = max(videos, key=lambda v: v.get("published_at") or "") if videos else None
    gap = _age_days_s(newest.get("published_at")) if newest else 0
    return {
        "title": "📊 Daily Digest — Eagle 3D Streaming",
        "Subscribers": channel_subs,
        "Total Views": total_views,
        "Total Likes": total_likes,
        "Total Comments": total_comments,
        "Avg Engagement": f"{avg_eng:.2f}%",
        "Uploaded Today": len(day_uploads),
        "Days Since Upload": int(gap),
        "Top Video": (by_views[0].get("title") or "")[:50] if by_views else "N/A",
        "Top Views": by_views[0].get("views") if by_views else 0,
    }


def _age_days_s(pub):
    if not pub:
        return 999
    try:
        pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
        return max(0.001, (datetime.now(pub_dt.tzinfo) - pub_dt).total_seconds() / 86400)
    except Exception:
        return 999
