"""
youtube_analytics.py — Eagle 3D Streaming Analytics Hub
=========================================================
Python port of AI-YouTube-Command-Center's youtube-analytics.ts
Uses YouTube Analytics API v2 via OAuth for REAL per-video metrics:
  - watch time, retention, CTR, impressions, subscribers gained
  - traffic sources, search terms, playback locations
  - demographics (age/gender/geo/device/OS)
  - revenue (estimatedRevenue, cpm, adImpressions)
  - subscriber growth, daily views
  - top videos by any metric
  - sharing services, playlist analytics
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

ANALYTICS_BASE = "https://youtubeanalytics.googleapis.com/v2/reports"
YOUTUBE_DATA_BASE = "https://www.googleapis.com/youtube/v3"


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


def _date_str(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _get_access_token() -> Optional[str]:
    """Refresh OAuth access token using refresh_token."""
    refresh = _secret("YOUTUBE_REFRESH_TOKEN")
    client_id = _secret("YOUTUBE_CLIENT_ID")
    client_secret = _secret("YOUTUBE_CLIENT_SECRET")
    if not (refresh and client_id and client_secret):
        return None
    try:
        r = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "refresh_token": refresh,
                "client_id":     client_id,
                "client_secret": client_secret,
                "grant_type":    "refresh_token",
            },
            timeout=15,
        )
        return r.json().get("access_token")
    except Exception:
        return None


def _channel_filter() -> str:
    cid = _channel_id()
    return f"channel=={cid}" if cid else "channel==MINE"


def _fetch_analytics(params: Dict[str, str]) -> Dict[str, Any]:
    token = _get_access_token()
    if not token:
        return {"error": "No access token"}
    if "ids" not in params:
        params["ids"] = _channel_filter()
    url = f"{ANALYTICS_BASE}?{urlencode(params)}"
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        data = r.json()
        if "error" in data:
            print(f"[yt-analytics] API error: {data['error'].get('message')}")
        return data
    except Exception as e:
        return {"error": str(e)}


def _parse_rows(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not data or "rows" not in data or "columnHeaders" not in data:
        return []
    headers = [c["name"] for c in data["columnHeaders"]]
    return [dict(zip(headers, row)) for row in data["rows"]]


# ─── Per-video ────────────────────────────────────────────────────
def get_video_analytics(video_id: str,
                        start: Optional[str] = None,
                        end: Optional[str] = None) -> Optional[Dict[str, Any]]:
    data = _fetch_analytics({
        "startDate": start or _date_str(90),
        "endDate":   end   or _date_str(0),
        "metrics":   ("views,estimatedMinutesWatched,averageViewDuration,"
                      "averageViewPercentage,likes,dislikes,comments,shares,"
                      "subscribersGained,subscribersLost,"
                      "videosAddedToPlaylists,videosRemovedFromPlaylists"),
        "dimensions": "video",
        "filters":    f"video=={video_id}",
    })
    rows = _parse_rows(data)
    return rows[0] if rows else None


def get_retention_curve(video_id: str) -> List[Dict[str, Any]]:
    data = _fetch_analytics({
        "startDate":  _date_str(365),
        "endDate":    _date_str(0),
        "metrics":    "audienceWatchRatio,relativeRetentionPerformance",
        "dimensions": "elapsedVideoTimeRatio",
        "filters":    f"video=={video_id}",
        "sort":       "elapsedVideoTimeRatio",
    })
    return _parse_rows(data)


def get_traffic_sources(video_id: Optional[str] = None,
                        start: Optional[str] = None,
                        end: Optional[str] = None) -> List[Dict[str, Any]]:
    params = {
        "startDate":  start or _date_str(30),
        "endDate":    end   or _date_str(0),
        "metrics":    "views,estimatedMinutesWatched,averageViewDuration",
        "dimensions": "insightTrafficSourceType",
        "sort":       "-views",
    }
    if video_id:
        params["filters"] = f"video=={video_id}"
    return _parse_rows(_fetch_analytics(params))


# ─── Demographics ─────────────────────────────────────────────────
def get_demographics(start: Optional[str] = None,
                     end: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    s = start or _date_str(90)
    e = end   or _date_str(0)

    def _try(params):
        try:
            return _parse_rows(_fetch_analytics(params))
        except Exception:
            return []

    return {
        "ageGender": _try({
            "startDate": s, "endDate": e,
            "metrics": "viewerPercentage",
            "dimensions": "ageGroup,gender",
        }),
        "geography": _try({
            "startDate": s, "endDate": e,
            "metrics": "views,estimatedMinutesWatched",
            "dimensions": "country", "sort": "-views", "maxResults": "20",
        }),
        "devices": _try({
            "startDate": s, "endDate": e,
            "metrics": "views,estimatedMinutesWatched",
            "dimensions": "deviceType",
        }),
        "os": _try({
            "startDate": s, "endDate": e,
            "metrics": "views",
            "dimensions": "operatingSystem", "sort": "-views", "maxResults": "10",
        }),
        "subscribedStatus": _try({
            "startDate": s, "endDate": e,
            "metrics": "views",
            "dimensions": "subscribedStatus",
        }),
    }


# ─── Time series ──────────────────────────────────────────────────
def get_subscriber_growth(start: Optional[str] = None,
                          end: Optional[str] = None) -> List[Dict[str, Any]]:
    return _parse_rows(_fetch_analytics({
        "startDate":  start or _date_str(30),
        "endDate":    end   or _date_str(0),
        "metrics":    "subscribersGained,subscribersLost,views",
        "dimensions": "day", "sort": "day",
    }))


def get_daily_views(start: Optional[str] = None,
                    end: Optional[str] = None) -> List[Dict[str, Any]]:
    return _parse_rows(_fetch_analytics({
        "startDate":  start or _date_str(30),
        "endDate":    end   or _date_str(0),
        "metrics":    ("views,estimatedMinutesWatched,averageViewDuration,"
                       "likes,comments,shares,subscribersGained"),
        "dimensions": "day", "sort": "day",
    }))


# ─── Revenue ──────────────────────────────────────────────────────
def get_revenue(start: Optional[str] = None,
                end: Optional[str] = None) -> Optional[Dict[str, Any]]:
    rows = _parse_rows(_fetch_analytics({
        "startDate": start or _date_str(30),
        "endDate":   end   or _date_str(0),
        "metrics":   ("estimatedRevenue,estimatedAdRevenue,grossRevenue,cpm,"
                      "playbackBasedCpm,adImpressions,monetizedPlaybacks"),
    }))
    return rows[0] if rows else None


def get_revenue_daily(start: Optional[str] = None,
                      end: Optional[str] = None) -> List[Dict[str, Any]]:
    return _parse_rows(_fetch_analytics({
        "startDate":  start or _date_str(30),
        "endDate":    end   or _date_str(0),
        "metrics":    "estimatedRevenue,cpm,adImpressions",
        "dimensions": "day", "sort": "day",
    }))


# ─── Top videos / search / playback / sharing ─────────────────────
def get_top_videos(metric: str = "views",
                   start: Optional[str] = None,
                   end: Optional[str] = None,
                   max_results: int = 10) -> List[Dict[str, Any]]:
    return _parse_rows(_fetch_analytics({
        "startDate":  start or _date_str(30),
        "endDate":    end   or _date_str(0),
        "metrics":    metric,
        "dimensions": "video",
        "sort":       f"-{metric}",
        "maxResults": str(max_results),
    }))


def get_search_terms(video_id: Optional[str] = None,
                     start: Optional[str] = None,
                     end: Optional[str] = None) -> List[Dict[str, Any]]:
    filters = "insightTrafficSourceType==YT_SEARCH"
    if video_id:
        filters += f";video=={video_id}"
    return _parse_rows(_fetch_analytics({
        "startDate":  start or _date_str(30),
        "endDate":    end   or _date_str(0),
        "metrics":    "views",
        "dimensions": "insightTrafficSourceDetail",
        "filters":    filters,
        "sort":       "-views",
        "maxResults": "50",
    }))


def get_views_by_playback(start: Optional[str] = None,
                          end: Optional[str] = None) -> List[Dict[str, Any]]:
    return _parse_rows(_fetch_analytics({
        "startDate":  start or _date_str(30),
        "endDate":    end   or _date_str(0),
        "metrics":    "views,estimatedMinutesWatched",
        "dimensions": "insightPlaybackLocationType",
        "sort":       "-views",
    }))


def get_sharing_service(start: Optional[str] = None,
                        end: Optional[str] = None) -> List[Dict[str, Any]]:
    return _parse_rows(_fetch_analytics({
        "startDate":  start or _date_str(30),
        "endDate":    end   or _date_str(0),
        "metrics":    "shares",
        "dimensions": "sharingService",
        "sort":       "-shares",
        "maxResults": "20",
    }))


def get_playlist_analytics(start: Optional[str] = None,
                           end: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = _parse_rows(_fetch_analytics({
        "startDate":  start or _date_str(30),
        "endDate":    end   or _date_str(0),
        "metrics":    ("views,estimatedMinutesWatched,averageViewDuration,"
                       "playlistStarts,viewsPerPlaylistStart,"
                       "averageTimeInPlaylist"),
        "dimensions": "playlist",
        "sort":       "-views",
        "maxResults": "25",
    }))
    # Enrich with playlist titles via Data API
    ids = [r["playlist"] for r in rows if r.get("playlist")]
    if ids:
        titles = _get_playlist_titles(ids)
        for r in rows:
            r["playlist_title"] = titles.get(r.get("playlist"), r.get("playlist"))
    return rows


def _get_playlist_titles(playlist_ids: List[str]) -> Dict[str, str]:
    key = _api_key()
    if not (key and playlist_ids):
        return {}
    titles: Dict[str, str] = {}
    for i in range(0, len(playlist_ids), 50):
        batch = ",".join(playlist_ids[i:i+50])
        try:
            r = requests.get(
                f"{YOUTUBE_DATA_BASE}/playlists",
                params={"part": "snippet", "id": batch,
                        "maxResults": 50, "key": key},
                timeout=15,
            )
            for it in r.json().get("items", []):
                titles[it["id"]] = it.get("snippet", {}).get("title", it["id"])
        except Exception:
            pass
    return titles


# ─── Batch analytics for many videos (matches TS getBatchVideoAnalytics) ──
def get_batch_video_analytics(video_ids: List[str],
                              start: Optional[str] = None,
                              end: Optional[str] = None
                              ) -> Dict[str, Dict[str, Any]]:
    if not video_ids:
        return {}
    s = start or _date_str(90)
    e = end   or _date_str(0)
    result: Dict[str, Dict[str, Any]] = {}

    # Core metrics — batches of 50
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        data = _fetch_analytics({
            "startDate": s, "endDate": e,
            "metrics": ("views,estimatedMinutesWatched,averageViewDuration,"
                        "averageViewPercentage,likes,dislikes,comments,"
                        "shares,subscribersGained"),
            "dimensions": "video",
            "filters":    "video==" + ",".join(batch),
            "maxResults": "50",
        })
        for r in _parse_rows(data):
            vid = r.get("video")
            if vid:
                result[vid] = {**r, "period_start": s, "period_end": e}

    # Card metrics — batches of 30
    for i in range(0, len(video_ids), 30):
        batch = video_ids[i:i+30]
        data = _fetch_analytics({
            "startDate": s, "endDate": e,
            "metrics": "cardImpressions,cardClicks,cardClickRate",
            "dimensions": "video",
            "filters":    "video==" + ",".join(batch),
            "maxResults": "30",
        })
        for r in _parse_rows(data):
            vid = r.get("video")
            if vid and vid in result:
                result[vid]["cardImpressions"] = r.get("cardImpressions", 0)
                result[vid]["cardClicks"]      = r.get("cardClicks", 0)
                ccr = r.get("cardClickRate")
                result[vid]["cardCTR"] = round(ccr * 100, 2) if ccr else None

    return result


# ─── CLI ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    print("Testing YouTube Analytics API...")
    print()
    print("─ Daily views (last 7 days) ─")
    print(json.dumps(get_daily_views(_date_str(6), _date_str(0)),
                     indent=2, default=str))
    print()
    print("─ Revenue (last 30 days) ─")
    print(json.dumps(get_revenue(), indent=2, default=str))
    print()
    print("─ Top 5 videos by views (last 30 days) ─")
    print(json.dumps(get_top_videos("views", max_results=5),
                     indent=2, default=str))
    print()
    print("─ Traffic sources (last 30 days) ─")
    print(json.dumps(get_traffic_sources(), indent=2, default=str))
    print()
    print("─ Demographics ─")
    print(json.dumps(get_demographics(), indent=2, default=str))
