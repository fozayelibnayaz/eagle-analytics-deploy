from pathlib import Path
from datetime import datetime

def backup(path: Path):
    b = Path("backups") / f"{path.name}.final_stable_kpi_fix.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
    b.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
    print(f"BACKUP: {path} -> {b}")

# ---------------- app.py ----------------
app = Path("app.py")
if app.exists():
    backup(app)
    text = app.read_text(encoding="utf-8", errors="ignore")

    # remove recurring/stopped breakdown section if present
    recurring_block = """
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
        rc1.metric("�� Recurring Customers", f"{int(recurring_customers):,}")
        rc2.metric("🛑 Stopped Recurring", f"{int(stopped_recurring_customers):,}")

"""
    text = text.replace(recurring_block, "")

    # remove any dashboard customer breakdown import/injection
    inject_block = """
        try:
            from customer_kpi_breakdown_ui import render_customer_kpi_breakdown
            render_customer_kpi_breakdown()
        except Exception as _e:
            st.warning(f"Customer KPI breakdown unavailable: {_e}")
"""
    text = text.replace(inject_block, "")

    # restore simple defaults
    text = text.replace(
        "signups = uploads = payments = recurring_customers = stopped_recurring_customers = 0",
        "signups = uploads = payments = 0"
    )
    text = text.replace(
        "prev_signups = prev_uploads = prev_payments = prev_recurring_customers = prev_stopped_recurring_customers = 0",
        "prev_signups = prev_uploads = prev_payments = 0"
    )

    # patch sum_kpis block to use correct fields only
    old_block = """                def sum_kpis(start_iso, end_iso):
                    rows = find_all("daily_kpis",
                                    filters={"date": {"$gte": start_iso, "$lte": end_iso}},
                                    sort=[("date", 1)])
                    s_ = sum(int(r.get("signups_accepted", 0) or 0) for r in rows)
                    u_ = sum(int(r.get("uploads_accepted", 0) or 0) for r in rows)
                    p_ = sum(int(r.get("paid_accepted",    0) or 0) for r in rows)
                    return s_, u_, p_
"""
    new_block = """                def sum_kpis(start_iso, end_iso):
                    rows = find_all("daily_kpis",
                                    filters={"date": {"$gte": start_iso[:10], "$lte": end_iso[:10]}},
                                    sort=[("date", 1)])
                    s_ = sum(int(r.get("signups", 0) or 0) for r in rows)
                    u_ = sum(int(r.get("first_uploads", r.get("uploads", 0)) or 0) for r in rows)
                    p_ = sum(int(r.get("new_paid_customers", r.get("paid_customers", 0)) or 0) for r in rows)
                    return s_, u_, p_
"""
    text = text.replace(old_block, new_block)

    # if previous broken variants exist, normalize them
    text = text.replace(
        "signups, uploads, payments, recurring_customers, stopped_recurring_customers = sum_kpis(period.start_iso(), period.end_iso())",
        "signups, uploads, payments = sum_kpis(period.start_iso(), period.end_iso())"
    )
    text = text.replace(
        "prev_signups, prev_uploads, prev_payments, prev_recurring_customers, prev_stopped_recurring_customers = sum_kpis(",
        "prev_signups, prev_uploads, prev_payments = sum_kpis("
    )

    text = text.replace("New New Paying Customers", "New Paying Customers")
    text = text.replace("💳 Paid", "💳 New Paying Customers")

    app.write_text(text, encoding="utf-8")
    print("✅ app.py patched")

# ---------------- pages_registry.py ----------------
pr = Path("pages_registry.py")
if pr.exists():
    backup(pr)
    text = pr.read_text(encoding="utf-8", errors="ignore")

    # remove recurring/stopped cards block if present
    recurring_cards = """
    st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)
    c4, c5 = st.columns(2)
    c4.metric("🔁 Recurring Customers", f"{recurring:,}")
    c5.metric("🛑 Stopped Recurring", f"{stopped:,}")
"""
    text = text.replace(recurring_cards, "")

    # replace exact sum_kpis block
    old_block = """    def sum_kpis(s_iso, e_iso):
        rows = find_all("daily_kpis",
                        filters={"date": {"$gte": s_iso, "$lte": e_iso}})
        return (
            sum(int(r.get("signups_accepted", 0) or 0) for r in rows),
            sum(int(r.get("uploads_accepted", 0) or 0) for r in rows),
            sum(int(r.get("paid_accepted",    0) or 0) for r in rows),
        )
"""
    new_block = """    def sum_kpis(s_iso, e_iso):
        rows = find_all("daily_kpis",
                        filters={"date": {"$gte": s_iso[:10], "$lte": e_iso[:10]}})
        return (
            sum(int(r.get("signups", 0) or 0) for r in rows),
            sum(int(r.get("first_uploads", r.get("uploads", 0)) or 0) for r in rows),
            sum(int(r.get("new_paid_customers", r.get("paid_customers", 0)) or 0) for r in rows),
        )
"""
    text = text.replace(old_block, new_block)

    # normalize assignments back to 3 values
    text = text.replace(
        "sign, up, pay, recurring, stopped = sum_kpis(period.start_iso(), period.end_iso())",
        "sign, up, pay = sum_kpis(period.start_iso(), period.end_iso())"
    )
    text = text.replace(
        "prev_s, prev_u, prev_p, prev_recurring, prev_stopped = sum_kpis(period.compare_start_iso(),",
        "prev_s, prev_u, prev_p = sum_kpis(period.compare_start_iso(),"
    )

    # fix labels
    text = text.replace("New New Paying Customers", "New Paying Customers")
    text = text.replace('c3.metric("💳 PAID",', 'c3.metric("💳 New Paying Customers",')
    text = text.replace('c3.metric("💳 Paid",', 'c3.metric("💳 New Paying Customers",')

    # fix chart columns
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
    print("✅ pages_registry.py patched")

print("✅ final stable KPI fix completed")
