"""
Mobile-First Responsive CSS for Eagle 3D Eagle Analytics Hub Hub
Provides world-class UX on mobile, tablet, and desktop
"""


def get_responsive_css() -> str:
    """Return complete CSS that makes the dashboard mobile-responsive."""
    return """
    <style>
    /* ═══════════════════════════════════════════════════════════ */
    /*  EAGLE 3D — MOBILE-FIRST RESPONSIVE DESIGN                 */
    /* ═══════════════════════════════════════════════════════════ */

    /* ── Color System ────────────────────────────────────────── */
    :root {
        --e3d-bg:           #0A1628;
        --e3d-card:         #1E3A5F;
        --e3d-card-light:   #162b45;
        --e3d-border:       #2a4a70;
        --e3d-accent:       #00D4FF;
        --e3d-green:        #00C896;
        --e3d-yellow:       #FFD700;
        --e3d-red:          #FF4B6E;
        --e3d-text:         #ffffff;
        --e3d-text-muted:   #a0b4cc;
        --e3d-text-faint:   #6b7d96;
    }

    /* ── BASE: Make everything touch-friendly ─────────────────── */
    .stApp {
        background: var(--e3d-bg);
    }

    /* All interactive elements minimum 44px (Apple HIG) */
    button, .stButton button, .stDownloadButton button,
    [role="button"], .stSelectbox, .stTextInput input,
    .stNumberInput input, .stTextArea textarea {
        min-height: 44px !important;
        font-size: 0.95rem !important;
    }

    /* ── HEADER (Hero Section) ────────────────────────────────── */
    .tih-header {
        background: linear-gradient(135deg, #1E3A5F 0%, #0A1628 100%);
        border-radius: 16px;
        padding: 20px;
        margin-bottom: 16px;
        border-left: 5px solid var(--e3d-accent);
    }
    .tih-header h1, .tih-header h2 {
        color: var(--e3d-accent);
        margin: 0;
        font-size: 1.5rem;
        line-height: 1.3;
        word-wrap: break-word;
    }
    .tih-header p {
        color: var(--e3d-text-muted);
        margin: 8px 0 0 0;
        font-size: 0.85rem;
        line-height: 1.5;
    }

    /* ── KPI CARDS (Responsive Grid) ──────────────────────────── */
    .kpi-card {
        background: linear-gradient(135deg, var(--e3d-card), var(--e3d-card-light));
        border-radius: 12px;
        padding: 16px;
        border: 1px solid var(--e3d-border);
        text-align: center;
        margin-bottom: 12px;
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    .kpi-card:hover, .kpi-card:active {
        transform: translateY(-2px);
        box-shadow: 0 4px 16px rgba(0, 212, 255, 0.2);
    }
    .kpi-number {
        font-size: 1.5rem;
        font-weight: 700;
        color: var(--e3d-accent);
        line-height: 1.2;
    }
    .kpi-label {
        font-size: 0.7rem;
        color: var(--e3d-text-muted);
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-top: 4px;
    }
    .kpi-up   { color: var(--e3d-green); font-size: 0.75rem; }
    .kpi-dn   { color: var(--e3d-red);   font-size: 0.75rem; }

    /* ── ALERTS (Touch-Optimized) ─────────────────────────────── */
    .alert-critical, .alert-warning, .alert-positive, .alert-info {
        border-radius: 10px;
        padding: 14px;
        margin: 10px 0;
        font-size: 0.9rem;
    }
    .alert-critical { background: #2d0a0a; border-left: 4px solid var(--e3d-red); }
    .alert-warning  { background: #2d1a00; border-left: 4px solid var(--e3d-yellow); }
    .alert-positive { background: #0a2d1a; border-left: 4px solid var(--e3d-green); }
    .alert-info     { background: #0a1a2d; border-left: 4px solid var(--e3d-accent); }
    .alert-title    { font-weight: 700; color: #fff; font-size: 0.95rem; }
    .alert-msg      { font-size: 0.85rem; color: #ccc; margin: 6px 0; }
    .alert-rec      { font-size: 0.8rem; color: #a0d4ff; font-style: italic; line-height: 1.5; }

    /* ── SECTION HEADERS ──────────────────────────────────────── */
    .sec-head {
        font-size: 1.1rem;
        font-weight: 700;
        color: var(--e3d-accent);
        border-bottom: 1px solid var(--e3d-card);
        padding-bottom: 8px;
        margin: 18px 0 14px 0;
    }

    /* ── TAB BAR (Horizontal scroll on mobile) ────────────────── */
    .stTabs [data-baseweb="tab-list"] {
        overflow-x: auto !important;
        flex-wrap: nowrap !important;
        scrollbar-width: thin;
        -webkit-overflow-scrolling: touch;
        gap: 4px;
        padding-bottom: 4px;
    }
    .stTabs [data-baseweb="tab-list"]::-webkit-scrollbar {
        height: 4px;
    }
    .stTabs [data-baseweb="tab-list"]::-webkit-scrollbar-thumb {
        background: var(--e3d-accent);
        border-radius: 2px;
    }
    .stTabs [data-baseweb="tab"] {
        flex-shrink: 0 !important;
        min-height: 44px !important;
        padding: 10px 16px !important;
        font-size: 0.9rem !important;
        white-space: nowrap !important;
    }

    /* ── DATAFRAMES (Mobile-friendly tables) ──────────────────── */
    .stDataFrame {
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch;
    }
    .stDataFrame table {
        font-size: 0.85rem !important;
    }

    /* ── FORMS (Larger inputs) ────────────────────────────────── */
    .stTextInput input, .stNumberInput input, .stTextArea textarea,
    .stSelectbox > div {
        font-size: 16px !important;  /* Prevents iOS zoom on focus */
        border-radius: 8px !important;
        padding: 12px 14px !important;
    }
    .stTextInput label, .stNumberInput label, .stSelectbox label,
    .stTextArea label, .stRadio label {
        font-size: 0.9rem !important;
        font-weight: 600 !important;
        color: var(--e3d-text-muted) !important;
    }

    /* ── BUTTONS (Touch-friendly) ─────────────────────────────── */
    .stButton button, .stDownloadButton button {
        min-height: 48px !important;
        font-weight: 600 !important;
        border-radius: 10px !important;
        padding: 12px 20px !important;
        font-size: 0.95rem !important;
        transition: all 0.15s ease;
    }
    .stButton button[kind="primary"] {
        background: var(--e3d-accent) !important;
        border: none !important;
    }
    .stButton button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(0, 212, 255, 0.3);
    }

    /* ── METRICS (Streamlit native) ───────────────────────────── */
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, var(--e3d-card), var(--e3d-card-light));
        padding: 16px;
        border-radius: 12px;
        border: 1px solid var(--e3d-border);
    }
    [data-testid="stMetricValue"] {
        font-size: 1.6rem !important;
        color: var(--e3d-accent) !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.75rem !important;
        color: var(--e3d-text-muted) !important;
    }

    /* ── SIDEBAR ──────────────────────────────────────────────── */
    [data-testid="stSidebar"] {
        background: var(--e3d-bg) !important;
        border-right: 1px solid var(--e3d-card);
    }
    [data-testid="stSidebar"] .stMarkdown h3 {
        color: var(--e3d-accent);
        font-size: 1rem;
    }

    /* ── EXPANDER ─────────────────────────────────────────────── */
    .streamlit-expanderHeader {
        background: var(--e3d-card-light) !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        min-height: 44px !important;
    }

    /* ── PROGRESS / SPINNERS ──────────────────────────────────── */
    .stSpinner > div {
        border-color: var(--e3d-accent) transparent var(--e3d-accent) transparent !important;
    }

    /* ═══════════════════════════════════════════════════════════ */
    /*  RESPONSIVE BREAKPOINTS                                    */
    /* ═══════════════════════════════════════════════════════════ */

    /* ── MOBILE: < 640px ──────────────────────────────────────── */
    @media (max-width: 640px) {

        /* Header smaller on mobile */
        .tih-header {
            padding: 16px;
            border-left-width: 4px;
            border-radius: 12px;
        }
        .tih-header h1, .tih-header h2 {
            font-size: 1.25rem !important;
        }
        .tih-header p {
            font-size: 0.8rem;
        }

        /* KPI cards: smaller text */
        .kpi-number { font-size: 1.4rem; }
        .kpi-label  { font-size: 0.65rem; }
        .kpi-card   { padding: 12px; }

        /* Section headers */
        .sec-head { font-size: 1rem; padding-bottom: 6px; }

        /* Metric cards: stack better */
        [data-testid="stMetricValue"] {
            font-size: 1.3rem !important;
        }
        [data-testid="stMetric"] {
            padding: 12px !important;
        }

        /* Tab labels: shorter on mobile */
        .stTabs [data-baseweb="tab"] {
            padding: 8px 12px !important;
            font-size: 0.85rem !important;
        }

        /* Make columns stack on mobile */
        [data-testid="column"] {
            min-width: 100% !important;
            flex: 1 1 100% !important;
        }

        /* Smaller dataframes */
        .stDataFrame table {
            font-size: 0.75rem !important;
        }
        .stDataFrame th, .stDataFrame td {
            padding: 6px 8px !important;
        }

        /* Hide caption text on mobile to save space */
        [data-testid="stCaptionContainer"] {
            font-size: 0.75rem !important;
        }

        /* Plotly charts: smaller margins */
        .js-plotly-plot {
            margin: 0 -8px !important;
        }

        /* Main content padding */
        .main .block-container {
            padding: 1rem !important;
            max-width: 100% !important;
        }

        /* Hide sidebar gap */
        section[data-testid="stSidebar"] {
            width: 280px !important;
        }
    }

    /* ── TABLET: 641px - 1024px ───────────────────────────────── */
    @media (min-width: 641px) and (max-width: 1024px) {

        .tih-header h1, .tih-header h2 {
            font-size: 1.6rem;
        }

        .kpi-number { font-size: 1.7rem; }

        [data-testid="stMetricValue"] {
            font-size: 1.5rem !important;
        }

        /* Allow 2-column layout */
        [data-testid="column"] {
            min-width: 48% !important;
        }

        .main .block-container {
            padding: 1.5rem !important;
            max-width: 95% !important;
        }
    }

    /* ── DESKTOP: > 1024px ────────────────────────────────────── */
    @media (min-width: 1025px) {

        .tih-header {
            padding: 28px 36px;
        }
        .tih-header h1, .tih-header h2 {
            font-size: 2rem;
        }
        .tih-header p {
            font-size: 0.95rem;
        }

        .kpi-number { font-size: 2rem; }
        .kpi-label  { font-size: 0.8rem; }

        [data-testid="stMetricValue"] {
            font-size: 1.8rem !important;
        }

        .stTabs [data-baseweb="tab"] {
            padding: 12px 20px !important;
            font-size: 0.95rem !important;
        }

        .main .block-container {
            max-width: 1400px !important;
            padding: 2rem !important;
        }
    }

    /* ── ULTRA-WIDE: > 1600px ─────────────────────────────────── */
    @media (min-width: 1600px) {
        .kpi-number { font-size: 2.5rem; }
        .main .block-container {
            max-width: 1600px !important;
        }
    }

    /* ═══════════════════════════════════════════════════════════ */
    /*  ACCESSIBILITY ENHANCEMENTS                                */
    /* ═══════════════════════════════════════════════════════════ */

    /* Focus visible for keyboard navigation */
    button:focus-visible,
    a:focus-visible,
    input:focus-visible,
    [role="button"]:focus-visible {
        outline: 2px solid var(--e3d-accent) !important;
        outline-offset: 2px !important;
        border-radius: 4px;
    }

    /* High contrast mode support */
    @media (prefers-contrast: high) {
        .kpi-card, .alert-critical, .alert-warning,
        .alert-positive, .alert-info {
            border-width: 2px !important;
        }
    }

    /* Reduced motion support */
    @media (prefers-reduced-motion: reduce) {
        *, *::before, *::after {
            animation-duration: 0.01ms !important;
            transition-duration: 0.01ms !important;
        }
    }

    /* ═══════════════════════════════════════════════════════════ */
    /*  CUSTOM UTILITY CLASSES                                    */
    /* ═══════════════════════════════════════════════════════════ */

    /* Intent badges */
    .badge-high   { background: #0a2d1a; border: 1px solid var(--e3d-green); color: var(--e3d-green); border-radius: 16px; padding: 4px 12px; font-size: 0.75rem; display: inline-block; }
    .badge-medium { background: #2d1a00; border: 1px solid var(--e3d-yellow); color: var(--e3d-yellow); border-radius: 16px; padding: 4px 12px; font-size: 0.75rem; display: inline-block; }
    .badge-low    { background: #2d0a0a; border: 1px solid var(--e3d-red); color: var(--e3d-red); border-radius: 16px; padding: 4px 12px; font-size: 0.75rem; display: inline-block; }

    /* Info card */
    .info-card {
        background: var(--e3d-card-light);
        border: 1px solid var(--e3d-border);
        border-radius: 10px;
        padding: 16px;
        margin: 10px 0;
    }

    /* Helper text */
    .helper-text {
        color: var(--e3d-text-faint);
        font-size: 0.8rem;
        line-height: 1.5;
    }

    /* ═══════════════════════════════════════════════════════════ */
    /*  HIDE STREAMLIT BRANDING (cleaner UX)                      */
    /* ═══════════════════════════════════════════════════════════ */

    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    header[data-testid="stHeader"] {
        background: transparent;
    }

    /* Optional: hide "Made with Streamlit" badge */
    .viewerBadge_link__1S137 { display: none !important; }

    </style>
    """


def get_chart_config() -> dict:
    """Mobile-responsive Plotly chart config."""
    return {
        "responsive":         True,
        "displayModeBar":     False,
        "scrollZoom":         False,
        "doubleClick":        "reset",
        "showAxisDragHandles": False,
        "showTips":           False,
    }


def get_chart_theme() -> dict:
    """Mobile-responsive Plotly chart theme (no margin to avoid kwarg conflicts)."""
    return {
        "paper_bgcolor": "#0A1628",
        "plot_bgcolor": "#0A1628",
        "font_color": "#a0b4cc",
        "font_size": 11,
        "autosize": True,
    }

def get_chart_theme_with_margin(margin=None) -> dict:
    """Returns theme with margin (use ONLY if not passing margin separately)."""
    if margin is None:
        margin = dict(l=10, r=10, t=40, b=10)
    return {
        "paper_bgcolor": "#0A1628",
        "plot_bgcolor": "#0A1628",
        "font_color": "#a0b4cc",
        "font_size": 11,
        "autosize": True,
        "margin": margin,
    }

