from pathlib import Path
from datetime import datetime

def backup(path: Path):
    b = Path("backups") / f"{path.name}.root_fix_kpi_zero_bug.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
    b.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
    print(f"BACKUP: {path} -> {b}")

# ---------- app.py ----------
app = Path("app.py")
if app.exists():
    backup(app)
    text = app.read_text(encoding="utf-8", errors="ignore")

    old_sum_block = """                def sum_kpis(start_iso, end_iso):
                    rows = find_all("daily_kpis",
                                    filters={"date": {"$gte": start_iso, "$lte": end_iso}},
                                    sort=[("date", 1)])
                    s_ = sum(int(r.get("signups_accepted", 0) or 0) for r in rows)
                    u_ = sum(int(r.get("uploads_accepted", 0) or 0) for r in rows)
                    p_ = sum(int(r.get("paid_accepted",    0) or 0) for r in rows)
                    return s_, u_, p_
"""

    new_sum_block = """                from kpi_totals_resolver import resolve_period_kpis

                def sum_kpis(start_iso, end_iso):
                    s_, u_, p_, r_, x_ = resolve_period_kpis(start_iso, end_iso)
                    return s_, u_, p_, r_, x_
"""

    if old_sum_block in text:
        text = text.replace(old_sum_block, new_sum_block, 1)
        print("✅ app.py: replaced legacy sum_kpis block")
    else:
        print("WARN: app.py legacy sum_kpis block not found exactly")

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

    text = text.replace("New New Paying Customers", "New Paying Customers")

    # inject recurring/stopped cards before pipeline controls
    anchor = "        # ── Pipeline controls + health ──"
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
    if anchor in text and "Recurring Customers" not in text:
        text = text.replace(anchor, inject + anchor, 1)
        print("✅ app.py: injected recurring/stopped recurring section")
    else:
        print("ℹ️ app.py: recurring/stopped section already present or anchor missing")

    app.write_text(text, encoding="utf-8")
    print("✅ app.py written")

# ---------- pages_registry.py ----------
pr = Path("pages_registry.py")
if pr.exists():
    backup(pr)
    text = pr.read_text(encoding="utf-8", errors="ignore")

    old_sum_block = """    def sum_kpis(s_iso, e_iso):
        rows = find_all("daily_kpis",
                        filters={"date": {"$gte": s_iso, "$lte": e_iso}})
        return (
            sum(int(r.get("signups_accepted", 0) or 0) for r in rows),
            sum(int(r.get("uploads_accepted", 0) or 0) for r in rows),
            sum(int(r.get("paid_accepted",    0) or 0) for r in rows),
        )
"""

    new_sum_block = """    from kpi_totals_resolver import resolve_period_kpis

    def sum_kpis(s_iso, e_iso):
        s, u, p, r, x = resolve_period_kpis(s_iso, e_iso)
        return s, u, p, r, x
"""

    if old_sum_block in text:
        text = text.replace(old_sum_block, new_sum_block, 1)
        print("✅ pages_registry.py: replaced legacy sum_kpis block")
    else:
        print("WARN: pages_registry.py legacy sum_kpis block not found exactly")

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

    text = text.replace('c3.metric("💳 New New Paying Customers",       f"{pay:,}",  _pct(pay, prev_p))',
                        'c3.metric("💳 New Paying Customers",       f"{pay:,}",  _pct(pay, prev_p))')
    text = text.replace('c3.metric("💳 PAID",       f"{pay:,}",  _pct(pay, prev_p))',
                        'c3.metric("💳 New Paying Customers",       f"{pay:,}",  _pct(pay, prev_p))')
    text = text.replace('c3.metric("💳 Paid",       f"{pay:,}",  _pct(pay, prev_p))',
                        'c3.metric("�� New Paying Customers",       f"{pay:,}",  _pct(pay, prev_p))')

    # inject recurring/stopped cards after first metric row
    anchor = 'c3.metric("💳 New Paying Customers",       f"{pay:,}",  _pct(pay, prev_p))'
    inject = """
    st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)
    c4, c5 = st.columns(2)
    c4.metric("🔁 Recurring Customers", f"{recurring:,}")
    c5.metric("🛑 Stopped Recurring", f"{stopped:,}")
"""
    if anchor in text and "Stopped Recurring" not in text:
        text = text.replace(anchor, anchor + inject, 1)
        print("✅ pages_registry.py: injected recurring/stopped recurring cards")
    else:
        print("ℹ️ pages_registry.py: recurring/stopped cards already present or anchor missing")

    # patch chart columns
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

print("✅ root KPI zero bug patch complete")
