"""
period_engine.py — Eagle 3D Streaming Analytics Hub
=====================================================
Global period + comparison state.
Now supports MANY comparison combinations.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, timedelta
from typing import Optional, Tuple

import streamlit as st


# ─── Preset periods ──────────────────────────────────────────────
PRESETS = [
    "Today",
    "Yesterday",
    "This Week",
    "Last 7 Days",
    "Last 14 Days",
    "Last 15 Days",
    "Last 28 Days",
    "Last 30 Days",
    "This Month",
    "Last Month",
    "Last 3 Months",
    "Last 6 Months",
    "Last 12 Months",
    "This Quarter",
    "Last Quarter",
    "This Year",
    "Last Year",
    "All Time",
    "Custom Range",
]

# ─── Comparison modes (10 combinations) ──────────────────────────
COMPARE_MODES = [
    "Off",
    "Previous Period",
    "Same Period Last Year",
    "Same Period Last Month",
    "vs This Week",
    "vs Last Week",
    "vs This Month",
    "vs Last Month",
    "vs This Quarter",
    "vs Last Quarter",
    "vs This Year",
    "vs Last Year",
    "vs Custom Range",
]

DEFAULT_PRESET  = "This Month"
DEFAULT_COMPARE = "Off"


# ─── Period dataclass ────────────────────────────────────────────
@dataclass
class Period:
    label:  str
    start:  date
    end:    date
    days:   int
    compare_enabled: bool
    compare_mode:    str
    compare_start:   Optional[date]
    compare_end:     Optional[date]
    compare_label:   str

    def start_iso(self) -> str: return self.start.isoformat()
    def end_iso(self)   -> str: return self.end.isoformat()
    def compare_start_iso(self) -> Optional[str]:
        return self.compare_start.isoformat() if self.compare_start else None
    def compare_end_iso(self) -> Optional[str]:
        return self.compare_end.isoformat() if self.compare_end else None


# ─── Helpers ─────────────────────────────────────────────────────
# Enforce 6-month max history (uploads only have 6mo of data)
ALL_TIME_MAX_DAYS = 180


def _all_time_start() -> date:
    """All Time = last 180 days (6 months) — matches upload data horizon."""
    return date.today() - timedelta(days=ALL_TIME_MAX_DAYS - 1)


def _quarter_start(d: date) -> date:
    q = (d.month - 1) // 3
    return date(d.year, q * 3 + 1, 1)


def _quarter_end(d: date) -> date:
    q = (d.month - 1) // 3
    if q < 3:
        return date(d.year, (q + 1) * 3 + 1, 1) - timedelta(days=1)
    return date(d.year, 12, 31)


def _last_day_of_month(y: int, m: int) -> int:
    if m == 12:
        return 31
    return (date(y, m + 1, 1) - timedelta(days=1)).day


def _shift_month(d: date, months: int) -> date:
    """Shift a date by N months, clamping day to month length."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, _last_day_of_month(y, m))
    return date(y, m, day)


# ─── Resolve preset to date range ────────────────────────────────
def _resolve_preset(preset: str,
                    custom_start: Optional[date] = None,
                    custom_end:   Optional[date] = None
                    ) -> Tuple[date, date]:
    today = date.today()

    if preset == "Today":            return (today, today)
    if preset == "Yesterday":
        y = today - timedelta(days=1); return (y, y)
    if preset == "This Week":
        return (today - timedelta(days=today.weekday()), today)
    if preset == "Last 7 Days":      return (today - timedelta(days=6),  today)
    if preset == "Last 14 Days":     return (today - timedelta(days=13), today)
    if preset == "Last 15 Days":     return (today - timedelta(days=14), today)
    if preset == "Last 28 Days":     return (today - timedelta(days=27), today)
    if preset == "Last 30 Days":     return (today - timedelta(days=29), today)

    if preset == "This Month":
        return (today.replace(day=1), today)
    if preset == "Last Month":
        first_this = today.replace(day=1)
        last_prev  = first_this - timedelta(days=1)
        return (last_prev.replace(day=1), last_prev)

    if preset == "Last 3 Months":    return (today - timedelta(days=89),  today)
    if preset == "Last 6 Months":    return (today - timedelta(days=179), today)
    if preset == "Last 12 Months":   return (today - timedelta(days=364), today)

    if preset == "This Quarter":     return (_quarter_start(today), today)
    if preset == "Last Quarter":
        first_this_q = _quarter_start(today)
        last_prev_q  = first_this_q - timedelta(days=1)
        return (_quarter_start(last_prev_q), last_prev_q)

    if preset == "This Year":
        return (today.replace(month=1, day=1), today)
    if preset == "Last Year":
        return (date(today.year - 1, 1, 1), date(today.year - 1, 12, 31))

    if preset == "All Time":
        return (_all_time_start(), today)

    if preset == "Custom Range":
        s = custom_start or (today - timedelta(days=29))
        e = custom_end   or today
        if e < s: s, e = e, s
        return (s, e)

    return (today - timedelta(days=29), today)


# ─── Resolve compare mode to range ───────────────────────────────
def _compute_compare(start: date, end: date, mode: str,
                     custom_cs: Optional[date] = None,
                     custom_ce: Optional[date] = None
                     ) -> Tuple[Optional[date], Optional[date], str]:
    """Return (compare_start, compare_end, human_label)."""
    if mode == "Off":
        return (None, None, "")

    span_days = (end - start).days + 1
    today = date.today()

    if mode == "Previous Period":
        c_end   = start - timedelta(days=1)
        c_start = c_end - timedelta(days=span_days - 1)
        return (c_start, c_end,
                f"Prev period ({c_start.isoformat()} → {c_end.isoformat()})")

    if mode == "Same Period Last Year":
        try:
            c_start = date(start.year - 1, start.month, min(start.day, _last_day_of_month(start.year - 1, start.month)))
            c_end   = date(end.year - 1,   end.month,   min(end.day,   _last_day_of_month(end.year - 1,   end.month)))
        except Exception:
            c_start = start - timedelta(days=365)
            c_end   = end   - timedelta(days=365)
        return (c_start, c_end,
                f"Last year ({c_start.isoformat()} → {c_end.isoformat()})")

    if mode == "Same Period Last Month":
        # Shift both dates back by 1 month, keep same day
        c_start = _shift_month(start, -1)
        c_end   = _shift_month(end,   -1)
        # If new end > actual (e.g. period is future part of month), cap
        return (c_start, c_end,
                f"Last month same period ({c_start.isoformat()} → {c_end.isoformat()})")

    # ── Fixed absolute comparisons ──
    if mode == "vs This Week":
        cs = today - timedelta(days=today.weekday())
        return (cs, today, f"This week ({cs.isoformat()} → {today.isoformat()})")

    if mode == "vs Last Week":
        this_mon = today - timedelta(days=today.weekday())
        last_sun = this_mon - timedelta(days=1)
        last_mon = last_sun - timedelta(days=6)
        return (last_mon, last_sun, f"Last week ({last_mon.isoformat()} → {last_sun.isoformat()})")

    if mode == "vs This Month":
        cs = today.replace(day=1)
        return (cs, today, f"This month ({cs.isoformat()} → {today.isoformat()})")

    if mode == "vs Last Month":
        first_this = today.replace(day=1)
        last_prev  = first_this - timedelta(days=1)
        cs = last_prev.replace(day=1)
        return (cs, last_prev, f"Last month ({cs.isoformat()} → {last_prev.isoformat()})")

    if mode == "vs This Quarter":
        cs = _quarter_start(today)
        return (cs, today, f"This quarter ({cs.isoformat()} → {today.isoformat()})")

    if mode == "vs Last Quarter":
        this_q_start = _quarter_start(today)
        last_q_end   = this_q_start - timedelta(days=1)
        cs = _quarter_start(last_q_end)
        return (cs, last_q_end, f"Last quarter ({cs.isoformat()} → {last_q_end.isoformat()})")

    if mode == "vs This Year":
        cs = today.replace(month=1, day=1)
        return (cs, today, f"This year ({cs.isoformat()} → {today.isoformat()})")

    if mode == "vs Last Year":
        cs = date(today.year - 1, 1, 1)
        ce = date(today.year - 1, 12, 31)
        return (cs, ce, f"Last year ({cs.isoformat()} → {ce.isoformat()})")

    if mode == "vs Custom Range":
        cs = custom_cs
        ce = custom_ce
        if cs and ce:
            if ce < cs: cs, ce = ce, cs
            return (cs, ce, f"Custom compare ({cs.isoformat()} → {ce.isoformat()})")
        return (None, None, "Custom range not set")

    return (None, None, "")


# ─── Public API ──────────────────────────────────────────────────
def get_period() -> Period:
    preset = st.session_state.get("period_preset", DEFAULT_PRESET)
    if preset not in PRESETS:
        preset = DEFAULT_PRESET

    cs = st.session_state.get("period_custom_start")
    ce = st.session_state.get("period_custom_end")
    if isinstance(cs, str):
        try: cs = date.fromisoformat(cs)
        except: cs = None
    if isinstance(ce, str):
        try: ce = date.fromisoformat(ce)
        except: ce = None

    start, end = _resolve_preset(preset, cs, ce)

    compare_mode = st.session_state.get("period_compare", DEFAULT_COMPARE)
    if compare_mode not in COMPARE_MODES:
        compare_mode = DEFAULT_COMPARE

    # Compare custom range
    ccs = st.session_state.get("period_compare_custom_start")
    cce = st.session_state.get("period_compare_custom_end")
    if isinstance(ccs, str):
        try: ccs = date.fromisoformat(ccs)
        except: ccs = None
    if isinstance(cce, str):
        try: cce = date.fromisoformat(cce)
        except: cce = None

    c_start, c_end, c_label = _compute_compare(start, end, compare_mode, ccs, cce)

    return Period(
        label            = preset,
        start            = start,
        end              = end,
        days             = (end - start).days + 1,
        compare_enabled  = compare_mode != "Off",
        compare_mode     = compare_mode,
        compare_start    = c_start,
        compare_end      = c_end,
        compare_label    = c_label,
    )


def set_period(**kwargs) -> None:
    m = {
        "preset":               "period_preset",
        "compare":              "period_compare",
        "custom_start":         "period_custom_start",
        "custom_end":           "period_custom_end",
        "compare_custom_start": "period_compare_custom_start",
        "compare_custom_end":   "period_compare_custom_end",
    }
    for k, v in kwargs.items():
        if v is not None and k in m:
            st.session_state[m[k]] = v


def reset_period() -> None:
    for k in ("period_preset", "period_compare",
              "period_custom_start", "period_custom_end",
              "period_compare_custom_start", "period_compare_custom_end"):
        st.session_state.pop(k, None)


# ─── Compact label for navbar button ─────────────────────────────
def get_period_button_label() -> str:
    p = get_period()
    short_map = {
        "Today":          "Today",
        "Yesterday":      "1d",
        "This Week":      "WTD",
        "Last 7 Days":    "7d",
        "Last 14 Days":   "14d",
        "Last 15 Days":   "15d",
        "Last 28 Days":   "28d",
        "Last 30 Days":   "30d",
        "This Month":     "MTD",
        "Last Month":     "Last mo",
        "Last 3 Months":  "3mo",
        "Last 6 Months":  "6mo",
        "Last 12 Months": "12mo",
        "This Quarter":   "QTD",
        "Last Quarter":   "Last Q",
        "This Year":      "YTD",
        "Last Year":      "LY",
        "All Time":       "All",
        "Custom Range":   "Custom",
    }
    return short_map.get(p.label, p.label)


# ─── Period picker UI ────────────────────────────────────────────
def render_period_picker(key_prefix: str = "period_picker") -> None:
    from datetime import timedelta as _td

    current_preset  = st.session_state.get("period_preset",  DEFAULT_PRESET)
    current_compare = st.session_state.get("period_compare", DEFAULT_COMPARE)

    # Preset
    new_preset = st.selectbox(
        "📅 Period",
        PRESETS,
        index=PRESETS.index(current_preset) if current_preset in PRESETS else 0,
        key=f"{key_prefix}_preset",
    )
    if new_preset != current_preset:
        st.session_state["period_preset"] = new_preset
        st.rerun()

    if new_preset == "Custom Range":
        col1, col2 = st.columns(2)
        with col1:
            cs = st.date_input(
                "Start",
                value=st.session_state.get(
                    "period_custom_start",
                    date.today() - _td(days=29),
                ),
                key=f"{key_prefix}_cs",
            )
        with col2:
            ce = st.date_input(
                "End",
                value=st.session_state.get("period_custom_end", date.today()),
                key=f"{key_prefix}_ce",
            )
        st.session_state["period_custom_start"] = cs
        st.session_state["period_custom_end"]   = ce

    st.markdown("---")

    # Comparison
    new_compare = st.selectbox(
        "🔄 Comparison",
        COMPARE_MODES,
        index=COMPARE_MODES.index(current_compare) if current_compare in COMPARE_MODES else 0,
        key=f"{key_prefix}_cmp",
        help=(
            "Off = no comparison\n\n"
            "Previous Period = span before selected period\n\n"
            "Same Period Last Year/Month = shift back keeping day\n\n"
            "vs This/Last Week/Month/Quarter/Year = fixed absolute ranges\n\n"
            "vs Custom Range = pick any two dates"
        ),
    )
    if new_compare != current_compare:
        st.session_state["period_compare"] = new_compare
        st.rerun()

    if new_compare == "vs Custom Range":
        col1, col2 = st.columns(2)
        with col1:
            ccs = st.date_input(
                "Compare start",
                value=st.session_state.get(
                    "period_compare_custom_start",
                    date.today() - _td(days=59),
                ),
                key=f"{key_prefix}_ccs",
            )
        with col2:
            cce = st.date_input(
                "Compare end",
                value=st.session_state.get(
                    "period_compare_custom_end",
                    date.today() - _td(days=30),
                ),
                key=f"{key_prefix}_cce",
            )
        st.session_state["period_compare_custom_start"] = ccs
        st.session_state["period_compare_custom_end"]   = cce

    # Preview
    p = get_period()
    st.markdown("---")
    st.caption(f"**{p.label}** — {p.start_iso()} → {p.end_iso()} ({p.days} days)")
    if p.compare_enabled:
        st.caption(f"↔ **{p.compare_label}**")


# ─── CLI test ────────────────────────────────────────────────────
if __name__ == "__main__":
    for preset in PRESETS:
        s, e = _resolve_preset(preset, date(2024, 6, 1), date(2024, 6, 30))
        print(f"  {preset:20s} → {s} → {e}  ({(e-s).days + 1} days)")
    print()
    print("Compare modes:", len(COMPARE_MODES))
    for m in COMPARE_MODES:
        cs, ce, lbl = _compute_compare(date(2026, 6, 1), date(2026, 6, 30), m,
                                        date(2025, 1, 1), date(2025, 3, 31))
        print(f"  {m:28s} → {cs} → {ce}  | {lbl}")
