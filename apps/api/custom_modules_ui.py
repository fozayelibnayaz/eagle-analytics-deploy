
"""
Custom Team Modules UI.
"""
from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.express as px

from custom_modules_engine import (
    list_modules,
    get_module,
    create_module,
    deactivate_module,
    read_uploaded_file,
    ingest_dataframe,
    get_module_df,
    summarize_dataframe,
    generate_auto_insights,
    slugify,
)


def render_custom_module_settings():
    st.markdown("### 🧩 Custom Team Modules")
    st.caption("Create new sidebar tabs for any team by uploading a sheet. Data is stored in MongoDB.")

    with st.expander("➕ Create New Module", expanded=False):
        name = st.text_input("Module name", placeholder="Example: HR Recruiting, Finance, Sales Pipeline", key="cm_name")
        team = st.text_input("Team / owner", placeholder="Example: HR", key="cm_team")
        description = st.text_area("Description", placeholder="What is this module for?", key="cm_desc")
        requested = st.text_area(
            "What analysis should this module provide?",
            placeholder="Example: Track applicants by stage, source, recruiter, time to hire, rejected reasons.",
            key="cm_requested",
        )

        if st.button("✅ Create Module", type="primary", key="cm_create"):
            result = create_module(name, description, team, requested)
            if result.get("success"):
                st.success(result["message"])
                st.rerun()
            else:
                st.error(result.get("message", "Failed to create module"))

    modules = list_modules(active_only=True)

    if not modules:
        st.info("No custom modules yet. Create one above.")
        return

    st.markdown("#### Existing Modules")

    for mod in modules:
        with st.expander(f"🧩 {mod.get('name')} — {mod.get('row_count', 0)} rows", expanded=False):
            st.write(mod.get("description", ""))
            st.caption(f"Slug: `{mod.get('slug')}` | Collection: `{mod.get('collection')}`")

            uploaded = st.file_uploader(
                f"Upload CSV/XLSX for {mod.get('name')}",
                type=["csv", "xlsx", "xls"],
                key=f"cm_upload_{mod.get('slug')}",
            )

            replace = st.checkbox("Replace existing rows", value=True, key=f"cm_replace_{mod.get('slug')}")

            if uploaded is not None:
                try:
                    df = read_uploaded_file(uploaded)
                    st.dataframe(df.head(20), use_container_width=True)

                    if st.button("📥 Import to MongoDB", key=f"cm_import_{mod.get('slug')}", type="primary"):
                        result = ingest_dataframe(mod.get("slug"), df, replace=replace)
                        if result.get("success"):
                            st.success(result["message"])
                            st.rerun()
                        else:
                            st.error(result.get("message", "Import failed"))
                except Exception as e:
                    st.error(f"Upload error: {e}")

            if st.button("🚫 Deactivate Module", key=f"cm_deactivate_{mod.get('slug')}"):
                result = deactivate_module(mod.get("slug"))
                if result.get("success"):
                    st.success(result["message"])
                    st.rerun()
                else:
                    st.error(result.get("message", "Failed"))


def render_custom_module_page(slug: str):
    slug = slugify(slug)
    mod = get_module(slug)

    if not mod:
        st.error(f"Custom module not found: {slug}")
        return

    st.markdown(f"### 🧩 {mod.get('name', slug)}")
    st.caption(mod.get("description", ""))

    df = get_module_df(slug)

    if df.empty:
        st.info("No data uploaded yet. Go to Settings → Custom Team Modules and upload a CSV/XLSX.")
        return

    summary = summarize_dataframe(df)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows", f"{summary['rows']:,}")
    c2.metric("Columns", f"{summary['columns']:,}")
    c3.metric("Numeric Columns", len(summary["numeric_columns"]))
    c4.metric("Missing Cells", f"{summary['missing_cells']:,}")

    st.markdown("#### 🤖 Auto Insights")
    for insight in generate_auto_insights(df, mod.get("requested_analysis", "")):
        st.write(f"- {insight}")

    st.markdown("#### 📊 Auto Charts")

    numeric_cols = summary["numeric_columns"]
    date_cols = summary["date_columns"]
    text_cols = summary["text_columns"]

    if numeric_cols:
        selected_num = st.selectbox("Numeric metric", numeric_cols, key=f"cm_num_{slug}")

        if date_cols:
            selected_date = st.selectbox("Date column", date_cols, key=f"cm_date_{slug}")
            chart_df = df.copy()
            chart_df[selected_date] = pd.to_datetime(chart_df[selected_date], errors="coerce")
            chart_df[selected_num] = pd.to_numeric(chart_df[selected_num], errors="coerce")
            chart_df = chart_df.dropna(subset=[selected_date])
            if not chart_df.empty:
                daily = chart_df.groupby(chart_df[selected_date].dt.date)[selected_num].sum().reset_index()
                daily.columns = ["date", selected_num]
                fig = px.line(daily, x="date", y=selected_num, markers=True)
                st.plotly_chart(fig, use_container_width=True)

        if text_cols:
            selected_cat = st.selectbox("Breakdown category", text_cols, key=f"cm_cat_{slug}")
            chart_df = df.copy()
            chart_df[selected_num] = pd.to_numeric(chart_df[selected_num], errors="coerce")
            grouped = chart_df.groupby(selected_cat)[selected_num].sum().sort_values(ascending=False).head(20).reset_index()
            if not grouped.empty:
                fig = px.bar(grouped, x=selected_cat, y=selected_num)
                fig.update_layout(xaxis_tickangle=-45)
                st.plotly_chart(fig, use_container_width=True)

    elif text_cols:
        selected_cat = st.selectbox("Category", text_cols, key=f"cm_cat_only_{slug}")
        counts = df[selected_cat].astype(str).value_counts().head(20).reset_index()
        counts.columns = [selected_cat, "count"]
        fig = px.bar(counts, x=selected_cat, y="count")
        fig.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### 🔍 Data Browser")
    search = st.text_input("Search", key=f"cm_search_{slug}")

    view = df.copy()
    if search:
        mask = pd.Series([False] * len(view), index=view.index)
        for c in view.columns:
            mask = mask | view[c].astype(str).str.contains(search, case=False, na=False)
        view = view[mask]

    st.dataframe(view.head(1000), use_container_width=True, height=500)

    csv = view.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download filtered CSV",
        data=csv,
        file_name=f"{slug}.csv",
        mime="text/csv",
        use_container_width=True,
    )
