from pathlib import Path
from datetime import datetime

p = Path("scripts/fix_daily_kpis_safe.py")
if not p.exists():
    raise SystemExit("❌ scripts/fix_daily_kpis_safe.py not found")

text = p.read_text(encoding="utf-8", errors="ignore")
backup = Path("backups") / f"fix_daily_kpis_safe.py.cutover.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
backup.write_text(text, encoding="utf-8")

if "from source_cutover_resolver import" not in text:
    text = text.replace(
        'from kpi_totals_resolver import _all_payment_events',
        'from kpi_totals_resolver import _all_payment_events\nfrom source_cutover_resolver import get_cutover_date, is_countable_signup, is_countable_upload'
    )

# replace signup loop
text = text.replace(
'''    for s in find_all("signups", {}):
        if not _is_accepted(s):
            continue
        d = _pick_date(s, ["signup_date", "account_created_on", "created_date", "date"])
        e = _norm(s.get("email") or s.get("email_normalized"))
        if d and e:
            ensure_day(d)["_s"].add(e)
''',
'''    for s in find_all("signups", {}):
        if not _is_accepted(s):
            continue
        d = _pick_date(s, ["signup_date", "account_created_on", "created_date", "date"])
        e = _norm(s.get("email") or s.get("email_normalized"))
        if d and e and is_countable_signup(s, d):
            ensure_day(d)["_s"].add(e)
'''
)

# replace upload loop
text = text.replace(
'''    for u in find_all("uploads", {}):
        if not _is_accepted(u):
            continue
        d = _pick_date(u, ["upload_date", "first_upload_date", "created_date", "date"])
        e = _norm(u.get("email") or u.get("email_normalized"))
        if d and e:
            ensure_day(d)["_u"].add(e)
''',
'''    for u in find_all("uploads", {}):
        if not _is_accepted(u):
            continue
        d = _pick_date(u, ["upload_date", "first_upload_date", "created_date", "date"])
        e = _norm(u.get("email") or u.get("email_normalized"))
        if d and e and is_countable_upload(u, d):
            ensure_day(d)["_u"].add(e)
'''
)

# add cutover print
text = text.replace(
'    base = load_base_daily_kpis()',
'    cutover = get_cutover_date()\n    print(f"Cutover date = {cutover}")\n    base = load_base_daily_kpis()'
)

p.write_text(text, encoding="utf-8")
print(f"✅ patched {p} for automatic source cutover (backup -> {backup})")
