from pathlib import Path
from datetime import datetime
import re

def backup(path: Path):
    b = Path("backups") / f"{path.name}.must_fix_kpi_zero_bug.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
    b.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
    print(f"BACKUP: {path} -> {b}")

# -------------------------------------------------------------------
# app.py
# -------------------------------------------------------------------
app = Path("app.py")
if app.exists():
    backup(app)
    text = app.read_text(encoding="utf-8", errors="ignore")

    # 1) Ensure defaults include recurring/stopped
    text = text.replace(
        "signups = uploads = payments = 0",
        "signups = uploads = payments = recurring_customers = stopped_recurring_customers = 0"
    )
    text = text.replace(
        "prev_signups = prev_uploads = prev_payments = 0",
        "prev_signups = prev_uploads = prev_payments = prev_recurring_customers = prev_stopped_recurring_customers = 0"
    )

    # 2) Replace legacy sum_kpis block
    pattern = re.compile(
        r'''def\s+sum_kpis\(start_iso,\s*end_iso\):\s*
                    rows\s*=\s*find_all\("daily_kpis",\s*
                                    filters=\{"date":\s*\{"\$gte":\s*start_iso,\s*"\$lte":\s*end_iso\}\},\s*
                                    sort=\[\("date",\s*1\)\]\)\s*
                    s_\s*=\s*sum\(int\(r\.get\("signups_accepted",\s*0\)\s*or\s*0\)\s*for\s*r\s*in\s*rows\)\s*
                    u_\s*=\s*sum\(int\(r\.get\("uploads_accepted",\s*0\)\s*or\s*0\)\s*for\s*r\s*in\s*rows\)\s*
                    p_\s*=\s*sum\(int\(r\.get\("paid_accepted",\s*0\)\s*or\s*0\)\s*for\s*r\s*in\s*rows\)\s*
                    return\s+s_,\s*u_,\s*p_''',
        re.X
    )

    replacement = '''from kpi_totals_resolver import resolve_period_kpis

                def sum_kpis(start_iso, end_iso):
                    s_, u_, p_, r_, x_ = resolve_period_kpis(start_iso, end_iso)
                    return s_, u_, p_, r_, x_'''

    text, n = pattern.subn(replacement, text, count=1)
    print(f"app.py sum_kpis replacements: {n}")

    # 3) Replace assignments
    text = text.replace(
        "signups, uploads, payments = sum_kpis(period.start_iso(), period.end_iso())",
        "signups, uploads, payments, recurring_customers, stopped_recurring_customers = sum_kpis(period.start_iso(), period.end_iso())"
    )

    text = text.replace(
        """prev_signups, prev_uploads, prev_payments = sum_kpis(
                            period.compare_start_iso(), period.compare_end_iso()
                        )""",
        """prev_signups, prev_uploads, prev_payments, prev_recurring_customers, prev_stopped_recurring_customers = sum_kpis(
                            period.compare_start_iso(), period.compare_end_iso()
                        )"""
    )

    # 4) Clean labels
    text = text.replace("New New Paying Customers", "New Paying Customers")
    text = text.replace("💳 Paid", "💳 New Paying Customers")
    text = text.replace("Paying Customers", "New Paying Customers")

    # 5) Inject recurring/stopped section once
    anchor = "        # ── Pipeline controls + health ──"
    if "Recurring Customers" not in text and anchor in text:
        inject = """
        st.markdown("<div style='margin-top:18px;'></div>", unsafe_allow_html=True)
        st.markdown(
            '''
            <div style="margin-bottom:8px;">
              <div style="font-size:13px;color:#9CA3AF;font-weight:600;letter-spacing:.02em;">
                CUSTOMER PAYMENT BREAKDOWN
              </div>
            </div>
            ''',
            unsafe_allow_html=True,
        )
        rc1, rc2 = st.columns(2)
        rc1.metric("🔁 Recurring Customers", f"{int(recurring_customers):,}")
        rc2.metric("🛑 Stopped Recurring", f"{int(stopped_recurring_customers):,}")

"""
        text = text.replace(anchor, inject + anchor, 1)
        print("✅ app.py recurring/stopped section injected")
    else:
        print("ℹ️ app.py recurring/stopped section already present or anchor missing")

    app.write_text(text, encoding="utf-8")
    print("✅ app.py written")
else:
    print("SKIP: app.py missing")

# -------------------------------------------------------------------
# pages_registry.py
# -------------------------------------------------------------------
pr = Path("pages_registry.py")
if pr.exists():
    backup(pr)
    text = pr.read_text(encoding="utf-8", errors="ignore")

    # 1) Replace legacy sum_kpis block exactly from current snippet
    old_block = """    def sum_kpis(s_iso, e_iso):
        rows = find_all("daily_kpis",
                        filters={"date": {"$gte": s_iso, "$lte": e_iso}})
        return (
            sum(int(r.get("signups_accepted", 0) or 0) for r in rows),
            sum(int(r.get("uploads_accepted", 0) or 0) for r in rows),
            sum(int(r.get("paid_accepted",    0) or 0) for r in rows),
        )
"""
    new_block = """    from kpi_totals_resolver import resolve_period_kpis

    def sum_kpis(s_iso, e_iso):
        s, u, p, r, x = resolve_period_kpis(s_iso, e_iso)
        return s, u, p, r, x
"""
    if old_block in text:
        text = text.replace(old_block, new_block, 1)
        print("✅ pages_registry.py sum_kpis replaced")
    else:
        print("WARN: pages_registry.py exact sum_kpis block not found")

    # 2) Replace assignments
    text = text.replace(
        "sign, up, pay = sum_kpis(period.start_iso(), period.end_iso())",
        "sign, up, pay, recurring, stopped = sum_kpis(period.start_iso(), period.end_iso())"
    )

    text = text.replace(
        """prev_s, prev_u, prev_p = sum_kpis(period.compare_start_iso(),
                                              period.compare_end_iso())""",
        """prev_s, prev_u, prev_p, prev_recurring, prev_stopped = sum_kpis(period.compare_start_iso(),
                                              period.compare_end_iso())"""
    )

    # 3) Fix paid label typo
    text = text.replace('c3.metric("💳 New New Paying Customers",       f"{pay:,}",  _pct(pay, prev_p))',
                        'c3.metric("💳 New Paying Customers",       f"{pay:,}",  _pct(pay, prev_p))')
    text = text.replace('c3.metric("💳 PAID",       f"{pay:,}",  _pct(pay, prev_p))',
                        'c3.metric("💳 New Paying Customers",       f"{pay:,}",  _pct(pay, prev_p))')
    text = text.replace('c3.metric("💳 Paid",       f"{pay:,}",  _pct(pay, prev_p))',
                        'c3.metric("�� New Paying Customers",       f"{pay:,}",  _pct(pay, prev_p))')

    # 4) Inject recurring/stopped cards once
    anchor = 'c3.metric("💳 New Paying Customers",       f"{pay:,}",  _pct(pay, prev_p))'
    if "Stopped Recurring" not in text and anchor in text:
        inject = """
    st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)
    c4, c5 = st.columns(2)
    c4.metric("🔁 Recurring Customers", f"{recurring:,}")
    c5.metric("🛑 Stopped Recurring", f"{stopped:,}")
"""
        text = text.replace(anchor, anchor + inject, 1)
        print("✅ pages_registry.py recurring/stopped cards injected")
    else:
        print("ℹ️ pages_registry.py recurring/stopped cards already present or anchor missing")

    # 5) Fix trend chart data columns
    text = text.replace(
        'for c in ["signups_accepted", "uploads_accepted", "paid_accepted"]:',
        'for c in ["signups", "first_uploads", "new_paid_customers"]:'
    )
    text = text.replace(
        '("signups_accepted", "Sign-ups", "#9EFF2F", "rgba(158,255,47,0.10)")',
        '("signups", "Sign-ups", "#9EFF2F", "rgba(158,255,47,0.10)")'
    )
    text = text.replace(
        '("uploads_accepted", "Uploads",  "#5EF46A", "rgba(94,244,106,0.08)")',
        '("first_uploads", "Uploads",  "#5EF46A", "rgba(94,244,106,0.08)")'
    )
    text = text.replace(
        '("paid_accepted",    "Paid",     "#4ADE80", "rgba(74,222,128,0.06)")',
        '("new_paid_customers",    "New Paying Customers",     "#4ADE80", "rgba(74,222,128,0.06)")'
    )

    pr.write_text(text, encoding="utf-8")
    print("✅ pages_registry.py written")
else:
    print("SKIP: pages_registry.py missing")

print("✅ must-fix KPI zero bug patch complete")
