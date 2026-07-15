from pathlib import Path
from datetime import datetime
import re

BACKUP_DIR = Path("backups")
BACKUP_DIR.mkdir(exist_ok=True)

def backup(path: Path):
    b = BACKUP_DIR / f"{path.name}.final_ui_fix.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
    b.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
    print(f"BACKUP: {path} -> {b}")

def patch_app_py():
    path = Path("app.py")
    if not path.exists():
        print("SKIP: app.py missing")
        return

    text = path.read_text(encoding="utf-8", errors="ignore")
    original = text
    backup(path)

    # 1) Ensure the dashboard resolves KPIs right before the metrics row
    pattern_cols = re.compile(r'(^[ \t]*c1,\s*c2,\s*c3,\s*c4\s*=\s*st\.columns\(4\)\s*$)', re.M)
    m = pattern_cols.search(text)
    if m:
        indent = re.match(r'^([ \t]*)', m.group(1)).group(1)
        inject = (
f"""{indent}try:
{indent}    from kpi_totals_resolver import resolve_period_kpis
{indent}    signups, uploads, payments, recurring_customers, stopped_recurring_customers = resolve_period_kpis(period.start_iso(), period.end_iso())
{indent}except Exception as _e:
{indent}    st.warning(f"KPI resolver unavailable: {{_e}}")
{indent}    recurring_customers = 0
{indent}    stopped_recurring_customers = 0

{indent}try:
{indent}    from customer_kpi_breakdown_ui import render_customer_kpi_breakdown
{indent}    render_customer_kpi_breakdown()
{indent}except Exception as _e:
{indent}    st.warning(f"Customer KPI breakdown unavailable: {{_e}}")

{m.group(1)}"""
        )
        text = text[:m.start()] + inject + text[m.end():]
        print("✅ app.py: injected KPI resolver + customer breakdown before dashboard metrics row")
    else:
        print("WARN: app.py metric columns anchor not found")

    # 2) Rename visible paid card label if present
    text = text.replace('st.metric("Paying Customers"', 'st.metric("New Paying Customers"')
    text = text.replace('st.metric("💳 Paying Customers"', 'st.metric("💳 New Paying Customers"')
    text = text.replace('st.metric("💳 Paid"', 'st.metric("💳 New Paying Customers"')

    if text != original:
        path.write_text(text, encoding="utf-8")
        print("✅ app.py written")
    else:
        print("ℹ️ app.py unchanged")

def patch_pages_registry():
    path = Path("pages_registry.py")
    if not path.exists():
        print("SKIP: pages_registry.py missing")
        return

    text = path.read_text(encoding="utf-8", errors="ignore")
    original = text
    backup(path)

    # Replace current period KPI assignment
    text, n1 = re.subn(
        r'(^[ \t]*)sign,\s*up,\s*pay\s*=\s*sum_kpis\(([^)]*)\)\s*$',
        r'\1from kpi_totals_resolver import resolve_period_kpis\n\1sign, up, pay, recurring, stopped = resolve_period_kpis(\2)',
        text,
        count=1,
        flags=re.M,
    )

    # Replace previous period KPI assignment
    text, n2 = re.subn(
        r'(^[ \t]*)prev_s,\s*prev_u,\s*prev_p\s*=\s*sum_kpis\(([^)]*)\)\s*$',
        r'\1prev_s, prev_u, prev_p, prev_recurring, prev_stopped = resolve_period_kpis(\2)',
        text,
        count=1,
        flags=re.M,
    )

    if n1:
        print("✅ pages_registry.py: replaced current KPI sum with shared resolver")
    else:
        print("WARN: pages_registry.py current KPI assignment not patched")

    if n2:
        print("✅ pages_registry.py: replaced previous KPI sum with shared resolver")
    else:
        print("WARN: pages_registry.py previous KPI assignment not patched")

    # Inject customer breakdown UI after current period KPI assignment
    inject_anchor = "sign, up, pay, recurring, stopped = resolve_period_kpis("
    if inject_anchor in text and "render_customer_kpi_breakdown()" not in text:
        idx = text.find(inject_anchor)
        line_end = text.find("\n", idx)
        indent = re.match(r'^([ \t]*)', text[idx:]).group(1)
        block = (
f"""
{indent}try:
{indent}    from customer_kpi_breakdown_ui import render_customer_kpi_breakdown
{indent}    render_customer_kpi_breakdown()
{indent}except Exception as _e:
{indent}    st.warning(f"Customer KPI breakdown unavailable: {{_e}}")
"""
        )
        text = text[:line_end+1] + block + text[line_end+1:]
        print("✅ pages_registry.py: injected customer KPI breakdown")
    elif "render_customer_kpi_breakdown()" in text:
        print("ℹ️ pages_registry.py already includes customer KPI breakdown")
    else:
        print("WARN: pages_registry.py injection anchor not found")

    # Rename label text
    text = text.replace("Paying Customers", "New Paying Customers")
    text = text.replace("paying customers", "new paying customers")

    if text != original:
        path.write_text(text, encoding="utf-8")
        print("✅ pages_registry.py written")
    else:
        print("ℹ️ pages_registry.py unchanged")

patch_app_py()
patch_pages_registry()
