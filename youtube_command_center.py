#!/usr/bin/env python3
"""
YouTube Command Center - Full Analytics Replication
Replicates: https://youtube-command-center-eight.vercel.app/dashboard

Features:
- Real watch hours, views, revenue (YouTube Analytics API)
- Traffic sources breakdown
- Audience demographics
- Geography
- Devices
- Playlists
- Per-video performance scores
"""

import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path("data_output")
CACHE_FILE = DATA_DIR / "youtube_command_center.json"


def log(m):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [YT-CC] {m}", flush=True)


def _get_secret(key, default=""):
    val = os.environ.get(key, "")
    if not val:
        try:
            import streamlit as st
            val = str(st.secrets.get(key, "")).strip()
        except Exception:
            pass
    return val or default


def _refresh_oauth_token():
    """Refresh YouTube OAuth access token using refresh token."""
    refresh_token  = _get_secret("YOUTUBE_REFRESH_TOKEN")
    client_id      = _get_secret("YOUTUBE_CLIENT_ID")
    client_secret  = _get_secret("YOUTUBE_CLIENT_SECRET")

    if not all([refresh_token, client_id, client_secret]):
        log(f"Missing OAuth credentials: refresh={bool(refresh_token)} id={bool(client_id)} secret={bool(client_secret)}")
        return None

    try:
        data = urllib.parse.urlencode({
            "client_id":     client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type":    "refresh_token",
        }).encode()

        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=data,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            token = result.get("access_token")
            if token:
                log(f"OAuth token refreshed (expires in {result.get('expires_in',0)}s)")
                return token
            else:
                log(f"Token refresh response missing access_token: {result}")
    except Exception as e:
        log(f"OAuth refresh failed: {e}")
    return None


def _yt_analytics_request(access_token, params):
    """Call YouTube Analytics API v2."""
    base = "https://youtubeanalytics.googleapis.com/v2/reports"
    url = base + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if hasattr(e, "read") else ""
        log(f"Analytics HTTP {e.code}: {body[:200]}")
        return None
    except Exception as e:
        log(f"Analytics error: {e}")
        return None


def _yt_data_request(api_key, endpoint, params):
    """Call YouTube Data API v3."""
    params["key"] = api_key
    url = f"https://www.googleapis.com/youtube/v3/{endpoint}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if hasattr(e, "read") else ""
        log(f"Data API HTTP {e.code}: {body[:200]}")
        return None
    except Exception as e:
        log(f"Data API error: {e}")
        return None


def fetch_command_center_data(period_days=28):
    """
    Fetch all YouTube Command Center data.
    Returns dict with all metrics needed for full dashboard replication.
    """
    result = {
        "fetched_at":      datetime.utcnow().isoformat(),
        "period_days":     period_days,
        "channel":         {},
        "videos":          [],
        "analytics":       {},
        "traffic_sources": [],
        "geography":       [],
        "devices":         [],
        "demographics":    [],
        "playlists":       [],
        "revenue":         {},
        "subscribers":     {},
        "watch_time":      {},
        "engagement":      {},
        "error":           None,
        "oauth_status":    "unknown",
    }

    # Get credentials
    api_key     = _get_secret("YOUTUBE_API_KEY")
    channel_id  = _get_secret("YOUTUBE_CHANNEL_ID")
    access_token = _refresh_oauth_token()

    result["oauth_status"] = "ok" if access_token else "missing_or_invalid"

    if not api_key or not channel_id:
        result["error"] = "Missing YOUTUBE_API_KEY or YOUTUBE_CHANNEL_ID"
        return result

    end_date   = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=period_days)).strftime("%Y-%m-%d")

    # ── 1. CHANNEL INFO (Data API - works with API key) ──
    try:
        ch_resp = _yt_data_request(api_key, "channels", {
            "part": "snippet,statistics,brandingSettings,contentDetails",
            "id":   channel_id,
        })
        if ch_resp and ch_resp.get("items"):
            item = ch_resp["items"][0]
            stats = item.get("statistics", {})
            snip = item.get("snippet", {})
            result["channel"] = {
                "title":       snip.get("title", ""),
                "description": snip.get("description", ""),
                "subscribers": int(stats.get("subscriberCount", 0)),
                "total_views": int(stats.get("viewCount", 0)),
                "video_count": int(stats.get("videoCount", 0)),
                "country":     snip.get("country", ""),
                "thumbnail":   snip.get("thumbnails", {}).get("high", {}).get("url", ""),
            }
            log(f"Channel: {result['channel']['title']} ({result['channel']['subscribers']:,} subs)")
    except Exception as e:
        log(f"Channel fetch error: {e}")

    # ── 2. VIDEOS LIST (Data API) ──
    try:
        all_videos = []
        next_token = None
        for _ in range(10):  # max 500 videos
            params = {
                "part": "snippet",
                "channelId": channel_id,
                "maxResults": 50,
                "order": "date",
                "type": "video",
            }
            if next_token:
                params["pageToken"] = next_token

            vresp = _yt_data_request(api_key, "search", params)
            if not vresp:
                break
            video_ids = [it["id"]["videoId"] for it in vresp.get("items", []) if it.get("id", {}).get("videoId")]
            if not video_ids:
                break

            # Get statistics for these videos
            stats_resp = _yt_data_request(api_key, "videos", {
                "part": "statistics,snippet,contentDetails",
                "id": ",".join(video_ids),
            })
            if stats_resp:
                for v in stats_resp.get("items", []):
                    vs = v.get("statistics", {})
                    sn = v.get("snippet", {})
                    cd = v.get("contentDetails", {})
                    views = int(vs.get("viewCount", 0))
                    likes = int(vs.get("likeCount", 0))
                    comments = int(vs.get("commentCount", 0))
                    eng = ((likes + comments) / views * 100) if views > 0 else 0
                    pub_date = sn.get("publishedAt", "")
                    age_days = 1
                    if pub_date:
                        try:
                            pd = datetime.fromisoformat(pub_date.replace("Z",""))
                            age_days = max(1, (datetime.now() - pd).days)
                        except Exception:
                            pass
                    vpd = views / age_days if age_days else 0
                    # Performance score 0-100
                    score = 0
                    if views > 0:
                        score += min(40, views / 100)  # views weight
                        score += min(30, eng * 3)       # engagement weight
                        score += min(30, vpd * 2)       # velocity weight
                    score = int(min(100, score))
                    all_videos.append({
                        "id":            v.get("id", ""),
                        "title":         sn.get("title", ""),
                        "description":   sn.get("description", "")[:200],
                        "published_at":  pub_date,
                        "thumbnail":     sn.get("thumbnails", {}).get("high", {}).get("url", ""),
                        "views":         views,
                        "likes":         likes,
                        "comments":      comments,
                        "engagement":    round(eng, 2),
                        "age_days":      age_days,
                        "views_per_day": round(vpd, 1),
                        "score":         score,
                        "duration":      cd.get("duration", ""),
                        "url":           f"https://youtube.com/watch?v={v.get('id','')}",
                    })

            next_token = vresp.get("nextPageToken")
            if not next_token:
                break

        result["videos"] = all_videos
        log(f"Videos fetched: {len(all_videos)}")
    except Exception as e:
        log(f"Videos fetch error: {e}")

    # ── 3. PLAYLISTS (Data API) ──
    try:
        pl_resp = _yt_data_request(api_key, "playlists", {
            "part": "snippet,contentDetails",
            "channelId": channel_id,
            "maxResults": 50,
        })
        if pl_resp:
            for pl in pl_resp.get("items", []):
                sn = pl.get("snippet", {})
                cd = pl.get("contentDetails", {})
                result["playlists"].append({
                    "id":            pl.get("id", ""),
                    "title":         sn.get("title", ""),
                    "description":   sn.get("description", "")[:200],
                    "thumbnail":     sn.get("thumbnails", {}).get("high", {}).get("url", ""),
                    "video_count":   int(cd.get("itemCount", 0)),
                    "published_at":  sn.get("publishedAt", ""),
                })
            log(f"Playlists: {len(result['playlists'])}")
    except Exception as e:
        log(f"Playlists fetch error: {e}")

    # ── ANALYTICS API (requires OAuth) ──
    if access_token:
        # 4. Overall analytics
        try:
            ana = _yt_analytics_request(access_token, {
                "ids":        f"channel=={channel_id}",
                "startDate":  start_date,
                "endDate":    end_date,
                "metrics":    "views,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost,likes,comments,shares",
            })
            if ana and ana.get("rows"):
                row = ana["rows"][0]
                headers = [h.get("name","") for h in ana.get("columnHeaders", [])]
                d = dict(zip(headers, row))
                result["analytics"] = {
                    "views":               int(d.get("views", 0)),
                    "watch_hours":         round(d.get("estimatedMinutesWatched", 0) / 60, 1),
                    "avg_view_duration":   int(d.get("averageViewDuration", 0)),
                    "subscribers_gained":  int(d.get("subscribersGained", 0)),
                    "subscribers_lost":    int(d.get("subscribersLost", 0)),
                    "net_subs":            int(d.get("subscribersGained", 0)) - int(d.get("subscribersLost", 0)),
                    "likes":               int(d.get("likes", 0)),
                    "comments":            int(d.get("comments", 0)),
                    "shares":              int(d.get("shares", 0)),
                }
                log(f"Analytics: {result['analytics']['views']:,} views, {result['analytics']['watch_hours']}h watch")
        except Exception as e:
            log(f"Analytics fetch error: {e}")

        # 5. Traffic sources
        try:
            ts = _yt_analytics_request(access_token, {
                "ids":        f"channel=={channel_id}",
                "startDate":  start_date,
                "endDate":    end_date,
                "metrics":    "views",
                "dimensions": "insightTrafficSourceType",
                "sort":       "-views",
            })
            if ts and ts.get("rows"):
                for row in ts["rows"]:
                    result["traffic_sources"].append({
                        "source": row[0],
                        "views":  int(row[1]),
                    })
                log(f"Traffic sources: {len(result['traffic_sources'])}")
        except Exception as e:
            log(f"Traffic fetch error: {e}")

        # 6. Geography
        try:
            geo = _yt_analytics_request(access_token, {
                "ids":        f"channel=={channel_id}",
                "startDate":  start_date,
                "endDate":    end_date,
                "metrics":    "views,estimatedMinutesWatched",
                "dimensions": "country",
                "sort":       "-views",
                "maxResults": "20",
            })
            if geo and geo.get("rows"):
                for row in geo["rows"]:
                    result["geography"].append({
                        "country":     row[0],
                        "views":       int(row[1]),
                        "watch_hours": round(row[2] / 60, 1),
                    })
                log(f"Geography: {len(result['geography'])} countries")
        except Exception as e:
            log(f"Geography fetch error: {e}")

        # 7. Devices
        try:
            dev = _yt_analytics_request(access_token, {
                "ids":        f"channel=={channel_id}",
                "startDate":  start_date,
                "endDate":    end_date,
                "metrics":    "views",
                "dimensions": "deviceType",
                "sort":       "-views",
            })
            if dev and dev.get("rows"):
                for row in dev["rows"]:
                    result["devices"].append({
                        "device": row[0],
                        "views":  int(row[1]),
                    })
                log(f"Devices: {len(result['devices'])}")
        except Exception as e:
            log(f"Devices fetch error: {e}")

        # 8. Demographics (age + gender)
        try:
            demo = _yt_analytics_request(access_token, {
                "ids":        f"channel=={channel_id}",
                "startDate":  start_date,
                "endDate":    end_date,
                "metrics":    "viewerPercentage",
                "dimensions": "ageGroup,gender",
            })
            if demo and demo.get("rows"):
                for row in demo["rows"]:
                    result["demographics"].append({
                        "age":        row[0],
                        "gender":     row[1],
                        "percentage": round(float(row[2]), 2),
                    })
                log(f"Demographics: {len(result['demographics'])} segments")
        except Exception as e:
            log(f"Demographics fetch error: {e}")

        # 9. Revenue (monetary scope required)
        try:
            rev = _yt_analytics_request(access_token, {
                "ids":        f"channel=={channel_id}",
                "startDate":  start_date,
                "endDate":    end_date,
                "metrics":    "estimatedRevenue,estimatedAdRevenue,grossRevenue,cpm,playbackBasedCpm,monetizedPlaybacks",
            })
            if rev and rev.get("rows"):
                row = rev["rows"][0]
                headers = [h.get("name","") for h in rev.get("columnHeaders", [])]
                d = dict(zip(headers, row))
                result["revenue"] = {
                    "estimated":         round(d.get("estimatedRevenue", 0), 2),
                    "ad_revenue":        round(d.get("estimatedAdRevenue", 0), 2),
                    "gross":             round(d.get("grossRevenue", 0), 2),
                    "cpm":               round(d.get("cpm", 0), 2),
                    "playback_cpm":      round(d.get("playbackBasedCpm", 0), 2),
                    "monetized_plays":   int(d.get("monetizedPlaybacks", 0)),
                }
                log(f"Revenue: ${result['revenue']['estimated']:.2f}")
        except Exception as e:
            log(f"Revenue fetch error (may not be monetized): {e}")
    else:
        log("OAuth token unavailable - analytics, revenue, demographics will be empty")

    # Save cache
    try:
        DATA_DIR.mkdir(exist_ok=True)
        CACHE_FILE.write_text(json.dumps(result, indent=2))
        log(f"Saved cache: {CACHE_FILE}")
    except Exception as e:
        log(f"Cache save error: {e}")

    return result


def get_cached_or_fetch(period_days=28, max_age_minutes=15):
    """Get from cache if fresh, otherwise fetch."""
    if CACHE_FILE.exists():
        try:
            cached = json.loads(CACHE_FILE.read_text())
            fetched_at = cached.get("fetched_at", "")
            if fetched_at:
                age = (datetime.utcnow() - datetime.fromisoformat(fetched_at)).total_seconds() / 60
                if age < max_age_minutes and cached.get("period_days") == period_days:
                    log(f"Using cache (age {age:.0f}min)")
                    return cached
        except Exception:
            pass
    return fetch_command_center_data(period_days)


if __name__ == "__main__":
    data = fetch_command_center_data(28)
    print(json.dumps({
        "channel":         data["channel"],
        "videos_count":    len(data["videos"]),
        "analytics":       data["analytics"],
        "traffic_sources": data["traffic_sources"][:5],
        "geography":       data["geography"][:5],
        "devices":         data["devices"],
        "revenue":         data["revenue"],
        "oauth_status":    data["oauth_status"],
        "error":           data["error"],
    }, indent=2))
