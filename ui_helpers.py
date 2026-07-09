"""
ui_helpers.py — Eagle 3D Streaming Analytics Hub
==================================================
Reusable UI primitives: skeletons, toasts, empty states, error boundaries.
Import these in every page for consistent premium look.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Optional

import streamlit as st


# ─── Loading skeletons ───────────────────────────────────────────
def skeleton_metric_row(count: int = 4) -> None:
    """Show shimmering placeholder for metric cards while loading."""
    cols = st.columns(count)
    for c in cols:
        with c:
            st.markdown(
                """
                <div class="e3-skeleton-card">
                  <div class="e3-skeleton-line" style="width:40%;height:12px;"></div>
                  <div class="e3-skeleton-line" style="width:60%;height:28px;margin-top:12px;"></div>
                  <div class="e3-skeleton-line" style="width:30%;height:10px;margin-top:8px;"></div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def skeleton_chart(height: int = 300) -> None:
    st.markdown(
        f"""
        <div class="e3-skeleton-card" style="height:{height}px;padding:24px;">
          <div class="e3-skeleton-line" style="width:30%;height:14px;margin-bottom:20px;"></div>
          <div style="display:flex;align-items:flex-end;height:{height-80}px;gap:8px;">
            <div class="e3-skeleton-bar" style="height:40%;"></div>
            <div class="e3-skeleton-bar" style="height:70%;"></div>
            <div class="e3-skeleton-bar" style="height:55%;"></div>
            <div class="e3-skeleton-bar" style="height:85%;"></div>
            <div class="e3-skeleton-bar" style="height:60%;"></div>
            <div class="e3-skeleton-bar" style="height:75%;"></div>
            <div class="e3-skeleton-bar" style="height:45%;"></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def skeleton_table(rows: int = 5) -> None:
    row_html = "".join(
        f'<div class="e3-skeleton-line" style="width:{95-i*3}%;height:14px;margin-bottom:12px;"></div>'
        for i in range(rows)
    )
    st.markdown(
        f'<div class="e3-skeleton-card" style="padding:20px;">{row_html}</div>',
        unsafe_allow_html=True,
    )


# ─── Empty states with helpful CTAs ──────────────────────────────
def empty_state(
    title: str,
    subtitle: str = "",
    icon: str = "📭",
    action_label: Optional[str] = None,
    action_url: Optional[str] = None,
    action_callback: Optional[Callable] = None,
) -> None:
    """Premium empty state with optional CTA."""
    st.markdown(
        f"""
        <div class="e3-empty-state">
          <div class="e3-empty-icon">{icon}</div>
          <div class="e3-empty-title">{title}</div>
          {f'<div class="e3-empty-sub">{subtitle}</div>' if subtitle else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )
    if action_label and action_url:
        st.markdown(
            f'<div style="text-align:center;margin-top:-40px;margin-bottom:24px;">'
            f'<a href="{action_url}" target="_top" '
            f'style="display:inline-block;padding:10px 24px;border-radius:999px;'
            f'background:linear-gradient(135deg,#9EFF2F,#5EF46A);color:#000;'
            f'font-weight:600;text-decoration:none;font-size:13px;">'
            f'{action_label}</a></div>',
            unsafe_allow_html=True,
        )
    elif action_label and action_callback:
        col1, col2, col3 = st.columns([2, 1, 2])
        with col2:
            if st.button(action_label, key=f"empty_cta_{title[:20]}", type="primary"):
                action_callback()


# ─── Toast notifications ─────────────────────────────────────────
def toast_success(msg: str) -> None:
    try:
        st.toast(msg, icon="✅")
    except Exception:
        st.success(msg)


def toast_error(msg: str) -> None:
    try:
        st.toast(msg, icon="❌")
    except Exception:
        st.error(msg)


def toast_info(msg: str) -> None:
    try:
        st.toast(msg, icon="ℹ️")
    except Exception:
        st.info(msg)


# ─── Error boundary decorator ────────────────────────────────────
@contextmanager
def page_error_boundary(page_name: str):
    """Wrap a page render to catch + display errors without killing the app."""
    try:
        yield
    except Exception as e:
        import traceback
        st.markdown(
            f"""
            <div class="e3-empty-state" style="border-color:rgba(239,68,68,0.3);">
              <div class="e3-empty-icon">⚠️</div>
              <div class="e3-empty-title">Something broke on the {page_name} page</div>
              <div class="e3-empty-sub">Error: {str(e)[:200]}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.expander("🐛 Full traceback (for devs)"):
            st.code(traceback.format_exc(), language="python")


# ─── Animated number counter ─────────────────────────────────────
def animated_number(
    value: float,
    label: str = "",
    prefix: str = "",
    suffix: str = "",
    decimals: int = 0,
    color: str = "#fff",
    duration_ms: int = 1200,
) -> None:
    """
    Renders a large number that counts up from 0 on page load.
    Uses vanilla JS via components.html.
    """
    import streamlit.components.v1 as components
    formatted_val = f"{value:,.{decimals}f}" if decimals else f"{int(value):,}"

    key_id = f"ac_{hash(f'{label}_{value}') & 0xFFFF}"
    components.html(
        f"""
        <div style="font-family:'Inter',sans-serif;color:{color};text-align:left;">
          <div style="font-size:14px;color:#9CA3AF;font-weight:500;
                      text-transform:uppercase;letter-spacing:0.06em;margin-bottom:8px;">
            {label}
          </div>
          <div id="{key_id}" style="font-size:56px;font-weight:700;
                                    letter-spacing:-0.03em;line-height:1;color:{color};">
            {prefix}0{suffix}
          </div>
        </div>
        <script>
        (function() {{
          const el = document.getElementById('{key_id}');
          if (!el) return;
          const target = {value};
          const dur = {duration_ms};
          const start = performance.now();
          const decimals = {decimals};
          function tick(now) {{
            const t = Math.min((now - start) / dur, 1);
            const eased = 1 - Math.pow(1 - t, 3);
            const val = target * eased;
            const formatted = decimals > 0
              ? val.toFixed(decimals)
              : Math.floor(val).toString();
            el.textContent = '{prefix}' + Number(formatted).toLocaleString() + '{suffix}';
            if (t < 1) requestAnimationFrame(tick);
          }}
          requestAnimationFrame(tick);
        }})();
        </script>
        """,
        height=110,
    )


# ─── Wallet-style gradient card ──────────────────────────────────
def wallet_card(
    title: str,
    balance: float,
    subtitle: str = "",
    prefix: str = "$",
    holder: str = "",
    chip_color: str = "#d4a017",
) -> None:
    """Premium Visa-style wallet card with gradient + shine."""
    balance_str = f"{prefix}{balance:,.2f}"
    st.markdown(
        f"""
        <div class="e3-wallet-card-v2">
          <div class="e3-wallet-shine"></div>
          <div class="e3-wallet-top">
            <div style="color:rgba(255,255,255,0.6);font-size:11px;
                        letter-spacing:0.15em;text-transform:uppercase;">
              {title}
            </div>
            <div class="e3-wallet-chip" style="background:linear-gradient(135deg,{chip_color},#a37a10);"></div>
          </div>
          <div class="e3-wallet-balance">{balance_str}</div>
          <div class="e3-wallet-subtitle">{subtitle}</div>
          <div class="e3-wallet-bottom">
            <div>
              <div class="e3-wallet-holder-label">Holder</div>
              <div class="e3-wallet-holder-name">{holder or "EAGLE 3D STREAMING"}</div>
            </div>
            <div class="e3-wallet-brand">
              <div class="e3-wallet-brand-dot" style="background:#9EFF2F;"></div>
              <div class="e3-wallet-brand-dot" style="background:#5EF46A;margin-left:-10px;opacity:0.7;"></div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ─── Right-side quick actions panel ──────────────────────────────
def quick_actions_panel(actions: list) -> None:
    """
    Render a right-side sticky panel with quick action buttons.
    actions = [{"icon": "📥", "label": "Export", "href": "?..."}, ...]
    """
    html = '<div class="e3-quick-actions">'
    html += '<div class="e3-quick-title">Quick Actions</div>'
    for a in actions:
        icon = a.get("icon", "•")
        label = a.get("label", "")
        href = a.get("href", "#")
        html += (
            f'<a class="e3-quick-btn" href="{href}" target="_top">'
            f'<span class="e3-quick-icon">{icon}</span>'
            f'<span class="e3-quick-label">{label}</span>'
            f'</a>'
        )
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)


# ─── Live activity feed ──────────────────────────────────────────
def activity_feed(events: list, title: str = "Recent Activity", max_show: int = 8) -> None:
    """
    events = [{"icon": "👥", "text": "New signup: x@y.com", "when": "2m ago", "color": "#9EFF2F"}, ...]
    """
    if not events:
        empty_state("No recent activity", "New events will appear here", icon="🕰️")
        return

    st.markdown(f'<p class="e3-section-title">{title}</p>', unsafe_allow_html=True)

    items = ""
    for e in events[:max_show]:
        icon = e.get("icon", "•")
        text = e.get("text", "")
        when = e.get("when", "")
        color = e.get("color", "#9EFF2F")
        items += f"""
        <div class="e3-activity-item">
          <div class="e3-activity-dot" style="background:{color};box-shadow:0 0 12px {color}80;"></div>
          <div class="e3-activity-content">
            <div class="e3-activity-text">{icon} {text}</div>
            <div class="e3-activity-when">{when}</div>
          </div>
        </div>
        """
    st.markdown(f'<div class="e3-activity-feed">{items}</div>', unsafe_allow_html=True)
