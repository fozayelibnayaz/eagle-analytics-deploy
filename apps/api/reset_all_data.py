"""
reset_all_data.py
Clears ALL Google Sheet tabs and local CSVs for a completely fresh start.
"""
import os, sys, json, shutil, time
from pathlib import Path

DATA_DIR = Path("data_output")
RESET_TABS = [
    "Raw_FREE", "Raw_FIRST_UPLOAD", "Raw_STRIPE", "Raw_PAID", "Raw_500_MIN",
    "Verified_FREE", "Verified_FIRST_UPLOAD", "Verified_STRIPE", "Verified_PAID", "Verified_500_MIN",
    "Daily_Counts", "Monthly_Counts",
    "LinkedIn", "LinkedIn_Posts",
    "YouTube", "GA4", "Cross_Platform",
    "Daily_Report", "Phase2_Summary",
]


def reset():
    print("=" * 60)
    print("COMPLETE DATA RESET — Clearing everything")
    print("=" * 60)

    # 1. Clear local CSVs
    if DATA_DIR.exists():
        for f in DATA_DIR.iterdir():
            if f.is_file():
                f.unlink()
                print(f"  🗑️ Deleted local: {f.name}")
        print(f"  ✅ Local data_output/ cleared")

    # 2. Clear Google Sheets tabs
    try:
        from sheets_writer import _get_client, _retry_on_quota
        client, ss = _get_client()
        worksheets = ss.worksheets()
        existing = {ws.title: ws for ws in worksheets}
        cleared = 0
        for tab in RESET_TABS:
            if tab in existing:
                ws = existing[tab]
                rows = _retry_on_quota(ws.get_all_values)
                if len(rows) > 0:
                    _retry_on_quota(ws.batch_clear, [f"A1:Z{len(rows)+5}"])
                    print(f"  🗑️ Cleared sheet tab: {tab} ({len(rows)} rows)")
                    cleared += 1
                time.sleep(0.3)
        print(f"  ✅ {cleared} sheet tabs cleared")

        # Reset headers for core tabs
        headers_map = {
            "Raw_FREE": ["Email", "Name", "Signup_Date"],
            "Raw_FIRST_UPLOAD": ["Email", "Name", "First_Upload_Date"],
            "Raw_STRIPE": ["Email", "Name", "Payment_Date", "Amount", "Status"],
            "Verified_FREE": ["Email", "Name", "Signup_Date", "Status"],
            "Verified_FIRST_UPLOAD": ["Email", "Name", "First_Upload_Date", "Status"],
            "Verified_STRIPE": ["Email", "Name", "Payment_Date", "Amount", "Status"],
            "LinkedIn": ["Date", "Impressions", "Reactions", "Comments", "Reposts", "Followers", "Visitors"],
            "LinkedIn_Posts": ["Date", "Post_URL", "Impressions", "Clicks", "Likes", "Comments", "Shares"],
            "YouTube": ["Date", "Views", "Subscribers_Gained", "Watch_Hours"],
            "GA4": ["Date", "Sessions", "Users", "Pageviews"],
            "Cross_Platform": ["Date", "Source", "Metric", "Value"],
            "Daily_Counts": ["Date", "Signups", "First_Uploads", "Paid"],
            "Monthly_Counts": ["Month", "Signups", "First_Uploads", "Paid"],
        }
        for tab, headers in headers_map.items():
            if tab in existing:
                ws = existing[tab]
                _retry_on_quota(ws.append_row, headers)
                print(f"  📝 Wrote headers to: {tab}")
                time.sleep(0.3)

        print(f"\n  ✅ All sheets reset complete!")
    except Exception as e:
        print(f"\n  ⚠️ Sheets reset error: {e}")
        print("  (Continuing with local reset only)")

    # 3. Clear any cached state files
    cache_files = ["daily_counts.json", "daily_counts_prev.json", 
                   "run_summaries.json", "linkedin_state.json",
                   "stripe_state.json", "kpi_state.json"]
    for cf in cache_files:
        p = DATA_DIR / cf
        if p.exists():
            p.unlink()
            print(f"  🗑️ Deleted cache: {cf}")

    print("\n" + "=" * 60)
    print("RESET COMPLETE — All data cleared for fresh start!")
    print("=" * 60)


if __name__ == "__main__":
    confirm = os.environ.get("RESET_CONFIRM", "")
    if confirm != "YES":
        print("⚠️  This will DELETE ALL data in Google Sheets and locally!")
        print("   Set RESET_CONFIRM=YES to proceed.")
        sys.exit(1)
    reset()
