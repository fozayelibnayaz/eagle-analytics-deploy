"""
period_picker_shared.py — Unified date-period picker for all pages.
Every page uses this so date presets are consistent.
"""
from datetime import date, timedelta
from typing import Tuple

import streamlit as st

from period_engine import PRESETS, _resolve_preset


def render_period_picker(key_prefix: str = "period",
                          default: str = "This Month"
                          ) -> Tuple[str, str, str]:
    """
    Render a unified period picker.
    Returns: (start_iso, end_iso, label)
    """
    # Session key so each page keeps its own selection
    sess_key = f"{key_prefix}_selection"

    if sess_key not in st.session_state:
        st.session_state[sess_key] = default

    idx = PRESETS.index(st.session_state[sess_key]) if st.session_state[sess_key] in PRESETS else PRESETS.index(default)

    preset = st.selectbox(
        "📅 Period",
        PRESETS,
        index=idx,
        key=f"{key_prefix}_preset",
    )
    st.session_state[sess_key] = preset

    # Custom range inputs
    custom_start = None
    custom_end = None
    if preset == "Custom Range":
        c1, c2 = st.columns(2)
        with c1:
            custom_start = st.date_input(
                "Start",
                value=st.session_state.get(f"{key_prefix}_cs",
                                             date.today() - timedelta(days=29)),
                key=f"{key_prefix}_cs",
            )
        with c2:
            custom_end = st.date_input(
                "End",
                value=st.session_state.get(f"{key_prefix}_ce", date.today()),
                key=f"{key_prefix}_ce",
            )

    start, end = _resolve_preset(preset, custom_start, custom_end)
    return start.isoformat(), end.isoformat(), preset
