#!/usr/bin/env python3
"""
daily_pipeline.py — Eagle 3D Streaming Analytics Hub
======================================================
Master orchestrator. Runs all scrapers + aggregators + alerts.
100% MongoDB. No Sheets.

Stages:
  0. Gap filler
  1. Scrape KPI dashboard
  2. Scrape Stripe (cookies)
  3. Process + dedupe + validate
  4. Build daily/monthly counts
  5. YouTube fetch
  6. LinkedIn (daily pipeline)
  7. Customer Success scrape
  8. GA4 cache
  9. Anomaly detection
 10. Send all alerts to Telegram
"""

from __future__ import annotations

import subprocess
import sys
import traceback
from datetime import datetime
from typing import Callable, Tuple


def log(msg: str) -> None:
    print(msg, flush=True)


def run_stage(num: int, name: str, fn: Callable) -> Tuple[bool, str]:
    log("\n" + "=" * 70)
    log(f"STAGE {num}: {name}")
    log("=" * 70)
    try:
        fn()
        log(f"STAGE {num} OK: {name}")
        return True, ""
    except Exception as e:
        log(f"STAGE {num} FAILED: {name}")
        log(f"  Error: {e}")
        traceback.print_exc()
        return False, str(e)


def _run_subprocess(script: str) -> None:
    log(f"Running {script} as subprocess...")
    r = subprocess.run([sys.executable, script], capture_output=False)
    if r.returncode != 0:
        raise RuntimeError(f"{script} exited with code {r.returncode}")


def main() -> int:
    start = datetime.now()
    log("\n" + "=" * 70)
    log(f"PIPELINE START: {start.strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 70)

    results = {}

    # STAGE 0: Data gap filler
    def s0():
        from data_gap_filler import fill_gaps
        r = fill_gaps()
        log(f"Gap filler: initial={r.get('initial_gaps',0)} final={r.get('final_gaps',0)}")
    ok, err = run_stage(0, "Data Gap Filler", s0)
    results["stage0_gaps"] = "ok" if ok else f"failed: {err}"

    # STAGE 1: KPI scrape (single-session with fresh Firebase login)
    def s1():
        _run_subprocess("scrape_kpi.py")
        from mongo_client import count_docs
        n = count_docs("signups")
        log(f"KPI validation: signups collection has {n} rows")
        if n == 0:
            raise RuntimeError("KPI scrape produced zero rows in signups")
    ok, err = run_stage(1, "Scrape KPI dashboard", s1)
    results["stage1_kpi"] = "ok" if ok else f"failed: {err}"

    # STAGE 2: Stripe scrape
    def s2():
        _run_subprocess("scrape_stripe.py")
        from mongo_client import count_docs
        n = count_docs("payments")
        log(f"Stripe validation: payments collection has {n} rows")
    ok, err = run_stage(2, "Scrape Stripe (cookies)", s2)
    results["stage2_stripe"] = "ok" if ok else f"failed: {err}"

    # STAGE 3: Process
    def s3():
        from process_data import main as run
        run()
        from mongo_client import count_accepted
        for col, field in (("signups", "signup_date"),
                           ("uploads", "upload_date"),
                           ("payments", "first_payment_date")):
            n = count_accepted(col, field)
            log(f"Process validation: {col} ACCEPTED={n}")
    ok, err = run_stage(3, "Process + validate", s3)
    results["stage3_process"] = "ok" if ok else f"failed: {err}"

    # STAGE 4: Daily counts
    def s4():
        from daily_counts import build_daily_counts_table
        r = build_daily_counts_table()
        log(f"Daily counts: {r}")
        if r.get("daily_rows", 0) == 0:
            raise RuntimeError("No daily counts produced")
    ok, err = run_stage(4, "Build daily/monthly counts", s4)
    results["stage4_counts"] = "ok" if ok else f"failed: {err}"

    # STAGE 4B: Rebuild daily_kpis from raw ACCEPTED counts (source of truth)
    def s4b():
        from pipeline_gap_scanner import rebuild_from_raw, scan_gaps
        r = rebuild_from_raw()
        log(f"Rebuild: {r.get('rebuilt_days', 0)} days | "
            f"S:{r.get('signups_total', 0)} U:{r.get('uploads_total', 0)} P:{r.get('paid_total', 0)}")
        gap = scan_gaps()
        log(f"Post-rebuild health: {gap['health_pct']}% "
            f"({gap['missing_count']} missing, {gap['zero_count']} zero-only)")
    ok, err = run_stage(43, "Rebuild daily_kpis from raw", s4b)
    results["stage4b_rebuild"] = "ok" if ok else f"failed: {err}"

    # STAGE 5: YouTube
    def s5():
        try:
            from youtube_connector import (
                get_channel_info, get_channel_videos, is_configured
            )
        except ImportError:
            log("YouTube connector missing — skipping")
            return
        if not is_configured():
            log("YouTube: not configured — skipping")
            return

        ch = get_channel_info()
        log(f"YouTube channel: {ch.get('title','N/A')}, "
            f"subs={int(ch.get('subscribers',0)):,}")

        from mongo_client import upsert_one, upsert_many
        upsert_one("youtube_channel", ch, ["channel_id"])

        vids = get_channel_videos(max_videos=200)
        log(f"YouTube videos: {len(vids)}")
        if vids:
            upsert_many("youtube_videos", vids, "video_id")
    ok, err = run_stage(5, "YouTube fetch", s5)
    results["stage5_youtube"] = "ok" if ok else f"failed: {err}"

    # STAGE 6: LinkedIn
    def s6():
        _run_subprocess("linkedin_daily_pipeline.py")
    ok, err = run_stage(6, "LinkedIn daily pipeline", s6)
    results["stage6_linkedin"] = "ok" if ok else f"failed: {err}"

    # STAGE 7: Customer Success
    def s7():
        try:
            from customer_success_scraper import run_full_pipeline
            r = run_full_pipeline()
            log(f"Customer Success: {r}")
        except ImportError:
            log("Customer Success scraper missing — skipping")
    ok, err = run_stage(7, "Customer Success scrape", s7)
    results["stage7_cs"] = "ok" if ok else f"failed: {err}"

    # STAGE 8: GA4
    def s8():
        try:
            from ga4_connector import (
                is_configured, fetch_utm_traffic, fetch_geo_traffic
            )
        except ImportError:
            log("GA4 connector missing — skipping")
            return
        if not is_configured():
            log("GA4: not configured — skipping")
            return

        from datetime import timedelta as _td
        from pathlib import Path
        import json as _json

        end = datetime.now().strftime("%Y-%m-%d")
        start_d = (datetime.now() - _td(days=30)).strftime("%Y-%m-%d")
        utm = fetch_utm_traffic(start_d, end)
        geo = fetch_geo_traffic(start_d, end)

        cache = {"scraped_at": datetime.now().isoformat()}
        if not utm.empty:
            cache["total_sessions"] = int(utm.get("sessions", 0).sum())
            cache["total_users"]    = int(utm.get("activeUsers", 0).sum())
            if "sourceMedium" in utm.columns:
                top = utm.groupby("sourceMedium")["sessions"].sum() \
                        .sort_values(ascending=False).head(5)
                cache["top_sources"] = [(s, int(v)) for s, v in top.items()]
        if not geo.empty and "country" in geo.columns:
            top = geo.groupby("country")["sessions"].sum() \
                    .sort_values(ascending=False).head(5)
            cache["top_countries"] = [(c, int(v)) for c, v in top.items()]

        Path("data_output").mkdir(exist_ok=True)
        (Path("data_output") / "ga4_traffic_cache.json").write_text(
            _json.dumps(cache, default=str, indent=2)
        )
        log(f"GA4 cache: {cache.get('total_sessions',0)} sessions")
    ok, err = run_stage(8, "GA4 fetch + cache", s8)
    results["stage8_ga4"] = "ok" if ok else f"failed: {err}"

    # ── Summary ──
    duration = (datetime.now() - start).total_seconds()
    passed = sum(1 for v in results.values() if v == "ok")
    total = len(results)

    log("\n" + "=" * 70)
    log(f"PIPELINE DONE: {passed}/{total} stages passed | {duration:.1f}s")
    log("=" * 70)
    for k, v in results.items():
        icon = "OK" if v == "ok" else "FAIL"
        log(f"  [{icon}] {k}: {v}")

    # ── Anomaly detection ──
    try:
        from anomaly_detector import detect_and_alert
        log("\nRunning anomaly detection...")
        anomalies = detect_and_alert()
        log(f"Anomalies: {len(anomalies)}")
    except Exception as e:
        log(f"Anomaly detection error: {e}")

    # ── Send all alerts + completion notice ──
    try:
        from all_alerts import run_all
        log("\nSending all alerts to Telegram...")
        sent = run_all()
        log(f"Sent {sent} alerts")
    except Exception as e:
        log(f"All alerts error: {e}")

    # ── Always send a pipeline completion Telegram alert ──
    try:
        from reporting_engine import send_telegram
        icon = "✅" if all(v == "ok" for v in results.values()) else "⚠️"
        summary_lines = [f"{icon} *Pipeline Run Complete*",
                          f"_{start.strftime('%Y-%m-%d %H:%M')} UTC_",
                          f"Duration: {duration:.0f}s",
                          f"Stages: {passed}/{total} passed",
                          ""]
        for k, v in results.items():
            emoji = "✅" if v == "ok" else "❌"
            summary_lines.append(f"{emoji} {k}: {v[:80]}")

        # Add current KPI snapshot
        try:
            from pipeline_gap_scanner import scan_gaps
            gap = scan_gaps()
            summary_lines.extend([
                "",
                f"📊 Data health: {gap['health_pct']}%",
                f"   {gap['missing_count']} missing days, {gap['zero_count']} zero-only",
            ])
        except Exception:
            pass

        send_telegram("\n".join(summary_lines))
        log("Completion alert sent to Telegram")
    except Exception as e:
        log(f"Completion alert failed: {e}")

    # ── Save pipeline health ──
    try:
        from pipeline_health import record_run
        record_run({
            "run_at":           start.isoformat(),
            "duration_seconds": round(duration, 1),
            "stages_passed":    passed,
            "total_stages":     total,
            "results":          results,
        })
        log("Pipeline health recorded")
    except Exception as e:
        log(f"Pipeline health save failed: {e}")

    failed = [k for k, v in results.items() if v != "ok"]
    if failed:
        log("\n" + "=" * 70)
        log(f"PIPELINE FAILED: {', '.join(failed)}")
        log("=" * 70)
        return 1

    log("\n" + "=" * 70)
    log("PIPELINE SUCCESS: all stages passed")
    log("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
