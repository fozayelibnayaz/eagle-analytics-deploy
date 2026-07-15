"""
auth_guard.py — Eagle 3D Streaming Analytics Hub
==================================================
BULLETPROOF auth: HMAC-signed token in URL query param + localStorage.

Flow:
  1. localStorage script runs on every page load → if token exists,
     it's appended to URL as ?t=xxx and page reloads.
  2. Python reads ?t=xxx from st.query_params on EVERY rerun.
  3. Token is HMAC-verified server-side. Valid → auto-login.
  4. On login: token appended to URL + saved to localStorage.
  5. On logout: URL cleaned + localStorage wiped.

Advantages:
  - No external libs (no cookies-manager, no controller)
  - Works on every rerun (query params are synchronous)
  - Nav clicks preserve token via URL
  - 7-day expiry enforced by HMAC payload
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

APP_NAME = "Eagle 3D Streaming"
TOKEN_PARAM = "t"          # ?t=<signed-token>
LS_KEY = "e3d_auth_token"  # localStorage key


# ─── Secrets ─────────────────────────────────────────────────────
def _secret(name: str, default: str = "") -> str:
    try:
        val = str(st.secrets.get(name, "") or "").strip()
        return val or default
    except Exception:
        return default


def _app_password() -> str: return _secret("APP_PASSWORD", "")


def _cookie_secret() -> str:
    s = _secret("COOKIE_SECRET", "")
    if not s:
        s = hashlib.sha256(
            (_app_password() + "e3d-fallback-salt").encode()
        ).hexdigest()
    return s


def _cookie_days() -> int:
    try:
        return int(_secret("COOKIE_DAYS", "7") or 7)
    except Exception:
        return 7


# ─── HMAC token ──────────────────────────────────────────────────
def _sign_token(payload: dict) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    sig = hmac.new(
        _cookie_secret().encode(), body.encode(), hashlib.sha256,
    ).hexdigest()
    return f"{body}.{sig}"


def _verify_token(token: str) -> dict | None:
    try:
        body, sig = token.rsplit(".", 1)
        expected = hmac.new(
            _cookie_secret().encode(), body.encode(), hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        padded = body + "=" * (-len(body) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded).decode())
        if int(data.get("exp", 0)) < int(time.time()):
            return None
        return data
    except Exception:
        return None


def _make_token(email: str, role: str, ip: str) -> str:
    now = int(time.time())
    exp = now + _cookie_days() * 86400
    return _sign_token({
        "email": email, "role": role, "ip": ip,
        "iat": now, "exp": exp,
    })


# ─── IP ──────────────────────────────────────────────────────────
def _get_client_ip() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        from streamlit.runtime import get_instance
        ctx = get_script_run_ctx()
        if ctx:
            info = get_instance()._session_mgr.get_session_info(ctx.session_id)
            if info and info.client:
                req = getattr(info.client, "request", None)
                if req:
                    ip = req.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                    if not ip:
                        ip = req.headers.get("X-Real-IP", "")
                    if not ip:
                        ip = getattr(req, "remote_ip", "")
                    return ip or "local"
    except Exception:
        pass
    return "local"


# ─── JS: localStorage ↔ URL sync ─────────────────────────────────
def _inject_ls_bootstrap():
    """
    On every page load:
      1. If URL has ?t=xxx → save to localStorage, done.
      2. Else if localStorage has token → append ?t=xxx to URL and reload.
    This runs BEFORE Streamlit reads query_params, ensuring the token
    is always in the URL when Python code executes.

    We use components.html so the script runs in the parent frame context.
    """
    js = f"""
    <script>
    (function() {{
      try {{
        const parent = window.parent;
        const url = new URL(parent.location.href);
        const urlToken = url.searchParams.get('{TOKEN_PARAM}');
        const lsToken  = parent.localStorage.getItem('{LS_KEY}');

        if (urlToken) {{
          // URL has token → sync to localStorage
          if (urlToken !== lsToken) {{
            parent.localStorage.setItem('{LS_KEY}', urlToken);
          }}
        }} else if (lsToken) {{
          // No token in URL but localStorage has one → inject + reload
          url.searchParams.set('{TOKEN_PARAM}', lsToken);
          parent.location.replace(url.toString());
        }}
      }} catch(e) {{
        console.error('[e3d auth bootstrap]', e);
      }}
    }})();
    </script>
    """
    components.html(js, height=0, width=0)


def _inject_ls_save(token: str):
    """After successful login, persist token to localStorage."""
    js = f"""
    <script>
    (function() {{
      try {{
        window.parent.localStorage.setItem('{LS_KEY}', '{token}');
      }} catch(e) {{ console.error(e); }}
    }})();
    </script>
    """
    components.html(js, height=0, width=0)


def _inject_ls_clear():
    """On logout: wipe localStorage + clean URL."""
    js = f"""
    <script>
    (function() {{
      try {{
        const parent = window.parent;
        parent.localStorage.removeItem('{LS_KEY}');
        const url = new URL(parent.location.href);
        url.searchParams.delete('{TOKEN_PARAM}');
        parent.history.replaceState({{}}, '', url.toString());
      }} catch(e) {{ console.error(e); }}
    }})();
    </script>
    """
    components.html(js, height=0, width=0)


def _inject_url_token_preserve(token: str):
    """
    Rewrite ALL <a> hrefs in the parent doc to include ?t=<token>.
    Ensures nav clicks preserve auth without another reload.
    Also intercepts clicks to same-origin links.
    """
    js = f"""
    <script>
    (function() {{
      const TOKEN = '{token}';
      const PARAM = '{TOKEN_PARAM}';
      const doc = window.parent.document;

      function patchLinks() {{
        const links = doc.querySelectorAll('a[href^="?"], a[href^="/?"], a[href="?"]');
        links.forEach(function(a) {{
          try {{
            const u = new URL(a.href, window.parent.location.origin);
            u.searchParams.set(PARAM, TOKEN);
            a.href = u.pathname + '?' + u.searchParams.toString();
          }} catch(e) {{}}
        }});
      }}

      // Patch immediately + on every mutation
      patchLinks();
      const observer = new MutationObserver(patchLinks);
      observer.observe(doc.body, {{ childList: true, subtree: true }});

      // Also ensure current URL has token (in case Streamlit stripped it)
      const cur = new URL(window.parent.location.href);
      if (cur.searchParams.get(PARAM) !== TOKEN) {{
        cur.searchParams.set(PARAM, TOKEN);
        window.parent.history.replaceState({{}}, '', cur.toString());
      }}
    }})();
    </script>
    """
    components.html(js, height=0, width=0)


# ─── UI ──────────────────────────────────────────────────────────
def _hide_chrome():
    st.markdown("""
    <style>
      [data-testid="stSidebar"], [data-testid="stSidebarNav"],
      [data-testid="collapsedControl"], section[data-testid="stSidebar"] {
        display: none !important;
      }
      header, #MainMenu, footer { visibility: hidden; }
      .main .block-container {
        max-width: 460px !important;
        padding-top: 4rem !important;
        margin: 0 auto !important;
      }
    </style>
    """, unsafe_allow_html=True)


def _login_css():
    st.markdown("""
    <style>
      .e3-login-card {
        background: linear-gradient(180deg, #141414 0%, #0a0a0a 100%);
        border: 1px solid #2a2a2a;
        border-radius: 20px;
        padding: 2.5rem 2rem;
        box-shadow: 0 20px 60px rgba(0,0,0,.35);
      }
      .e3-login-title {
        color: #fff; font-size: 1.8rem; font-weight: 700; margin-bottom: .25rem;
      }
      .e3-login-subtitle {
        color: #999; font-size: .95rem; margin-bottom: 1.5rem;
      }
      .e3-brand { color: #9EFF2F; font-size: 1rem; font-weight: 600; }
      .e3-brand-logo {
        display: flex; align-items: center; gap: 10px; margin-bottom: 1rem;
      }
    </style>
    """, unsafe_allow_html=True)


def _brand_row() -> str:
    logo_html = ""
    for p in ("static/eagle3d_logo2.png", "static/eagle3d_logo.png"):
        f = Path(p)
        if f.exists():
            b64 = base64.b64encode(f.read_bytes()).decode()
            logo_html = (
                f'<img src="data:image/png;base64,{b64}" '
                f'style="width:38px;height:38px;object-fit:contain;">'
            )
            break
    return f"""
    <div class="e3-brand-logo">{logo_html}<span class="e3-brand">{APP_NAME}</span></div>
    """


def _render_login_banner():
    """Animated brand banner shown above login forms."""
    import base64
    from pathlib import Path as _P
    import streamlit as st

    # Load logo
    logo_b64 = ""
    for f in ["static/eagle3d_logo2.png", "static/eagle3d_logo.png"]:
        fp = _P(f)
        if fp.exists():
            logo_b64 = base64.b64encode(fp.read_bytes()).decode()
            break

    st.markdown(f"""
    <style>
      @keyframes e3-pulse {{
        0%, 100% {{ transform: scale(1); opacity: 0.6; }}
        50%      {{ transform: scale(1.15); opacity: 1; }}
      }}
      @keyframes e3-shine {{
        0%   {{ transform: translateX(-100%); }}
        100% {{ transform: translateX(200%); }}
      }}
      @keyframes e3-float {{
        0%, 100% {{ transform: translateY(0); }}
        50%      {{ transform: translateY(-8px); }}
      }}
      .e3-login-banner {{
        position: relative;
        background: linear-gradient(135deg, #0d1810 0%, #1a2e1f 50%, #0d1810 100%);
        border: 1px solid rgba(158,255,47,0.25);
        border-radius: 20px;
        padding: 32px 24px;
        text-align: center;
        margin-bottom: 24px;
        overflow: hidden;
        box-shadow: 0 20px 60px rgba(0,0,0,0.5), 0 0 40px rgba(158,255,47,0.08);
      }}
      .e3-login-banner::before {{
        content: '';
        position: absolute;
        top: 0; left: 0;
        width: 40%; height: 200%;
        background: linear-gradient(to right,
          transparent 0%, rgba(158,255,47,0.15) 50%, transparent 100%);
        animation: e3-shine 4s infinite ease-in-out;
        pointer-events: none;
      }}
      .e3-login-banner-logo {{
        width: 80px; height: 80px;
        margin: 0 auto 12px auto;
        animation: e3-float 3s ease-in-out infinite;
        filter: drop-shadow(0 4px 20px rgba(158,255,47,0.4));
      }}
      .e3-login-banner-title {{
        color: #fff;
        font-size: 22px;
        font-weight: 700;
        letter-spacing: -0.02em;
        margin: 0 0 6px 0;
      }}
      .e3-login-banner-sub {{
        color: #9CA3AF;
        font-size: 13px;
        margin: 0;
      }}
      .e3-login-banner-dots {{
        display: flex;
        justify-content: center;
        gap: 8px;
        margin-top: 16px;
      }}
      .e3-login-banner-dots span {{
        width: 6px; height: 6px;
        border-radius: 50%;
        background: #9EFF2F;
        animation: e3-pulse 1.4s infinite ease-in-out;
      }}
      .e3-login-banner-dots span:nth-child(2) {{ animation-delay: 0.2s; }}
      .e3-login-banner-dots span:nth-child(3) {{ animation-delay: 0.4s; }}
    </style>
    <div class="e3-login-banner">
      <img class="e3-login-banner-logo"
           src="data:image/png;base64,{logo_b64}"
           alt="Eagle 3D Streaming" />
      <div class="e3-login-banner-title">Eagle 3D Streaming</div>
      <div class="e3-login-banner-sub">Analytics Hub · Real-time business intelligence</div>
      <div class="e3-login-banner-dots">
        <span></span><span></span><span></span>
      </div>
    </div>
    """, unsafe_allow_html=True)


def _render_password_screen():
    _hide_chrome(); _login_css()
    _render_login_banner()
    st.markdown('<div class="e3-login-card">', unsafe_allow_html=True)
    st.markdown(_brand_row(), unsafe_allow_html=True)
    st.markdown('<div class="e3-login-title">Analytics Hub</div>',
                unsafe_allow_html=True)
    st.markdown('<div class="e3-login-subtitle">Enter access password to continue</div>',
                unsafe_allow_html=True)
    with st.form("pwd_form"):
        pwd = st.text_input("Password", type="password",
                            placeholder="Enter password",
                            label_visibility="collapsed")
        if st.form_submit_button("🔓 Continue",
                                  width='stretch', type="primary"):
            expected = _app_password()
            if not expected:
                st.error("APP_PASSWORD not configured in secrets.toml")
                st.stop()
            if pwd == expected:
                st.session_state["_pwd_ok"] = True
                st.rerun()
            else:
                st.error("Incorrect password")
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()


def _render_email_screen():
    from access_control import is_allowed, log_access

    _hide_chrome(); _login_css()
    _render_login_banner()
    st.markdown('<div class="e3-login-card">', unsafe_allow_html=True)
    st.markdown(_brand_row(), unsafe_allow_html=True)
    st.markdown('<div class="e3-login-title">Verify your identity</div>',
                unsafe_allow_html=True)
    st.markdown(
        f'<div class="e3-login-subtitle">'
        f'Enter your work email (session stays for {_cookie_days()} days)</div>',
        unsafe_allow_html=True,
    )
    with st.form("email_form"):
        email = st.text_input(
            "Email", placeholder="you@eagle3dstreaming.com",
            label_visibility="collapsed",
        )
        if st.form_submit_button("✅ Verify & Sign In",
                                  width='stretch', type="primary"):
            ip = _get_client_ip()
            if not email or "@" not in email:
                st.error("Valid email required")
                log_access(email or "empty", "login_attempt",
                           success=False, reason="Invalid email", ip=ip)
                st.stop()
            allowed, role, reason = is_allowed(email)
            log_access(email, "login", success=allowed,
                       reason=reason, role=role, ip=ip)
            if allowed:
                em = email.strip().lower()
                token = _make_token(em, role, ip)

                # Set session state
                st.session_state["_pwd_ok"]    = True
                st.session_state["_auth_ok"]   = True
                st.session_state["user_email"] = em
                st.session_state["user_role"]  = role
                st.session_state["user_ip"]    = ip
                st.session_state["_auth_token"] = token

                # Put token in URL immediately
                st.query_params[TOKEN_PARAM] = token

                # Save to localStorage (survives reload)
                _inject_ls_save(token)

                # Small delay to let JS write to localStorage
                time.sleep(0.15)
                st.rerun()
            else:
                st.error(f"Access denied: {reason}")
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()


# ─── PUBLIC API ──────────────────────────────────────────────────
def require_auth(page_name: str = "Dashboard"):
    """
    THREE ways to auth (checked in order):
      1. session_state (fast path — same tab, no reload)
      2. URL query param ?t=xxx (nav clicks, refresh with URL)
      3. localStorage (refresh with clean URL — JS injects it back)
    """
    # Always inject the localStorage bootstrap so it runs even on login screens
    _inject_ls_bootstrap()

    # ── PATH 1: already authed this session ──
    if st.session_state.get("_auth_ok"):
        tok = st.session_state.get("_auth_token", "")
        # Keep URL token in sync (in case Streamlit stripped it)
        if tok:
            cur = st.query_params.get(TOKEN_PARAM, "")
            if cur != tok:
                st.query_params[TOKEN_PARAM] = tok
            # Patch all nav links to preserve token
            _inject_url_token_preserve(tok)
        return (
            st.session_state.get("user_email", ""),
            st.session_state.get("user_role", "viewer"),
        )

    # ── PATH 2: URL token ──
    url_token = st.query_params.get(TOKEN_PARAM, "")
    if url_token:
        data = _verify_token(url_token)
        if data:
            st.session_state["_pwd_ok"]    = True
            st.session_state["_auth_ok"]   = True
            st.session_state["user_email"] = data.get("email", "")
            st.session_state["user_role"]  = data.get("role", "viewer")
            st.session_state["user_ip"]    = data.get("ip", "")
            st.session_state["_auth_token"] = url_token
            # Patch links immediately so this render has correct hrefs
            _inject_url_token_preserve(url_token)
            return (
                st.session_state["user_email"],
                st.session_state["user_role"],
            )
        else:
            # Bad/expired token → clean up + go to login
            _inject_ls_clear()
            try:
                del st.query_params[TOKEN_PARAM]
            except Exception:
                pass

    # ── PATH 3: localStorage handles auto-inject via _inject_ls_bootstrap ──
    # If we got here, no valid token exists → show login screens

    if not st.session_state.get("_pwd_ok"):
        _render_password_screen()

    if not st.session_state.get("_auth_ok"):
        _render_email_screen()

    return (
        st.session_state.get("user_email", ""),
        st.session_state.get("user_role", "viewer"),
    )


def logout():
    """Clear everything: session, URL, localStorage."""
    for k in ("_pwd_ok", "_auth_ok", "user_email", "user_role",
              "user_ip", "_auth_token"):
        st.session_state.pop(k, None)
    try:
        st.query_params.clear()
    except Exception:
        pass
    _inject_ls_clear()


def render_user_menu():
    email = st.session_state.get("user_email", "")
    role  = st.session_state.get("user_role", "")
    with st.sidebar:
        st.markdown("---")
        st.caption(f"👤 {email}")
        st.caption(f"🔑 {role}")
        if st.button("🚪 Logout", width='stretch', key="_logout_btn"):
            logout()
            st.rerun()


def get_verified_user_email() -> str:
    return st.session_state.get("user_email", "") if st.session_state.get("_auth_ok") else ""
