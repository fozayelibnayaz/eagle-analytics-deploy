"""
custom_modules_ui.py — Custom Modules (upload any sheet → dashboard)

Features:
  - Upload CSV / Excel / paste Google Sheets URL
  - Auto-schema detection (date/numeric/category/email)
  - Auto-generated charts based on column types
  - Editable data table (via editable_tables.py)
  - AI Q&A specific to this module
  - Save & reuse — modules appear in sidebar
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd
import streamlit as st

from custom_modules_engine import (
    list_modules, get_module, create_module, deactivate_module,
    read_uploaded_file, ingest_dataframe, get_module_df,
    summarize_dataframe, detect_column_types,
    load_from_google_sheet_url, ai_qa_over_module, slugify,
    module_collection,
)


# ─── SETTINGS / MANAGE UI ────────────────────────────────────────
def render_custom_module_settings() -> None:
    """Create / list / delete modules."""
    st.markdown("### 🧩 Custom Modules")
    st.caption("Upload any spreadsheet → auto-generated dashboard with charts, "
                "editable table & AI chat.")

    tabs = st.tabs(["➕ Create New", "📋 Manage Existing"])

    # ── CREATE ──
    with tabs[0]:
        _render_create_form()

    # ── MANAGE ──
    with tabs[1]:
        _render_manage_list()


def _render_create_form() -> None:
    st.markdown("#### Step 1 · Basic info")
    c1, c2 = st.columns(2)
    with c1:
        name = st.text_input("Module name",
                              placeholder="e.g. HR Employee List",
                              key="cm_new_name")
    with c2:
        team = st.selectbox("Team",
                             ["HR", "Sales", "Marketing", "Customer Success",
                              "Finance", "Product", "Ops", "Other"],
                             key="cm_new_team")

    description = st.text_area("Description (optional)",
                                key="cm_new_desc",
                                placeholder="What does this data track?")

    st.markdown("#### Step 2 · Upload data")

    source_type = st.radio("Data source",
                             ["📁 Upload file (CSV/Excel)",
                              "🔗 Google Sheets URL"],
                             horizontal=True,
                             key="cm_new_source")

    df: Optional[pd.DataFrame] = None
    source_meta = {}

    if source_type.startswith("📁"):
        f = st.file_uploader("Choose a file",
                              type=["csv", "xlsx", "xls"],
                              key="cm_new_file")
        if f:
            try:
                df = read_uploaded_file(f)
                source_meta = {"source_type": "upload", "filename": f.name}
                st.success(f"✅ Loaded {len(df)} rows × {len(df.columns)} columns")
            except Exception as e:
                st.error(f"Read error: {e}")
    else:
        url = st.text_input("Google Sheets URL",
                             placeholder="https://docs.google.com/spreadsheets/d/...",
                             key="cm_new_url")
        tab_name = st.text_input("Sheet tab name (leave blank for first tab)",
                                   key="cm_new_tab")
        if url and st.button("🔄 Fetch from Google Sheets",
                              key="cm_new_fetch"):
            try:
                with st.spinner("Fetching..."):
                    df = load_from_google_sheet_url(url, tab_name or None)
                    source_meta = {"source_type": "gsheet", "url": url,
                                    "tab_name": tab_name or "sheet1"}
                    st.success(f"✅ Loaded {len(df)} rows × {len(df.columns)} columns")
                    st.session_state["cm_new_df"] = df
                    st.session_state["cm_new_source_meta"] = source_meta
            except Exception as e:
                st.error(f"Fetch error: {e}")

    # Pull from session if just loaded
    if df is None and "cm_new_df" in st.session_state:
        df = st.session_state["cm_new_df"]
        source_meta = st.session_state.get("cm_new_source_meta", {})

    if df is not None and not df.empty:
        st.markdown("#### Step 3 · Preview & confirm")

        types = detect_column_types(df)
        with st.expander("🔍 Detected column types", expanded=False):
            st.dataframe(
                pd.DataFrame({"column": list(types.keys()),
                              "detected type": list(types.values())}),
                width='stretch', hide_index=True,
            )

        st.markdown("**Preview (first 20 rows)**")
        st.dataframe(df.head(20), width='stretch', hide_index=True)

        if not name:
            st.warning("Enter a module name above to continue")
        elif st.button("💾 Create Module",
                        type="primary", key="cm_new_save"):
            try:
                # Positional args match engine signature:
                #   create_module(name, description, team, requested_analysis, created_by)
                user_email = st.session_state.get("user_email", "system")
                result = create_module(
                    name=name,
                    description=description or "",
                    team=team,
                    requested_analysis="",
                    created_by=user_email,
                )
                if not result.get("success"):
                    st.error(result.get("message", "Create failed"))
                else:
                    slug = slugify(name)
                    # Store extra metadata (column_types, source info) directly
                    from mongo_client import get_db
                    db = get_db()
                    if db is not None:
                        db["custom_modules"].update_one(
                            {"slug": slug},
                            {"$set": {
                                "column_types": types,
                                **source_meta,
                            }},
                        )
                    # Ingest data
                    res = ingest_dataframe(slug, df, replace=True)
                    inserted = (res.get("inserted") if isinstance(res, dict) else 0) or 0
                    st.success(f"✅ Module '{name}' created with {inserted} rows")
                    st.session_state.pop("cm_new_df", None)
                    st.session_state.pop("cm_new_source_meta", None)
                    st.rerun()
            except Exception as e:
                import traceback
                st.error(f"Save error: {e}")
                with st.expander("Traceback"):
                    st.code(traceback.format_exc())


def _render_manage_list() -> None:
    mods = list_modules(active_only=False)
    if not mods:
        st.info("No custom modules yet. Create one above.")
        return

    st.caption(f"{len(mods)} module(s)")
    df = pd.DataFrame(mods)
    show_cols = [c for c in ["name", "team", "slug", "created_at",
                              "is_active", "rows"] if c in df.columns]
    st.dataframe(df[show_cols], width='stretch', hide_index=True)

    st.markdown("---")
    st.markdown("#### 🗑️ Delete a module")
    slugs = [m["slug"] for m in mods]
    to_delete = st.selectbox("Pick module to deactivate",
                                slugs, key="cm_delete")
    if st.button("🗑️ Deactivate", key="cm_delete_btn"):
        r = deactivate_module(to_delete)
        st.success(f"Deactivated: {r}")
        st.rerun()


# ─── SINGLE MODULE PAGE (dashboard for one module) ─────────────
def render_custom_module_page(slug: str) -> None:
    module = get_module(slug)
    if not module:
        st.error(f"Module '{slug}' not found")
        return

    st.markdown(f"### 🧩 {module.get('name', slug)}")
    st.caption(module.get("description", ""))

    df = get_module_df(slug, limit=5000)
    if df.empty:
        st.info("This module has no data yet.")
        return

    # ── Top metrics ──
    summary = summarize_dataframe(df)
    types = module.get("column_types") or detect_column_types(df)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📊 Rows", f"{len(df):,}")
    m2.metric("📁 Columns", len(df.columns))
    numeric_cols = [c for c, t in types.items() if t == "numeric"]
    date_cols    = [c for c, t in types.items() if t == "date"]
    category_cols= [c for c, t in types.items() if t == "category"]
    m3.metric("🔢 Numeric",  len(numeric_cols))
    m4.metric("📅 Date",     len(date_cols))

    # ── Tabs: Data / Charts / AI ──
    tabs = st.tabs(["📊 Data (editable)", "📈 Auto Charts",
                     "✦ Ask AI", "⚙ Settings"])

    with tabs[0]:
        from editable_tables import render_editable_table
        user_email = st.session_state.get("user_email", "")
        # Pick a decent key field — first email column or first column
        key_field = "email"
        for c, t in types.items():
            if t == "email":
                key_field = c
                break
        else:
            key_field = df.columns[0]
        render_editable_table(
            collection=module_collection(slug),
            user_email=user_email,
            key_field=key_field,
            max_rows=500,
        )

    with tabs[1]:
        _render_auto_charts(df, types)

    with tabs[2]:
        _render_module_ai(slug)

    with tabs[3]:
        _render_module_settings(slug, module)


def _render_auto_charts(df: pd.DataFrame, types: dict) -> None:
    import plotly.express as px
    date_cols     = [c for c, t in types.items() if t == "date"]
    numeric_cols  = [c for c, t in types.items() if t == "numeric"]
    category_cols = [c for c, t in types.items() if t == "category"]

    if not (date_cols or numeric_cols or category_cols):
        st.info("No chartable columns detected.")
        return

    dark = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#9CA3AF"),
        margin=dict(l=0, r=0, t=30, b=0),
        xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
        height=340,
    )

    # 1. Category bar chart
    if category_cols:
        col = st.selectbox("📊 Category to chart", category_cols,
                            key="chart_cat")
        counts = df[col].value_counts().head(20)
        fig = px.bar(x=counts.index.astype(str), y=counts.values,
                      color_discrete_sequence=["#9EFF2F"],
                      title=f"Count by {col}")
        fig.update_layout(**dark)
        st.plotly_chart(fig, width='stretch')

    # 2. Numeric distribution
    if numeric_cols:
        col = st.selectbox("🔢 Numeric to histogram", numeric_cols,
                            key="chart_num")
        try:
            values = pd.to_numeric(df[col], errors="coerce").dropna()
            fig = px.histogram(x=values, nbins=30,
                                color_discrete_sequence=["#5EF46A"],
                                title=f"Distribution of {col}")
            fig.update_layout(**dark)
            st.plotly_chart(fig, width='stretch')
        except Exception as e:
            st.info(f"Histogram error: {e}")

    # 3. Time series (if both date & numeric)
    if date_cols and numeric_cols:
        c1, c2 = st.columns(2)
        with c1:
            date_col = st.selectbox("📅 Date column", date_cols,
                                      key="chart_date")
        with c2:
            metric = st.selectbox("📈 Metric", numeric_cols,
                                    key="chart_metric")
        try:
            plot_df = df[[date_col, metric]].copy()
            plot_df[date_col] = pd.to_datetime(plot_df[date_col],
                                                 errors="coerce")
            plot_df[metric] = pd.to_numeric(plot_df[metric],
                                              errors="coerce")
            plot_df = plot_df.dropna().groupby(date_col)[metric].sum().reset_index()
            fig = px.line(plot_df, x=date_col, y=metric, markers=True,
                           color_discrete_sequence=["#9EFF2F"],
                           title=f"{metric} over time")
            fig.update_layout(**dark)
            st.plotly_chart(fig, width='stretch')
        except Exception as e:
            st.info(f"Time series error: {e}")


def _render_module_ai(slug: str) -> None:
    st.markdown("#### ✦ Ask AI about this data")
    st.caption("The AI sees only THIS module's data.")

    key = f"module_ai_chat_{slug}"
    if key not in st.session_state:
        st.session_state[key] = []

    # Quick prompts
    st.markdown("**Try:**")
    q1, q2, q3 = st.columns(3)
    quick = None
    with q1:
        if st.button("📊 Summarize", key=f"{key}_q1", width='stretch'):
            quick = "Give me a high-level summary of this data."
    with q2:
        if st.button("📈 Trends", key=f"{key}_q2", width='stretch'):
            quick = "What are the top trends and patterns in this data?"
    with q3:
        if st.button("💡 Insights", key=f"{key}_q3", width='stretch'):
            quick = "Give me 3 non-obvious insights and 2 recommended actions."

    user_msg = st.text_area("Your question", height=80, key=f"{key}_input")

    if st.button("🚀 Ask", type="primary", key=f"{key}_ask") or quick:
        q = quick or user_msg
        if q:
            with st.spinner("AI thinking..."):
                answer = ai_qa_over_module(slug, q)
                st.session_state[key].append({
                    "q": q, "a": answer,
                    "at": datetime.now().strftime("%H:%M"),
                })

    # History
    if st.session_state[key]:
        st.markdown("---")
        for e in reversed(st.session_state[key][-10:]):
            with st.chat_message("user"):
                st.write(f"**{e['q']}** _{e['at']}_")
            with st.chat_message("assistant"):
                st.write(e["a"])

        if st.button("🗑 Clear history", key=f"{key}_clear"):
            st.session_state[key] = []
            st.rerun()


def _render_module_settings(slug: str, module: dict) -> None:
    st.markdown("#### ⚙ Module info")
    st.json({k: v for k, v in module.items() if not k.startswith("_")},
             expanded=False)

    st.markdown("---")

    # Refresh from source (if Google Sheet)
    if module.get("source_type") == "gsheet":
        st.markdown("#### 🔄 Refresh from Google Sheet")
        if st.button("Re-fetch data now", key=f"refetch_{slug}"):
            try:
                url = module.get("url", "")
                tab = module.get("tab_name", "") or None
                with st.spinner("Re-fetching..."):
                    df = load_from_google_sheet_url(url, tab)
                    res = ingest_dataframe(slug, df, replace=True)
                    st.success(f"✅ Refreshed {res.get('inserted', 0)} rows")
                    st.rerun()
            except Exception as e:
                st.error(f"Refresh error: {e}")

    st.markdown("---")
    st.markdown("#### �� Deactivate")
    if st.button("🗑 Deactivate this module",
                  key=f"deact_{slug}", type="secondary"):
        deactivate_module(slug)
        st.success("Deactivated")
        st.rerun()
