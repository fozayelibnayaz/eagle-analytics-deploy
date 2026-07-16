from pathlib import Path
from datetime import datetime
import re
import os

ROOT = Path.cwd()
BACKUPS = ROOT / "backups"
BACKUPS.mkdir(exist_ok=True)

def backup_file(path: Path):
    if path.exists():
        b = BACKUPS / f"{path.name}.must_fix_all.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
        b.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        print(f"BACKUP: {path} -> {b}")

def patch_app_py():
    path = ROOT / "app.py"
    if not path.exists():
        print("SKIP: app.py missing")
        return
    backup_file(path)
    text = path.read_text(encoding="utf-8", errors="ignore")

    # Fix route naming
    text = text.replace("def _route(page: str, user_email: str) -> None:", "def route(page: str, user_email: str) -> None:")
    text = text.replace("_route(current_page, user_email)", "route(current_page, user_email)")

    # Repair broken route line if corruption exists
    text = text.replace("render_dashboard(user_email)    elif page == \"settings\":", 'render_dashboard(user_email)\n    elif page == "settings":')

    # Remove any customer_kpi_breakdown injected blocks
    text = re.sub(
        r'\n[ \t]*try:\n[ \t]*from customer_kpi_breakdown_ui import render_customer_kpi_breakdown\n[ \t]*render_customer_kpi_breakdown\(\)\n[ \t]*except Exception as _e:\n[ \t]*st\.warning\(f"Customer KPI breakdown unavailable: \{_e\}"\)\n',
        '\n',
        text
    )

    # Remove recurring/stopped cards block if any
    text = re.sub(
        r'\n[ \t]*st\.markdown\("<div style=\'margin-top:18px;\'></div>", unsafe_allow_html=True\)\n'
        r'[ \t]*st\.markdown\([\s\S]*?CUSTOMER PAYMENT BREAKDOWN[\s\S]*?unsafe_allow_html=True,\n[ \t]*\)\n'
        r'[ \t]*rc1,\s*rc2\s*=\s*st\.columns\(2\)\n'
        r'[ \t]*rc1\.metric\("🔁 Recurring Customers".*?\n'
        r'[ \t]*rc2\.metric\("🛑 Stopped Recurring".*?\n',
        '\n',
        text,
        flags=re.M
    )

    # Remove recurring vars from defaults if they exist
    text = text.replace(
        "signups = uploads = payments = recurring_customers = stopped_recurring_customers = 0",
        "signups = uploads = payments = 0"
    )
    text = text.replace(
        "prev_signups = prev_uploads = prev_payments = prev_recurring_customers = prev_stopped_recurring_customers = 0",
        "prev_signups = prev_uploads = prev_payments = 0"
    )

    # Make app.py use current daily_kpis fields
    text = text.replace("signups_accepted", "signups")
    text = text.replace("uploads_accepted", "first_uploads")
    text = text.replace("paid_accepted", "new_paid_customers")

    # Normalize label
    text = text.replace("New New Paying Customers", "New Paying Customers")
    text = text.replace("💳 Paid", "💳 New Paying Customers")
    text = text.replace("Paying Customers", "New Paying Customers")

    path.write_text(text, encoding="utf-8")
    print("✅ patched app.py")

def patch_pages_registry():
    path = ROOT / "pages_registry.py"
    if not path.exists():
        print("SKIP: pages_registry.py missing")
        return
    backup_file(path)
    text = path.read_text(encoding="utf-8", errors="ignore")

    # Remove recurring cards block
    text = re.sub(
        r'\n[ \t]*st\.markdown\("<div style=\'margin-top:16px;\'></div>", unsafe_allow_html=True\)\n'
        r'[ \t]*c4,\s*c5\s*=\s*st\.columns\(2\)\n'
        r'[ \t]*c4\.metric\("🔁 Recurring Customers".*?\n'
        r'[ \t]*c5\.metric\("🛑 Stopped Recurring".*?\n',
        '\n',
        text,
        flags=re.M
    )

    # Remove 5-value assignments if any
    text = text.replace(
        "sign, up, pay, recurring, stopped = sum_kpis(period.start_iso(), period.end_iso())",
        "sign, up, pay = sum_kpis(period.start_iso(), period.end_iso())"
    )
    text = text.replace(
        "prev_s, prev_u, prev_p, prev_recurring, prev_stopped = sum_kpis(period.compare_start_iso(),",
        "prev_s, prev_u, prev_p = sum_kpis(period.compare_start_iso(),"
    )

    # Use current daily_kpis fields everywhere
    text = text.replace("signups_accepted", "signups")
    text = text.replace("uploads_accepted", "first_uploads")
    text = text.replace("paid_accepted", "new_paid_customers")

    # Normalize label
    text = text.replace("New New Paying Customers", "New Paying Customers")
    text = text.replace('c3.metric("💳 PAID",', 'c3.metric("💳 New Paying Customers",')
    text = text.replace('c3.metric("💳 Paid",', 'c3.metric("💳 New Paying Customers",')

    path.write_text(text, encoding="utf-8")
    print("✅ patched pages_registry.py")

def disable_legacy_daily_pipeline():
    wf = ROOT / ".github" / "workflows" / "daily_pipeline.yml"
    if wf.exists():
        backup_file(wf)
        disabled = ROOT / ".github" / "workflows" / "daily_pipeline.disabled.yml"
        wf.rename(disabled)
        print(f"✅ disabled legacy workflow: {wf} -> {disabled}")
    else:
        print("ℹ️ no legacy daily_pipeline.yml found")

patch_app_py()
patch_pages_registry()
disable_legacy_daily_pipeline()

print("✅ must-fix-all code patch complete")
