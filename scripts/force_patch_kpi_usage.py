from pathlib import Path
from datetime import datetime
import re

FILES = ["app.py", "pages_registry.py"]

def backup(path: Path):
    b = Path("backups") / f"{path.name}.force_kpi_fix.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
    b.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
    return b

def patch_file(path_str: str):
    path = Path(path_str)
    if not path.exists():
        print(f"SKIP: {path} missing")
        return False

    text = path.read_text(encoding="utf-8", errors="ignore")
    original = text
    b = backup(path)

    # Ensure import exists somewhere
    if "from kpi_totals_resolver import resolve_period_kpis" not in text:
        # add near top after existing imports
        m = re.search(r'^(import .*|from .* import .*)$', text, re.M)
        if m:
            insert_at = m.end()
            text = text[:insert_at] + "\nfrom kpi_totals_resolver import resolve_period_kpis" + text[insert_at:]
        else:
            text = "from kpi_totals_resolver import resolve_period_kpis\n" + text

    # Replace current period 3-value assignment patterns
    replacements = [
        (
            r'(^[ \t]*)signups,\s*uploads,\s*payments\s*=\s*sum_kpis\(([^)]*)\)\s*$',
            r'\1signups, uploads, payments, recurring_customers, stopped_recurring_customers = resolve_period_kpis(\2)'
        ),
        (
            r'(^[ \t]*)sign,\s*up,\s*pay\s*=\s*sum_kpis\(([^)]*)\)\s*$',
            r'\1sign, up, pay, recurring, stopped = resolve_period_kpis(\2)'
        ),
        (
            r'(^[ \t]*)signups,\s*uploads,\s*payments\s*=\s*_sum_kpis\(([^)]*)\)\s*$',
            r'\1signups, uploads, payments, recurring_customers, stopped_recurring_customers = resolve_period_kpis(\2)'
        ),
        (
            r'(^[ \t]*)sign,\s*up,\s*pay\s*=\s*_sum_kpis\(([^)]*)\)\s*$',
            r'\1sign, up, pay, recurring, stopped = resolve_period_kpis(\2)'
        ),
    ]

    # Replace previous period 3-value assignment patterns
    replacements_prev = [
        (
            r'(^[ \t]*)prev_signups,\s*prev_uploads,\s*prev_payments\s*=\s*sum_kpis\(([^)]*)\)\s*$',
            r'\1prev_signups, prev_uploads, prev_payments, prev_recurring_customers, prev_stopped_recurring_customers = resolve_period_kpis(\2)'
        ),
        (
            r'(^[ \t]*)prev_s,\s*prev_u,\s*prev_p\s*=\s*sum_kpis\(([^)]*)\)\s*$',
            r'\1prev_s, prev_u, prev_p, prev_recurring, prev_stopped = resolve_period_kpis(\2)'
        ),
        (
            r'(^[ \t]*)prev_signups,\s*prev_uploads,\s*prev_payments\s*=\s*_sum_kpis\(([^)]*)\)\s*$',
            r'\1prev_signups, prev_uploads, prev_payments, prev_recurring_customers, prev_stopped_recurring_customers = resolve_period_kpis(\2)'
        ),
        (
            r'(^[ \t]*)prev_s,\s*prev_u,\s*prev_p\s*=\s*_sum_kpis\(([^)]*)\)\s*$',
            r'\1prev_s, prev_u, prev_p, prev_recurring, prev_stopped = resolve_period_kpis(\2)'
        ),
    ]

    hits = 0
    for pat, repl in replacements:
        text, n = re.subn(pat, repl, text, count=1, flags=re.M)
        hits += n

    for pat, repl in replacements_prev:
        text, n = re.subn(pat, repl, text, count=1, flags=re.M)
        hits += n

    # Rename visible paid labels
    text = text.replace("💳 PAID", "💳 NEW PAYING CUSTOMERS")
    text = text.replace("💳 Paid", "💳 New Paying Customers")
    text = text.replace("Paying Customers", "New Paying Customers")

    if text != original:
        path.write_text(text, encoding="utf-8")
        print(f"✅ patched {path} (backup -> {b}) | replacements={hits}")
        return True
    else:
        print(f"ℹ️ no text changes made in {path}")
        return False

changed = False
for f in FILES:
    changed = patch_file(f) or changed

if not changed:
    raise SystemExit("❌ No KPI usage patch was applied. Need exact code inspection.")
