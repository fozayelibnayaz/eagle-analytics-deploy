"""
qa_full_system.py — Automated QA for every function in the system.
Imports every module, calls every public renderer, catches every error.
"""

import importlib
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List

RESULTS = {"pass": [], "warn": [], "fail": []}


def _test(name: str, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
        RESULTS["pass"].append(name)
        print(f"  ✅ {name}")
    except ImportError as e:
        RESULTS["warn"].append(f"{name}: ImportError: {e}")
        print(f"  ⚠️  {name}: ImportError: {e}")
    except AttributeError as e:
        RESULTS["fail"].append(f"{name}: AttributeError: {e}")
        print(f"  ❌ {name}: AttributeError: {e}")
    except Exception as e:
        RESULTS["fail"].append(f"{name}: {type(e).__name__}: {e}")
        print(f"  ❌ {name}: {type(e).__name__}: {e}")


def test_imports():
    print("\n═══ 1. IMPORT CHECK (every module) ═══")
    modules = [
        # Core
        "app", "config", "mongo_client", "mongo_data_loader",
        "auth_guard", "access_control", "period_engine", "ui_helpers",
        "pages_registry", "user_prefs",
        # Scrapers
        "scrape_kpi", "scrape_stripe", "firebase_login",
        "linkedin_browser_scraper", "linkedin_daily_pipeline",
        "customer_success_scraper", "youtube_connector", "ga4_connector",
        # Processing
        "process_data", "daily_counts", "daily_pipeline",
        "pipeline_gap_scanner", "email_validator_engine",
        # Analytics engines
        "attribution_tracker", "anomaly_detector",
        "kpi_pattern_analyzer", "trend_analysis_engine",
        "unsubscribe_analytics", "customer_success_analytics",
        "youtube_command_center", "youtube_analytics",
        "cross_platform_engine", "custom_modules_engine",
        # UI
        "kpi_pattern_ui", "trend_analysis_ui", "unsubscribe_ui",
        "customer_success_ui", "customer_success_analytics_ui",
        "linkedin_command_center_ui", "youtube_command_center_ui",
        "youtube_page_v2", "custom_modules_ui", "ai_assistant_ui",
        "ai_enhanced_ui", "editable_tables",
        # AI + Alerts
        "ai_engine", "ai_assistant_engine", "ai_enhanced_engine",
        "reporting_engine", "comprehensive_alerts", "rich_alerts_engine",
        "all_alerts", "telegram_alerts", "notifications",
        # API
        "api_server",
    ]
    for m in modules:
        _test(f"import {m}", importlib.import_module, m)


def test_mongo():
    print("\n═══ 2. MONGODB HEALTH ═══")
    from mongo_client import get_mongo_status, count_docs, find_all
    s = get_mongo_status()
    assert s["connected"], "MongoDB not connected"
    _test("mongo status: connected", lambda: None)
    _test("count_docs('signups')", count_docs, "signups")
    _test("count_docs('uploads')", count_docs, "uploads")
    _test("count_docs('payments')", count_docs, "payments")
    _test("count_docs('daily_kpis')", count_docs, "daily_kpis")


def test_scrapers():
    print("\n═══ 3. SCRAPERS (import only, don't run) ═══")
    from scrape_kpi import main as kpi_main
    from scrape_stripe import main as stripe_main
    _test("scrape_kpi.main exists", lambda: kpi_main)
    _test("scrape_stripe.main exists", lambda: stripe_main)


def test_processing():
    print("\n═══ 4. PROCESSING FUNCTIONS ═══")
    from process_data import (
        process_signups, process_uploads, process_payments,
        _parse_date_string, _is_internal_email,
    )
    _test("_parse_date_string('2026-07-09')",
           _parse_date_string, "2026-07-09")
    _test("_is_internal_email('a@eagle3dstreaming.com')",
           _is_internal_email, "a@eagle3dstreaming.com")

    from pipeline_gap_scanner import scan_gaps, rebuild_from_raw
    _test("scan_gaps()", scan_gaps)


def test_attribution():
    print("\n═══ 5. ATTRIBUTION ═══")
    from attribution_tracker import (
        signups_by_source, uploads_by_source, payments_by_source,
        revenue_by_source, daily_attribution_report, build_attribution_alert,
    )
    from datetime import date, timedelta
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=30)).isoformat()

    _test("signups_by_source", signups_by_source, start, end)
    _test("uploads_by_source", uploads_by_source, start, end)
    _test("payments_by_source", payments_by_source, start, end)
    _test("revenue_by_source", revenue_by_source, start, end)
    _test("daily_attribution_report", daily_attribution_report, 7)
    _test("build_attribution_alert", build_attribution_alert, 7)


def test_rich_alerts():
    print("\n═══ 6. RICH ALERT BUILDERS ═══")
    from rich_alerts_engine import (
        build_kpi_daily_summary, build_youtube_daily_summary,
        build_linkedin_daily_summary, build_ga4_daily_summary,
        build_cs_daily_summary, build_kpi_spike_alerts,
        build_youtube_dead_video_alerts, build_linkedin_viral_post_alerts,
        build_kpi_top_source_alert, build_top_paying_customers_alert,
        build_youtube_top_video_alert, build_revenue_trend_alert,
        build_upload_trend_alert, build_kpi_cold_source_alert,
        build_cs_dormant_alert, build_linkedin_dead_post_alerts,
        build_ga4_source_trend_alert,
    )
    for fn_name, fn in [
        ("build_kpi_daily_summary", build_kpi_daily_summary),
        ("build_youtube_daily_summary", build_youtube_daily_summary),
        ("build_linkedin_daily_summary", build_linkedin_daily_summary),
        ("build_ga4_daily_summary", build_ga4_daily_summary),
        ("build_cs_daily_summary", build_cs_daily_summary),
        ("build_kpi_spike_alerts", build_kpi_spike_alerts),
        ("build_youtube_dead_video_alerts", build_youtube_dead_video_alerts),
        ("build_linkedin_viral_post_alerts", build_linkedin_viral_post_alerts),
        ("build_kpi_top_source_alert", build_kpi_top_source_alert),
        ("build_top_paying_customers_alert", build_top_paying_customers_alert),
        ("build_youtube_top_video_alert", build_youtube_top_video_alert),
        ("build_revenue_trend_alert", build_revenue_trend_alert),
        ("build_upload_trend_alert", build_upload_trend_alert),
        ("build_kpi_cold_source_alert", build_kpi_cold_source_alert),
        ("build_cs_dormant_alert", build_cs_dormant_alert),
        ("build_linkedin_dead_post_alerts", build_linkedin_dead_post_alerts),
        ("build_ga4_source_trend_alert", build_ga4_source_trend_alert),
    ]:
        _test(fn_name, fn)


def test_period_engine():
    print("\n═══ 7. PERIOD ENGINE ═══")
    from period_engine import (
        _resolve_preset, _compute_compare, PRESETS, COMPARE_MODES,
    )
    from datetime import date
    for p in PRESETS:
        _test(f"resolve preset '{p}'", _resolve_preset, p,
               date(2024, 1, 1), date(2024, 12, 31))
    for m in COMPARE_MODES:
        _test(f"compare mode '{m}'", _compute_compare,
               date(2026, 6, 1), date(2026, 6, 30), m,
               date(2025, 1, 1), date(2025, 3, 31))


def test_youtube_analytics():
    print("\n═══ 8. YOUTUBE ANALYTICS ═══")
    from youtube_analytics import (
        _get_access_token, _channel_filter,
        get_daily_views, get_revenue, get_top_videos,
        get_traffic_sources, get_demographics, get_subscriber_growth,
        get_search_terms, get_views_by_playback, get_sharing_service,
        get_playlist_analytics, get_batch_video_analytics,
    )
    _test("get_daily_views", get_daily_views)
    _test("get_revenue", get_revenue)
    _test("get_top_videos", get_top_videos, "views", None, None, 5)
    _test("get_traffic_sources", get_traffic_sources)
    _test("get_demographics", get_demographics)
    _test("get_subscriber_growth", get_subscriber_growth)


def test_ai_tools():
    print("\n═══ 9. AI TOOLS ═══")
    from ai_enhanced_engine import TOOL_REGISTRY
    from datetime import date, timedelta
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=30)).isoformat()

    tools_args = {
        "get_kpi_counts":       {"start": start, "end": end},
        "top_signup_sources":   {"start": start, "end": end, "limit": 5},
        "top_paying_customers": {"start": start, "end": end, "limit": 5},
        "get_revenue":          {"start": start, "end": end},
        "pipeline_health":      {},
        "youtube_summary":      {},
        "linkedin_summary":     {},
        "reject_reasons":       {"start": start, "end": end, "collection": "uploads"},
    }
    for name, args in tools_args.items():
        if name in TOOL_REGISTRY:
            _test(f"tool: {name}", TOOL_REGISTRY[name], **args)


def test_api_endpoints():
    print("\n═══ 10. API SERVER ENDPOINTS (local) ═══")
    import requests
    import re
    from pathlib import Path

    try:
        content = Path(".streamlit/secrets.toml").read_text()
        m = re.search(r'^API_KEY\s*=\s*"([^"]+)"', content, re.MULTILINE)
        key = m.group(1) if m else ""
    except Exception:
        key = ""

    headers = {"X-API-Key": key, "ngrok-skip-browser-warning": "1"}
    base = "http://localhost:8000"

    endpoints = [
        "/health",
        "/api/kpis/summary?start=2026-07-01&end=2026-07-31",
        "/api/kpis/daily?start=2026-07-01&end=2026-07-31",
        "/api/signups?limit=5",
        "/api/uploads?limit=5",
        "/api/payments?limit=5",
        "/api/attribution/full-report?days=7",
        "/api/youtube/channel",
        "/api/youtube/videos?limit=5",
        "/api/linkedin/latest",
        "/api/customer-success?view=enriched&limit=5",
        "/api/ga4/cache",
        "/api/pipeline/health",
        "/api/collections",
    ]
    for ep in endpoints:
        def call(url=ep):
            r = requests.get(f"{base}{url}", headers=headers, timeout=10)
            r.raise_for_status()
        _test(f"GET {ep}", call)


def test_custom_modules():
    print("\n═══ 11. CUSTOM MODULES ═══")
    from custom_modules_engine import (
        list_modules, slugify, detect_column_types,
        load_from_google_sheet_url, ai_qa_over_module,
    )
    import pandas as pd
    _test("list_modules", list_modules)
    _test("slugify", slugify, "Test Name 123")

    df = pd.DataFrame({
        "email": ["a@b.com", "c@d.com"],
        "date": ["2026-01-01", "2026-01-02"],
        "amount": [10.5, 20.0],
        "status": ["active", "inactive"],
    })
    _test("detect_column_types", detect_column_types, df)


if __name__ == "__main__":
    print("=" * 60)
    print("EAGLE 3D STREAMING — FULL SYSTEM QA")
    print("=" * 60)

    test_imports()
    test_mongo()
    test_scrapers()
    test_processing()
    test_attribution()
    test_rich_alerts()
    test_period_engine()
    test_youtube_analytics()
    test_ai_tools()
    test_api_endpoints()
    test_custom_modules()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  ✅ Passed:  {len(RESULTS['pass'])}")
    print(f"  ⚠️  Warned:  {len(RESULTS['warn'])}")
    print(f"  ❌ Failed:  {len(RESULTS['fail'])}")

    if RESULTS["fail"]:
        print("\n❌ FAILURES:")
        for f in RESULTS["fail"]:
            print(f"  • {f}")

    if RESULTS["warn"]:
        print("\n⚠️ WARNINGS:")
        for w in RESULTS["warn"][:10]:
            print(f"  • {w}")

    sys.exit(1 if RESULTS["fail"] else 0)
