"""
Mobile-Optimized UI Components for Eagle 3D
Provides reusable touch-friendly widgets
"""

import streamlit as st
import pandas as pd


def render_kpi_card(label: str, value, delta: str = None, delta_positive: bool = True, icon: str = ""):
    """Render a responsive KPI card."""
    delta_html = ""
    if delta:
        delta_class = "kpi-up" if delta_positive else "kpi-dn"
        delta_html = f'<div class="{delta_class}">{delta}</div>'

    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-number">{icon} {value}</div>
        <div class="kpi-label">{label}</div>
        {delta_html}
    </div>
    """, unsafe_allow_html=True)


def render_kpi_grid(metrics: list):
    """
    Render KPI cards in a responsive grid.
    metrics = [{"label": str, "value": any, "delta": str, "delta_positive": bool, "icon": str}, ...]
    """
    n = len(metrics)
    cols = st.columns(min(n, 4))
    for i, m in enumerate(metrics):
        with cols[i % len(cols)]:
            render_kpi_card(
                label=m.get("label", ""),
                value=m.get("value", "—"),
                delta=m.get("delta"),
                delta_positive=m.get("delta_positive", True),
                icon=m.get("icon", ""),
            )


def render_alert(severity: str, title: str, message: str, recommendation: str = "", emoji: str = ""):
    """Render a styled alert card."""
    sev_class = {
        "critical": "alert-critical",
        "warning":  "alert-warning",
        "positive": "alert-positive",
        "info":     "alert-info",
    }.get(severity, "alert-info")

    rec_html = f'<div class="alert-rec">💡 {recommendation}</div>' if recommendation else ""

    st.markdown(f"""
    <div class="{sev_class}">
        <div class="alert-title">{emoji} {title}</div>
        <div class="alert-msg">{message}</div>
        {rec_html}
    </div>
    """, unsafe_allow_html=True)


def render_badge(text: str, intent: str = "medium"):
    """Render an intent badge."""
    badge_class = f"badge-{intent}"
    return f'<span class="{badge_class}">{text}</span>'


def render_info_card(content: str):
    """Render a styled info card."""
    st.markdown(f"""
    <div class="info-card">
        {content}
    </div>
    """, unsafe_allow_html=True)


def render_section_header(title: str, subtitle: str = ""):
    """Render a section header with optional subtitle."""
    html = f'<div class="sec-head">{title}</div>'
    if subtitle:
        html += f'<div class="helper-text" style="margin-top: -8px; margin-bottom: 12px;">{subtitle}</div>'
    st.markdown(html, unsafe_allow_html=True)


def render_mobile_table(df: pd.DataFrame, key_col: str = None, max_rows: int = 100):
    """
    Render a table that's mobile-friendly.
    On mobile, falls back to card-style display.
    On desktop, shows full table.
    """
    if df is None or df.empty:
        st.info("No data to display")
        return

    df = df.head(max_rows)

    # Use Streamlit's native dataframe (it has horizontal scroll built-in)
    st.dataframe(
        df,
        use_container_width=True,
        height=min(40 + len(df) * 35, 500),
    )


def render_responsive_columns(num_cols: int, force_stack_on_mobile: bool = True):
    """
    Create responsive columns that stack on mobile.
    Returns a list of column containers.
    """
    # Streamlit handles this via CSS in our responsive module
    # Just create the columns and let CSS handle mobile layout
    return st.columns(num_cols)


def render_hero_header(title: str, subtitle: str = "", icon: str = "🚦"):
    """Render the main page hero header."""
    st.markdown(f"""
    <div class="tih-header">
        <h1>{icon} {title}</h1>
        {f'<p>{subtitle}</p>' if subtitle else ''}
    </div>
    """, unsafe_allow_html=True)


def render_compact_metric(label: str, value, delta: str = None):
    """Render a compact metric (smaller than KPI card)."""
    delta_html = f'<span style="color: var(--e3d-text-muted); font-size: 0.75rem; margin-left: 8px;">{delta}</span>' if delta else ""
    st.markdown(f"""
    <div style="background: var(--e3d-card-light); padding: 10px 14px; border-radius: 8px; margin: 4px 0;">
        <span style="color: var(--e3d-text-muted); font-size: 0.8rem;">{label}</span><br>
        <span style="color: var(--e3d-accent); font-size: 1.1rem; font-weight: 700;">{value}</span>
        {delta_html}
    </div>
    """, unsafe_allow_html=True)


def render_action_button(label: str, key: str, primary: bool = False, icon: str = ""):
    """Render a touch-friendly action button."""
    btn_type = "primary" if primary else "secondary"
    full_label = f"{icon} {label}" if icon else label
    return st.button(full_label, key=key, type=btn_type, use_container_width=True)


def render_empty_state(title: str, message: str, action_label: str = None, action_key: str = None):
    """Render an empty state when no data is available."""
    st.markdown(f"""
    <div style="text-align: center; padding: 40px 20px; background: var(--e3d-card-light); border-radius: 12px; margin: 20px 0;">
        <div style="font-size: 3rem; margin-bottom: 16px;">📭</div>
        <h3 style="color: var(--e3d-text); font-size: 1.1rem; margin: 0;">{title}</h3>
        <p style="color: var(--e3d-text-muted); font-size: 0.9rem; margin: 8px 0 16px 0;">{message}</p>
    </div>
    """, unsafe_allow_html=True)

    if action_label and action_key:
        return st.button(action_label, key=action_key, type="primary")
    return None


def render_loading_skeleton(rows: int = 3):
    """Render skeleton placeholders while data loads."""
    for _ in range(rows):
        st.markdown("""
        <div style="background: linear-gradient(90deg, #1E3A5F 0%, #2a4a70 50%, #1E3A5F 100%);
                    background-size: 200% 100%;
                    animation: skeleton-loading 1.5s ease-in-out infinite;
                    height: 80px; border-radius: 12px; margin: 8px 0;">
        </div>
        <style>
        @keyframes skeleton-loading {
            0% { background-position: -200% 0; }
            100% { background-position: 200% 0; }
        }
        </style>
        """, unsafe_allow_html=True)


def render_mobile_nav_hint():
    """Show a hint on mobile to swipe tabs."""
    st.markdown("""
    <div class="helper-text" style="text-align: center; margin: 8px 0;">
        💡 Swipe tabs horizontally → to see more
    </div>
    """, unsafe_allow_html=True)

