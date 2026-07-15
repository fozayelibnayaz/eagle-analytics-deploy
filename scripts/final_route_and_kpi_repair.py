from pathlib import Path
from datetime import datetime
import re

def backup(path: Path):
    b = Path("backups") / f"{path.name}.final_route_and_kpi_repair.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
    b.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
    print(f"BACKUP: {path} -> {b}")

# -------------------------------------------------
# app.py
# -------------------------------------------------
app = Path("app.py")
if not app.exists():
    raise SystemExit("❌ app.py not found")

backup(app)
app_text = app.read_text(encoding="utf-8", errors="ignore")

# 1) Fix main call: _route(...) -> route(...)
app_text = app_text.replace("_route(current_page, user_email)", "route(current_page, user_email)")

# 2) If the function is named _route, rename to route
app_text = app_text.replace("def _route(page: str, user_email: str) -> None:", "def route(page: str, user_email: str) -> None:")

# 3) Make sure app.py dashboard sum_kpis uses current fields
app_text = app_text.replace(
'''                def sum_kpis(start_iso, end_iso):
                    rows = find_all("daily_kpis",
                                    filters={"date": {"$gte": start_iso, "$lte": end_iso}},
                                    sort=[("date", 1)])
                    s_ = sum(int(r.get("signups_accepted", 0) or 0) for r in rows)
                    u_ = sum(int(r.get("uploads_accepted", 0) or 0) for r in rows)
                    p_ = sum(int(r.get("paid_accepted",    0) or 0) for r in rows)
                    return s_, u_, p_
''',
'''                def sum_kpis(start_iso, end_iso):
                    rows = find_all("daily_kpis",
                                    filters={"date": {"$gte": start_iso[:10], "$lte": end_iso[:10]}},
                                    sort=[("date", 1)])
                    s_ = sum(int(r.get("signups", 0) or 0) for r in rows)
                    u_ = sum(int(r.get("first_uploads", r.get("uploads", 0)) or 0) for r in rows)
                    p_ = sum(int(r.get("new_paid_customers", r.get("paid_customers", 0)) or 0) for r in rows)
                    return s_, u_, p_
'''
)

# 4) Normalize paid labels
app_text = app_text.replace("New New Paying Customers", "New Paying Customers")
app_text = app_text.replace("💳 Paid", "💳 New Paying Customers")
app_text = app_text.replace("Paying Customers", "New Paying Customers")

# 5) Remove recurring/stopped UI lines if they slipped into app.py
app_text = re.sub(
    r'\n[ \t]*st\.markdown\("<div style=\'margin-top:18px;\'></div>", unsafe_allow_html=True\)\n'
    r'[ \t]*st\.markdown\([\s\S]*?CUSTOMER PAYMENT BREAKDOWN[\s\S]*?unsafe_allow_html=True,\n[ \t]*\)\n'
    r'[ \t]*rc1,\s*rc2\s*=\s*st\.columns\(2\)\n'
    r'[ \t]*rc1\.metric\("🔁 Recurring Customers".*?\n'
    r'[ \t]*rc2\.metric\("🛑 Stopped Recurring".*?\n',
    '\n',
    app_text,
    flags=re.M
)

app.write_text(app_text, encoding="utf-8")
print("✅ app.py repaired")

# -------------------------------------------------
# pages_registry.py
# -------------------------------------------------
pr = Path("pages_registry.py")
if not pr.exists():
    raise SystemExit("❌ pages_registry.py not found")

backup(pr)
pr_text = pr.read_text(encoding="utf-8", errors="ignore")

# 1) Remove recurring/stopped cards to keep KPI page stable
pr_text = pr_text.replace(
'''
    st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)
    c4, c5 = st.columns(2)
    c4.metric("🔁 Recurring Customers", f"{recurring:,}")
    c5.metric("🛑 Stopped Recurring", f"{stopped:,}")
''',
''
)

# 2) Replace sum_kpis block with current fields
pr_text = pr_text.replace(
'''    def sum_kpis(s_iso, e_iso):
        rows = find_all("daily_kpis",
                        filters={"date": {"$gte": s_iso, "$lte": e_iso}})
        return (
            sum(int(r.get("signups_accepted", 0) or 0) for r in rows),
            sum(int(r.get("uploads_accepted", 0) or 0) for r in rows),
            sum(int(r.get("paid_accepted",    0) or 0) for r in rows),
        )
''',
'''    def sum_kpis(s_iso, e_iso):
        rows = find_all("daily_kpis",
                        filters={"date": {"$gte": s_iso[:10], "$lte": e_iso[:10]}})
        return (
            sum(int(r.get("signups", 0) or 0) for r in rows),
            sum(int(r.get("first_uploads", r.get("uploads", 0)) or 0) for r in rows),
            sum(int(r.get("new_paid_customers", r.get("paid_customers", 0)) or 0) for r in rows),
        )
'''
)

# 3) Force simple 3-value assignments
pr_text = pr_text.replace(
    "sign, up, pay, recurring, stopped = sum_kpis(period.start_iso(), period.end_iso())",
    "sign, up, pay = sum_kpis(period.start_iso(), period.end_iso())"
)
pr_text = pr_text.replace(
    "prev_s, prev_u, prev_p, prev_recurring, prev_stopped = sum_kpis(period.compare_start_iso(),",
    "prev_s, prev_u, prev_p = sum_kpis(period.compare_start_iso(),"
)

# 4) Labels
pr_text = pr_text.replace("New New Paying Customers", "New Paying Customers")
pr_text = pr_text.replace('c3.metric("💳 PAID",', 'c3.metric("💳 New Paying Customers",')
pr_text = pr_text.replace('c3.metric("💳 Paid",', 'c3.metric("💳 New Paying Customers",')

# 5) Chart fields
pr_text = pr_text.replace(
    'for c in ["signups_accepted", "uploads_accepted", "paid_accepted"]:',
    'for c in ["signups", "first_uploads", "new_paid_customers"]:'
)
pr_text = pr_text.replace(
    '("signups_accepted", "Sign-ups", "#9EFF2F", "rgba(158,255,47,0.10)")',
    '("signups", "Sign-ups", "#9EFF2F", "rgba(158,255,47,0.10)")'
)
pr_text = pr_text.replace(
    '("uploads_accepted", "Uploads",  "#5EF46A", "rgba(94,244,106,0.08)")',
    '("first_uploads", "Uploads",  "#5EF46A", "rgba(94,244,106,0.08)")'
)
pr_text = pr_text.replace(
    '("paid_accepted",    "Paid",     "#4ADE80", "rgba(74,222,128,0.06)")',
    '("new_paid_customers",    "New Paying Customers",     "#4ADE80", "rgba(74,222,128,0.06)")'
)

pr.write_text(pr_text, encoding="utf-8")
print("✅ pages_registry.py repaired")

print("✅ final route + KPI repair complete")
