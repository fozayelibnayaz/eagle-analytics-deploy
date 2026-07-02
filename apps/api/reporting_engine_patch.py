#!/usr/bin/env python3
# REPORTING ENGINE PATCH
from pathlib import Path
from datetime import datetime

PATCH_MARKER = "# PATCHED_BY_REPORTING_ENGINE_PATCH"

PATCH_CODE = (
"\n# PATCHED_BY_REPORTING_ENGINE_PATCH\n"
"def build_kpi_stats_validated():\n"
"    from sheets_writer import read_tab_data\n"
"    from override_engine import load_overrides, apply_overrides_to_rows\n"
"    from common_period_engine import compute_alltime_metrics, get_common_period\n"
"    from validation_engine import validate_kpi_metrics\n"
"    today_str     = datetime.now().strftime('%Y-%m-%d')\n"
"    cur_month_str = datetime.now().strftime('%Y-%m')\n"
"    free_rows   = apply_overrides_to_rows(read_tab_data('Verified_FREE'),         'FREE')\n"
"    upload_rows = apply_overrides_to_rows(read_tab_data('Verified_FIRST_UPLOAD'), 'FIRST_UPLOAD')\n"
"    stripe_rows = apply_overrides_to_rows(read_tab_data('Verified_STRIPE'),       'STRIPE')\n"
"    s_today = u_today = p_today = 0\n"
"    s_month = u_month = p_month = 0\n"
"    for r in free_rows:\n"
"        if str(r.get('final_status','')).upper() == 'ACCEPTED':\n"
"            for f in ('row_date_used','Account Created On','__scraped_date__'):\n"
"                d = _parse_report_date(str(r.get(f,'')))\n"
"                if d:\n"
"                    if d == today_str:         s_today += 1\n"
"                    if d[:7] == cur_month_str: s_month += 1\n"
"                    break\n"
"    for r in upload_rows:\n"
"        if str(r.get('final_status','')).upper() == 'ACCEPTED':\n"
"            for f in ('row_date_used','Upload Date','__scraped_date__'):\n"
"                d = _parse_report_date(str(r.get(f,'')))\n"
"                if d:\n"
"                    if d == today_str:         u_today += 1\n"
"                    if d[:7] == cur_month_str: u_month += 1\n"
"                    break\n"
"    for r in stripe_rows:\n"
"        if str(r.get('final_status','')).upper() == 'ACCEPTED':\n"
"            for f in ('First payment','row_date_used','Created','__scraped_date__'):\n"
"                d = _parse_report_date(str(r.get(f,'')))\n"
"                if d:\n"
"                    if d == today_str:         p_today += 1\n"
"                    if d[:7] == cur_month_str: p_month += 1\n"
"                    break\n"
"    alltime = compute_alltime_metrics(use_common_period=True)\n"
"    common_start, common_end = get_common_period()\n"
"    s_all  = alltime.get('signups', 0)\n"
"    u_all  = alltime.get('uploads', 0)\n"
"    p_all  = alltime.get('paid',    0)\n"
"    s_full = alltime.get('full_db_signups', 0)\n"
"    u_full = alltime.get('full_db_uploads', 0)\n"
"    p_full = alltime.get('full_db_paid',    0)\n"
"    validation = validate_kpi_metrics(signups=s_all, uploads=u_all, paid=p_all, common_period_only=True)\n"
"    overrides = load_overrides()\n"
"    return {\n"
"        'signups_today':          s_today,\n"
"        'uploads_today':          u_today,\n"
"        'paid_today':             p_today,\n"
"        'signups_month':          s_month,\n"
"        'uploads_month':          u_month,\n"
"        'paid_month':             p_month,\n"
"        'signups_all':            s_all,\n"
"        'uploads_all':            u_all,\n"
"        'paid_all':               p_all,\n"
"        'signups_full_db':        s_full,\n"
"        'uploads_full_db':        u_full,\n"
"        'paid_full_db':           p_full,\n"
"        'signups_all_override':   s_all,\n"
"        'uploads_all_override':   u_all,\n"
"        'paid_all_override':      p_all,\n"
"        'signups_month_override': s_month,\n"
"        'uploads_month_override': u_month,\n"
"        'paid_month_override':    p_month,\n"
"        'today_str':              today_str,\n"
"        'month_str':              cur_month_str,\n"
"        'alltime_period':         alltime.get('period_label','Common Period'),\n"
"        'alltime_start':          common_start or '',\n"
"        'alltime_end':            common_end   or '',\n"
"        'total_overrides':        len(overrides),\n"
"        'validation_passed':      validation.is_valid,\n"
"        'validation_warnings':    len(validation.warnings),\n"
"        'validation_summary':     validation.get_summary(),\n"
"        'validation_banner':      validation.get_display_banner(),\n"
"    }\n"
)

def apply_patch():
    p = Path("reporting_engine.py")
    if not p.exists():
        print("reporting_engine.py not found")
        return
    content = p.read_text()
    if PATCH_MARKER in content:
        print("Already patched")
        return
    p.write_text(content + "\n\n" + PATCH_CODE)
    print("reporting_engine.py patched")

if __name__ == "__main__":
    apply_patch()
