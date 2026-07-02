#!/usr/bin/env python3
"""Daily pipeline orchestrator. Runs all scrapers + sends alerts."""
"""
daily_pipeline.py — MASTER ORCHESTRATOR
All 7 layers + YouTube + LinkedIn. reporting_engine handles ALL notifications.
"""
import sys
import traceback
from datetime import datetime

from storage_adapter import get_storage_status, SHEETS_AVAILABLE
from sheets_writer import write_run_summary


def log(msg):
    print(msg, flush=True)


def run_stage(num, name, func):
    log(f"\n{'='*70}")
    log(f"STAGE {num}: {name}")
    log(f"{'='*70}")
    try:
        func()
        log(f"STAGE {num} COMPLETE: {name}")
        return True, None
    except Exception as e:
        log(f"STAGE {num} FAILED: {name}")
        log(f"  Error: {e}")
        traceback.print_exc()
        return False, str(e)


def main():
    start = datetime.now()
    log(f"\n{'='*70}")
    log(f"PIPELINE START: {start.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"Sheets available: {SHEETS_AVAILABLE}")
    log(f"{'='*70}")

    # Ensure all required Google Sheet tabs exist
    try:
        from sheets_writer import ensure_tabs_exist
        _created = ensure_tabs_exist()
        if _created:
            log(f"✅ Created missing sheet tabs: {', '.join(_created)}")
    except Exception as e:
        log(f"⚠️ ensure_tabs_exist: {e}")

    results = {}

    # ── STAGE 0: Fill any data gaps from missed pipeline runs ──
    try:
        from data_gap_filler import run as _fill_gaps
        log("STAGE 0: Checking for data gaps...")
        _gap_result = _fill_gaps()
        log(f"Gap filler: initial={_gap_result.get('initial_gaps',0)} final={_gap_result.get('final_gaps',0)}")
    except Exception as _ge:
        log(f"Gap filler error (non-fatal): {_ge}")

    def s1():
        # Run scrape_kpi.py as subprocess - guarantees fresh interpreter without asyncio loop
        import subprocess as _sp, sys as _sys
        log("Running scrape_kpi.py as subprocess (clean asyncio context)...")
        r = _sp.run([_sys.executable, "scrape_kpi.py"], capture_output=False)
        if r.returncode != 0:
            raise RuntimeError(f"scrape_kpi.py exited with code {r.returncode}")
        # Validate
        from sheets_writer import read_tab_data
        free_rows = read_tab_data("Raw_FREE")
        upload_rows = read_tab_data("Raw_FIRST_UPLOAD")
        if not free_rows and not upload_rows:
            raise RuntimeError("KPI scrape produced zero rows")
        log(f"KPI validation: FREE={len(free_rows)}, UPLOAD={len(upload_rows)}")
    ok1, e1 = run_stage(1, "Scrape KPI (Layer 1+2)", s1)
    results["stage1_kpi"] = "ok" if ok1 else f"failed: {e1}"

    def s2():
        import subprocess as _sp, sys as _sys
        log("Running scrape_stripe.py as subprocess...")
        r = _sp.run([_sys.executable, "scrape_stripe.py"], capture_output=False)
        if r.returncode != 0:
            raise RuntimeError(f"scrape_stripe.py exited with code {r.returncode}")
        # Validate: Stripe scrape produced data
        from sheets_writer import read_tab_data
        stripe_rows = read_tab_data("Raw_STRIPE")
        if not stripe_rows:
            raise RuntimeError("Stripe scrape produced zero rows")
        # Check for date columns
        has_dates = any(r.get("Created") or r.get("First payment") or r.get("Payment_Date") for r in stripe_rows[:5])
        if not has_dates and stripe_rows:
            log("WARNING: Stripe rows missing date fields (Created/First payment/Payment_Date)")
        log(f"Stripe validation: {len(stripe_rows)} rows")
    ok2, e2 = run_stage(2, "Scrape Stripe (Layer 1+2)", s2)
    results["stage2_stripe"] = "ok" if ok2 else f"failed: {e2}"

    def s3():
        from process_data import main as run
        run()
        # Validate: Processing produced ACCEPTED records
        from sheets_writer import read_tab_data
        for tab in ["Verified_FREE", "Verified_FIRST_UPLOAD", "Verified_STRIPE"]:
            rows = read_tab_data(tab)
            accepted = [r for r in rows if str(r.get("final_status", "")).upper() == "ACCEPTED"]
            log(f"Process validation: {tab} ACCEPTED={len(accepted)}/{len(rows)}")
            if len(accepted) == 0 and len(rows) > 0:
                log(f"WARNING: {tab} has 0 ACCEPTED out of {len(rows)} rows")
    ok3, e3 = run_stage(3, "Process: Validate + Dedup + ML (Layers 3-5)", s3)
    results["stage3_process"] = "ok" if ok3 else f"failed: {e3}"

    def s4():
        from pathlib import Path as _P
        import shutil as _sh
        # Save previous counts for anomaly detection before rebuilding
        _dc_path = _P("data_output") / "daily_counts.json"
        if _dc_path.exists():
            try:
                _sh.copy2(_dc_path, _P("data_output") / "daily_counts_prev.json")
                log("Preserved previous daily counts for anomaly detection")
            except Exception:
                pass
        from daily_counts import build_daily_counts_table
        result = build_daily_counts_table()
        # Validate: Daily counts have data
        if result.get("daily_rows", 0) == 0:
            raise RuntimeError("Daily counts produced zero rows")
        if result.get("free_accepted", 0) == 0 and result.get("upload_accepted", 0) == 0 and result.get("stripe_accepted", 0) == 0:
            raise RuntimeError("Daily counts: all metrics zero")
        log(f"Daily counts validation: {result}")
    ok4, e4 = run_stage(4, "Build Daily/Monthly Counts (Layer 6)", s4)
    results["stage4_counts"] = "ok" if ok4 else f"failed: {e4}"

    # ── YouTube Data Fetch (Stage 5) ──
    def s5():
        from youtube_connector import get_channel_info, get_channel_videos, get_daily_analytics, is_configured
        from pathlib import Path as _P
        import json as _json
        if not is_configured():
            log("YouTube: Not configured — skipping")
            return
        log("YouTube: Fetching channel info...")
        ch = get_channel_info()
        log(f"YouTube: Channel = {ch.get('title', 'N/A')}, Subscribers = {ch.get('subscribers', 0):,}")

        # Save channel snapshot daily
        try:
            _yt_cache_dir = _P("data_output")
            _yt_cache_dir.mkdir(exist_ok=True)
            # Save channel info
            _ch_path = _yt_cache_dir / "youtube_channel.json"
            _ch_path.write_text(_json.dumps(ch, indent=2, default=str))
            log(f"YouTube: Channel info saved")
        except Exception as e:
            log(f"YouTube: Channel save error: {e}")

        log("YouTube: Fetching video list...")
        videos = get_channel_videos(max_videos=200)
        log(f"YouTube: Got {len(videos)} videos")

        # Save video list
        try:
            _vid_path = _P("data_output") / "youtube_videos.json"
            _vid_path.write_text(_json.dumps(videos, indent=2, default=str))
            log(f"YouTube: Videos saved ({len(videos)})")
        except Exception as e:
            log(f"YouTube: Video save error: {e}")

        # Build daily time-series from video publish dates (available without OAuth)
        try:
            from collections import defaultdict as _dd
            _yt_daily = _dd(lambda: {"youtube_views": 0, "youtube_likes": 0, "youtube_comments": 0, "youtube_videos": 0})
            for v in videos:
                vd = v.get("published_at", "")
                if vd:
                    vdate = vd[:10]
                    _yt_daily[vdate]["youtube_views"] += v.get("views", 0)
                    _yt_daily[vdate]["youtube_likes"] += v.get("likes", 0)
                    _yt_daily[vdate]["youtube_comments"] += v.get("comments", 0)
                    _yt_daily[vdate]["youtube_videos"] += 1
            _daily_path = _P("data_output") / "youtube_daily.json"
            # Merge with existing daily data
            _existing = {}
            if _daily_path.exists():
                try:
                    _existing = _json.loads(_daily_path.read_text())
                except Exception:
                    pass
            for d, vals in _yt_daily.items():
                _existing[d] = vals  # Overwrite with latest
            _daily_path.write_text(_json.dumps(_existing, indent=2, sort_keys=True, default=str))
            log(f"YouTube: Daily time-series saved ({len(_existing)} days)")
        except Exception as e:
            log(f"YouTube: Daily build error: {e}")

        # Analytics (if OAuth token available)
        try:
            from youtube_connector import has_analytics_access, get_daily_analytics
            if has_analytics_access():
                from datetime import timedelta
                start_d = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
                end_d = datetime.now().strftime("%Y-%m-%d")
                daily = get_daily_analytics(start_d, end_d)
                log(f"YouTube Analytics: Got {len(daily)} days of data")
                # Save analytics data
                if not daily.empty:
                    _analytics_path = _P("data_output") / "youtube_analytics.json"
                    _analytics_path.write_text(daily.to_json(orient="records", indent=2))
                    log(f"YouTube Analytics: Saved to {_analytics_path}")
            else:
                log("YouTube: No OAuth credentials — Analytics API skipped")
        except Exception as e:
            log(f"YouTube Analytics: Error ({e})")
        
        # Validate YouTube data exists
        from sheets_writer import read_tab_data
        yt_channel = read_tab_data("YouTube")
        if yt_channel and len(yt_channel) > 0:
            log(f"YouTube validation: Channel data OK ({len(yt_channel)} rows)")
        else:
            log("WARNING: YouTube channel data not in Sheets")
    ok5, e5 = run_stage(5, "YouTube Data Fetch", s5)
    results["stage5_youtube"] = "ok" if ok5 else f"failed: {e5}"

    # Also fetch YouTube Command Center data for cache
    try:
        from youtube_command_center import fetch_command_center_data
        log("Fetching YouTube Command Center cache...")
        _yt_cc = fetch_command_center_data(period_days=30)
        log(f"YouTube CC: {len(_yt_cc.get('videos',[]))} videos cached")
    except Exception as _yte:
        log(f"YouTube CC cache (non-fatal): {_yte}")

    # ── LinkedIn Scrape via Daily Pipeline (Stage 6) ──
    def s6():
        """Run our LinkedIn daily pipeline as subprocess - writes to MongoDB + JSON cache."""
        import subprocess as _sp, sys as _sys
        log("Running linkedin_daily_pipeline.py as subprocess...")
        r = _sp.run([_sys.executable, "linkedin_daily_pipeline.py"], capture_output=False)
        if r.returncode != 0:
            log(f"LinkedIn pipeline exited with code {r.returncode} (non-fatal)")
        # Also keep legacy linkedin_connector daily entry for backward compat
        try:
            from linkedin_connector import scrape_authenticated, save_daily_entry
            log("LinkedIn: Also running legacy daily entry save...")
            try:
                result = scrape_authenticated()
                if result and not result.get("error"):
                    save_daily_entry({
                        "date":      datetime.now().strftime("%Y-%m-%d"),
                        "followers": result.get("followers", 0),
                        "posts":     len(result.get("posts", [])),
                        "source":    "playwright",
                    })
                    log(f"LinkedIn legacy entry saved: {result.get('followers',0)} followers")
            except Exception as _le:
                log(f"LinkedIn legacy entry error (non-fatal): {_le}")
        except Exception as _e:
            log(f"LinkedIn legacy connector unavailable (non-fatal): {_e}")
    ok6, e6 = run_stage(6, "LinkedIn (MongoDB + legacy)", s6)
    results["stage6_linkedin"] = "ok" if ok6 else f"failed: {e6}"

    # ── Reporting (Stage 7) ──
    def s7():
        # Cache GA4 data for reporting engine fallback
        try:
            from ga4_connector import is_configured as ga4_ok, fetch_utm_traffic, fetch_geo_traffic
            if ga4_ok():
                from datetime import timedelta as _td
                _end = datetime.now().strftime("%Y-%m-%d")
                _start = (datetime.now() - _td(days=30)).strftime("%Y-%m-%d")
                _utm = fetch_utm_traffic(_start, _end)
                _geo = fetch_geo_traffic(_start, _end)
                _cache = {"scraped_at": datetime.now().isoformat()}
                if not _utm.empty:
                    _cache["total_sessions"] = int(_utm.get("sessions", 0).sum()) if "sessions" in _utm.columns else 0
                    _cache["total_users"] = int(_utm.get("activeUsers", 0).sum()) if "activeUsers" in _utm.columns else 0
                    if "sourceMedium" in _utm.columns:
                        _top = _utm.groupby("sourceMedium")["sessions"].sum().sort_values(ascending=False).head(5)
                        _cache["top_sources"] = [(s, int(v)) for s, v in _top.items()]
                if not _geo.empty and "country" in _geo.columns:
                    _top = _geo.groupby("country")["sessions"].sum().sort_values(ascending=False).head(5)
                    _cache["top_countries"] = [(c, int(v)) for c, v in _top.items()]
                import json as _json
                _P("data_output").mkdir(exist_ok=True)
                (_P("data_output") / "ga4_traffic_cache.json").write_text(_json.dumps(_cache, default=str, indent=2))
                log(f"GA4 cache saved: {_cache.get('total_sessions', 0)} sessions")
        except Exception as e:
            log(f"GA4 cache error (non-fatal): {e}")
        # Legacy reporting_engine.main() DISABLED - all_alerts.py sends 12 new alerts
        log("Stage 7: GA4 cache saved. Alerts handled by all_alerts.py at end of pipeline.")
    ok7, e7 = run_stage(7, "Reporting + Notifications (Layer 6)", s7)
    results["stage7_report"] = "ok" if ok7 else f"failed: {e7}"

    duration = (datetime.now() - start).total_seconds()
    passed   = sum([ok1, ok2, ok3, ok4, ok5, ok6, ok7])

    log(f"\n{'='*70}")
    log(f"PIPELINE DONE: {passed}/7 stages passed | {duration:.1f}s")
    log(f"{'='*70}")
    for k, v in results.items():
        icon = "OK" if v == "ok" else "FAIL"
        log(f"  [{icon}] {k}: {v}")

    # ── SEND ALL ALERTS (runs even if some stages failed) ──
    try:
        from anomaly_detector import detect_and_alert
        log("Running anomaly detection...")
        _anomalies = detect_and_alert()
        log(f"Anomaly alerts: {len(_anomalies)} sent")
    except Exception as _ade:
        log(f"Anomaly detection error: {_ade}")

    try:
        from all_alerts import run_all as _send_all_alerts
        log("Sending all 12 alerts to Telegram group...")
        _sent = _send_all_alerts()
        log(f"Sent {_sent}/12 alerts")
    except Exception as _ae:
        log(f"All alerts error: {_ae}")

    # PIPELINE FAILURE CHECK: Fail if any stage failed
    failed_stages = [k for k, v in results.items() if v != "ok"]
    if failed_stages:
        log(f"\n{'='*70}")
        log(f"PIPELINE FAILED: {len(failed_stages)} stage(s) failed: {', '.join(failed_stages)}")
        log(f"{'='*70}")
        sys.exit(1)
    else:
        log(f"\n{'='*70}")
        log("PIPELINE SUCCESS: All 7 stages passed validation")
        log(f"{'='*70}")

    log(f"\n{'='*60}")
    log("FINAL SHEETS STATE")
    log(f"{'='*60}")
    try:
        from sheets_writer import read_tab_data
        for tab in ["Raw_FREE", "Raw_FIRST_UPLOAD", "Raw_STRIPE",
                    "Verified_FREE", "Verified_FIRST_UPLOAD", "Verified_STRIPE",
                    "Daily_Counts", "Monthly_Counts"]:
            try:
                rows = read_tab_data(tab)
                log(f"  {tab:30s}: {len(rows):>5} rows")
            except Exception:
                log(f"  {tab:30s}: ERROR")
    except Exception as e:
        log(f"State check error: {e}")

    try:
        write_run_summary({
            "run_at":           start.isoformat(),
            "duration_seconds": round(duration, 1),
            "stages_passed":    passed,
            **results,
        })
    except Exception as e:
        log(f"Summary write failed: {e}")

    # Save pipeline health for reporting engine
    try:
        from pathlib import Path as _P
        _health_path = _P("data_output") / "pipeline_health.json"
        _health_path.parent.mkdir(exist_ok=True)
        import json as _json
        with open(_health_path, "w") as _hf:
            _json.dump({
                "last_run":           start.isoformat(),
                "duration_seconds":   round(duration, 1),
                "stages_passed":      passed,
                "total_stages":       7,
                "results":            results,
            }, _hf, indent=2)
        log(f"Pipeline health saved: {_health_path}")
    except Exception as e:
        log(f"Pipeline health save failed: {e}")

    return 0




    # ── STAGE: Customer Success Pipeline ──
    try:
        from customer_success_scraper import run_full_pipeline as _cs_pipeline
        print("\n[Daily] Running Customer Success scraper...")
        _cs_result = _cs_pipeline()
        print(f"[Daily] Customer Success: {_cs_result}")
    except Exception as _cs_e:
        print(f"[Daily] Customer Success error: {_cs_e}")

    # ── STAGE: LinkedIn Daily Pipeline ──
    try:
        from linkedin_daily_pipeline import run_daily_pipeline as _li_pipeline
        print("\n[Daily] Running LinkedIn pipeline...")
        _li_pipeline()
    except Exception as _li_e:
        print(f"[Daily] LinkedIn pipeline error: {_li_e}")






        # ── ANOMALY DETECTION: Send instant alerts for spikes/drops/flatlines ──
    try:
        from anomaly_detector import detect_and_alert
        log("Running anomaly detection...")
        _anomalies = detect_and_alert()
        log(f"Anomaly alerts: {len(_anomalies)} sent")
    except Exception as _ade:
        log(f"Anomaly detection error: {_ade}")



if __name__ == "__main__":
    sys.exit(main())
