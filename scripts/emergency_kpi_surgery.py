from pathlib import Path
from datetime import datetime

def backup(path: Path):
    b = Path("backups") / f"{path.name}.emergency_kpi_surgery.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
    b.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
    print(f"BACKUP: {path} -> {b}")

# ------------------------------------------------------------------
# app.py
# ------------------------------------------------------------------
app = Path("app.py")
if not app.exists():
    raise SystemExit("❌ app.py not found")

backup(app)
app_lines = app.read_text(encoding="utf-8", errors="ignore").splitlines()

# Replace route() block by line numbers based on your own printed source:
# route starts around 735, dashboard section starts at 782
new_route_block = """
def route(page: str, user_email: str) -> None:
    if page == "dashboard":
        render_dashboard(user_email)
    elif page == "kpi":
        from pages_registry import render_kpi_page
        render_kpi_page(user_email)
    elif page == "ga4":
        from pages_registry import render_ga4_page
        render_ga4_page(user_email)
    elif page == "youtube":
        from pages_registry import render_youtube_page
        render_youtube_page(user_email)
    elif page == "linkedin":
        from pages_registry import render_linkedin_page
        render_linkedin_page(user_email)
    elif page == "cs":
        from pages_registry import render_cs_page
        render_cs_page(user_email)
    elif page == "ai":
        from pages_registry import render_ai_page
        render_ai_page(user_email)
    elif page == "cross":
        from pages_registry import render_cross_page
        render_cross_page(user_email)
    elif page == "custom":
        from pages_registry import render_custom_page
        render_custom_page(user_email)
    elif page == "settings":
        st.info("Settings page is available through the app controls.")
    elif page == "_logout":
        for k in ("_pwd_ok", "_auth_ok", "user_email", "user_role", "current_page"):
            st.session_state.pop(k, None)
        st.query_params.clear()
        st.rerun()
    else:
        st.warning(f"Unknown page: {page}")
""".strip("\n").splitlines()

# 735..781 in 1-based line numbers => 734:781 in 0-based slices
if len(app_lines) >= 781:
    app_lines[734:781] = new_route_block
else:
    raise SystemExit("❌ app.py shorter than expected; cannot repair route block safely")

# Fix dashboard KPI logic by line numbers around 843..858 from your printed source
app_text = "\n".join(app_lines) + "\n"

old_sum = """                def sum_kpis(start_iso, end_iso):
                    rows = find_all("daily_kpis",
                                    filters={"date": {"$gte": start_iso, "$lte": end_iso}},
                                    sort=[("date", 1)])
                    s_ = sum(int(r.get("signups_accepted", 0) or 0) for r in rows)
                    u_ = sum(int(r.get("uploads_accepted", 0) or 0) for r in rows)
                    p_ = sum(int(r.get("paid_accepted",    0) or 0) for r in rows)
                    return s_, u_, p_
"""
new_sum = """                def sum_kpis(start_iso, end_iso):
                    rows = find_all("daily_kpis",
                                    filters={"date": {"$gte": start_iso[:10], "$lte": end_iso[:10]}},
                                    sort=[("date", 1)])
                    s_ = sum(int(r.get("signups", 0) or 0) for r in rows)
                    u_ = sum(int(r.get("first_uploads", r.get("uploads", 0)) or 0) for r in rows)
                    p_ = sum(int(r.get("new_paid_customers", r.get("paid_customers", 0)) or 0) for r in rows)
                    return s_, u_, p_
"""
app_text = app_text.replace(old_sum, new_sum, 1)

app_text = app_text.replace("New New Paying Customers", "New Paying Customers")
app_text = app_text.replace("💳 Paid", "💳 New Paying Customers")
app_text = app_text.replace("Paying Customers", "New Paying Customers")

# Remove broken recurring UI snippets if any remain
app_text = app_text.replace("""
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

""", "")

app.write_text(app_text, encoding="utf-8")
print("✅ app.py repaired")

# ------------------------------------------------------------------
# pages_registry.py
# ------------------------------------------------------------------
pr = Path("pages_registry.py")
if not pr.exists():
    raise SystemExit("❌ pages_registry.py not found")

backup(pr)
pr_text = pr.read_text(encoding="utf-8", errors="ignore")

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
pr_text = pr_text.replace(old_block, new_block, 1)

# remove recurring UI additions
pr_text = pr_text.replace("""
    st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)
    c4, c5 = st.columns(2)
    c4.metric("🔁 Recurring Customers", f"{recurring:,}")
    c5.metric("🛑 Stopped Recurring", f"{stopped:,}")
""", "")

# restore simple 3-value assignments
pr_text = pr_text.replace(
    "sign, up, pay, recurring, stopped = sum_kpis(period.start_iso(), period.end_iso())",
    "sign, up, pay = sum_kpis(period.start_iso(), period.end_iso())"
)
pr_text = pr_text.replace(
    "prev_s, prev_u, prev_p, prev_recurring, prev_stopped = sum_kpis(period.compare_start_iso(),",
    "prev_s, prev_u, prev_p = sum_kpis(period.compare_start_iso(),"
)

# labels
pr_text = pr_text.replace("New New Paying Customers", "New Paying Customers")
pr_text = pr_text.replace('c3.metric("💳 PAID",', 'c3.metric("💳 New Paying Customers",')
pr_text = pr_text.replace('c3.metric("💳 Paid",', 'c3.metric("💳 New Paying Customers",')

# chart columns
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

print("✅ emergency KPI surgery complete")
