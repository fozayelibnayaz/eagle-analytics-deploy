from __future__ import annotations

from datetime import date
import streamlit as st

from mongo_client import find_all

def _as_int(v):
    try:
        if v is None or str(v).strip() == "":
            return 0
        return int(float(v))
    except Exception:
        return 0

def _month_rows():
    today = date.today()
    month_start = today.replace(day=1).isoformat()
    month_end = today.isoformat()

    rows = find_all("daily_kpis", sort=[("date", 1)], limit=10000)
    rows = [r for r in rows if month_start <= str(r.get("date", "")) <= month_end]
    return rows, month_start, month_end

def render_customer_kpi_breakdown():
    rows, month_start, month_end = _month_rows()

    new_paid = sum(_as_int(r.get("new_paid_customers", r.get("paid_customers", 0))) for r in rows)
    recurring = sum(_as_int(r.get("recurring_customers", 0)) for r in rows)
    stopped = sum(_as_int(r.get("stopped_recurring_customers", 0)) for r in rows)

    st.markdown(
        f"""
        <div style="margin-top:18px;margin-bottom:8px;">
          <div style="font-size:13px;color:#9CA3AF;font-weight:600;letter-spacing:.02em;">
            CUSTOMER PAYMENT BREAKDOWN
          </div>
          <div style="font-size:12px;color:#6B7280;margin-top:4px;">
            This Month · {month_start} → {month_end}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("💳 New Paying Customers", f"{new_paid:,}")
    with c2:
        st.metric("🔁 Recurring Customers", f"{recurring:,}")
    with c3:
        st.metric("🛑 Stopped Recurring", f"{stopped:,}")
