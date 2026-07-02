#!/usr/bin/env python3
# DASHBOARD VALIDATED COMPONENTS - Priorities 3, 5, 8
import json
import streamlit as st
from pathlib import Path
from datetime import datetime


def show_validation_banner(kpi_stats: dict):
    banner = kpi_stats.get("validation_banner", "")
    if not banner:
        return
    if "Failed" in banner:
        st.error(banner)
    elif "Warning" in banner:
        st.warning(banner)


def show_alltime_note(kpi_stats: dict):
    start  = kpi_stats.get("alltime_start", "")
    end    = kpi_stats.get("alltime_end", "")
    s_full = kpi_stats.get("signups_full_db", 0)
    u_full = kpi_stats.get("uploads_full_db", 0)
    p_full = kpi_stats.get("paid_full_db", 0)
    if start and end:
        st.info(
            f"All-Time = Common Data Period ({start} to {end}). "
            f"Upload tracking started Dec 2025. Conversion rates only valid when ALL metrics have data. "
            f"Full DB totals: Signups={s_full:,} Uploads={u_full:,} Paid={p_full:,}"
        )


def show_validated_kpi_metrics(kpi_stats: dict, period: str = "alltime"):
    show_validation_banner(kpi_stats)
    if period == "today":
        s     = kpi_stats.get("signups_today", 0)
        u     = kpi_stats.get("uploads_today", 0)
        p     = kpi_stats.get("paid_today", 0)
        label = "Today ({})".format(kpi_stats.get("today_str",""))
    elif period == "month":
        s     = kpi_stats.get("signups_month", 0)
        u     = kpi_stats.get("uploads_month", 0)
        p     = kpi_stats.get("paid_month", 0)
        label = "Month ({})".format(kpi_stats.get("month_str",""))
    else:
        s     = kpi_stats.get("signups_all", 0)
        u     = kpi_stats.get("uploads_all", 0)
        p     = kpi_stats.get("paid_all", 0)
        label = kpi_stats.get("alltime_period", "Common Period")
    c1, c2, c3 = st.columns(3)
    c1.metric("Sign-ups", "{:,}".format(s), help="Period: {}".format(label))
    c2.metric("Uploads",  "{:,}".format(u), help="Period: {}".format(label))
    c3.metric("Paid",     "{:,}".format(p), help="Period: {}".format(label))
    if period == "alltime" and s > 0:
        s2u = u / s * 100
        s2p = p / s * 100
        st.caption("Sign to Upload: {:.1f}% | Sign to Paid: {:.1f}% (valid for {})".format(s2u, s2p, label))
        show_alltime_note(kpi_stats)


def show_override_ui():
    st.subheader("Manual Overrides")
    st.caption("Manual overrides are AUTHORITATIVE and permanent. Automation never overwrites them.")
    try:
        from override_engine import (
            set_override, remove_override,
            get_override_summary, get_audit_log, load_overrides
        )
    except ImportError:
        st.error("override_engine.py not found")
        return
    summary = get_override_summary()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total",    summary["total"])
    c2.metric("Accepted", summary["accepted"])
    c3.metric("Rejected", summary["rejected"])
    c4.metric("Pending",  summary["pending"])
    st.divider()
    with st.expander("Set New Override", expanded=False):
        with st.form("set_override_form"):
            email  = st.text_input("Email")
            action = st.selectbox("Action", ["accept","reject","pending"])
            reason = st.text_area("Reason (required)")
            user   = st.text_input("Your Name or Email")
            source = st.selectbox("Source Tab", ["","FREE","STRIPE","FIRST_UPLOAD"])
            if st.form_submit_button("Set Override"):
                if not email or "@" not in email:
                    st.error("Valid email required")
                elif not reason.strip():
                    st.error("Reason required")
                elif not user.strip():
                    st.error("Your name required")
                else:
                    try:
                        rec = set_override(email, action, reason, user, source)
                        st.success("Override set: {} -> {}".format(email, action.upper()))
                        st.json(rec)
                    except Exception as e:
                        st.error("Failed: {}".format(e))
    with st.expander("Remove Override", expanded=False):
        with st.form("remove_override_form"):
            rem_email  = st.text_input("Email to remove override")
            rem_reason = st.text_input("Reason")
            rem_user   = st.text_input("Your Name or Email")
            if st.form_submit_button("Remove Override"):
                if not rem_email:
                    st.error("Email required")
                else:
                    try:
                        ok = remove_override(rem_email, rem_user, rem_reason)
                        if ok:
                            st.success("Override removed for {}".format(rem_email))
                        else:
                            st.warning("No override found for {}".format(rem_email))
                    except Exception as e:
                        st.error("Failed: {}".format(e))
    st.subheader("Active Overrides")
    overrides = load_overrides()
    if overrides:
        import pandas as pd
        rows = [{
            "Email":     em,
            "Action":    ov.get("action",""),
            "Status":    ov.get("final_status",""),
            "Reason":    ov.get("reason","")[:60],
            "Set By":    ov.get("override_user",""),
            "Timestamp": ov.get("override_timestamp","")[:19],
            "Tab":       ov.get("source_tab",""),
        } for em, ov in overrides.items()]
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
    else:
        st.info("No active overrides")
    st.subheader("Override Audit Log")
    search = st.text_input("Filter by email (optional)", key="audit_search")
    audit  = get_audit_log(email=search if search else None, limit=50)
    if audit:
        import pandas as pd
        df   = pd.DataFrame(audit)
        cols = [c for c in ["timestamp","email","action","previous_action",
                            "new_status","reason","user","change_type"] if c in df.columns]
        st.dataframe(df[cols], use_container_width=True)
    else:
        st.info("No audit log entries{}".format(" for {}".format(search) if search else ""))


def show_browse_diagnostics(rows: list, filters_applied: dict):
    total_raw    = filters_applied.get("raw_total", len(rows))
    after_date   = filters_applied.get("after_date_filter",   total_raw)
    after_status = filters_applied.get("after_status_filter", after_date)
    after_search = filters_applied.get("after_search_filter", after_status)
    final        = len(rows)
    with st.expander("Filter Diagnostics", expanded=(final == 0)):
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Raw",          total_raw)
        c2.metric("After Date",   after_date,   delta="-{}".format(total_raw - after_date)     if total_raw > after_date    else None)
        c3.metric("After Status", after_status, delta="-{}".format(after_date - after_status)  if after_date > after_status else None)
        c4.metric("After Search", after_search, delta="-{}".format(after_status - after_search) if after_status > after_search else None)
        c5.metric("Displayed",    final)
        if final == 0 and total_raw > 0:
            st.error("All records excluded by filters!")
            if total_raw - after_date > 0:
                st.write("Date filter excluded {} records - check date range".format(total_raw - after_date))
            if after_date - after_status > 0:
                st.write("Status filter excluded {} records - try All status".format(after_date - after_status))
            if after_status - after_search > 0:
                st.write("Search excluded {} records - clear search".format(after_status - after_search))
        if total_raw == 0:
            st.warning("No raw records loaded - check Google Sheets connection or data pipeline")


def show_audit_report_widget():
    audit_path = Path("data_output/audits/audit_latest.json")
    if not audit_path.exists():
        st.warning("No audit report found. Run: python3 run_full_audit.py")
        return
    try:
        audit = json.loads(audit_path.read_text())
    except Exception as e:
        st.error("Could not load audit: {}".format(e))
        return
    st.subheader("Data Integrity Audit")
    st.caption("Generated: {} UTC".format(audit.get("generated_at","")[:19]))
    cp = audit.get("coverage_periods", {})
    import pandas as pd
    cp_rows = [{
        "Metric":   k,
        "Start":    v.get("start","N/A"),
        "End":      v.get("end","N/A"),
        "Records":  v.get("total", v.get("records","N/A")),
    } for k, v in cp.items()]
    st.dataframe(pd.DataFrame(cp_rows), use_container_width=True)
    common = audit.get("common_period", {})
    if common:
        st.success(
            "Valid All-Time: {} to {} | Signups={} Uploads={} Paid={}".format(
                common.get("start",""), common.get("end",""),
                common.get("common_signups",0),
                common.get("common_uploads",0),
                common.get("common_paid",0),
            )
        )
    failures = audit.get("validation_failures", [])
    passes   = audit.get("validation_passes",   [])
    c1, c2   = st.columns(2)
    c1.metric("Passed",   len(passes))
    c2.metric("Warnings", len(failures))
    for f in failures:
        icon = "ERROR" if f["status"] == "FAIL" else "WARNING"
        st.write("{}: {}: {}".format(icon, f["rule"], f["message"]))
    with st.expander("Root Causes"):
        for rc in audit.get("summary",{}).get("root_cause",[]):
            st.write("- {}".format(rc))
