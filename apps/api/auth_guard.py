"""
Enterprise authentication guard for Eagle Analytics Hub.

Uses Streamlit OIDC authentication:
- Verified identity via identity provider
- User email from st.user
- MongoDB allow-list via access_control.py
- Audit logging
"""

from __future__ import annotations

from datetime import datetime
import streamlit as st

APP_NAME = "Eagle Analytics Hub"


def get_verified_user_email() -> str:
    try:
        if not getattr(st, "user", None):
            return ""
        if not st.user.is_logged_in:
            return ""
        return str(st.user.get("email", "") or "").strip().lower()
    except Exception:
        return ""


def render_login_page():
    st.set_page_config(
        page_title=f"{APP_NAME} | Login",
        page_icon="🦅",
        layout="centered",
    )

    st.markdown(
        """
        <style>
        .login-card {
            max-width: 460px;
            margin: 8vh auto;
            padding: 2.25rem;
            border-radius: 24px;
            background: linear-gradient(180deg, rgba(255,255,255,.08), rgba(255,255,255,.03));
            border: 1px solid rgba(255,255,255,.12);
            box-shadow: 0 20px 60px rgba(0,0,0,.25);
        }
        .login-title {
            font-size: 2rem;
            font-weight: 800;
            margin-bottom: .25rem;
        }
        .login-subtitle {
            opacity: .75;
            margin-bottom: 1.5rem;
        }
        </style>
        <div class="login-card">
            <div class="login-title">Eagle Analytics Hub</div>
            <div class="login-subtitle">
                Secure analytics for Eagle3D Streaming.
                Sign in with your verified company account.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Continue with SSO", type="primary", use_container_width=True):
        st.login()


def require_auth(page_name: str = "Dashboard"):
    """
    Enforce authenticated + authorized access.
    Must be called before rendering protected pages.
    """
    try:
        logged_in = bool(st.user and st.user.is_logged_in)
    except Exception:
        logged_in = False

    if not logged_in:
        render_login_page()
        st.stop()

    email = get_verified_user_email()

    try:
        from access_control import is_allowed, log_access
        allowed, role, reason = is_allowed(email)
    except Exception as e:
        st.error(f"Access control unavailable: {e}")
        st.stop()

    if not allowed:
        try:
            from access_control import log_access
            log_access(
                email=email,
                action="unauthorized_access",
                success=False,
                reason=f"{reason} | page={page_name}",
                role="none",
            )
        except Exception:
            pass

        st.error("Access denied")
        st.caption("Your verified email is not authorized for Eagle Analytics Hub.")
        if st.button("Logout"):
            st.logout()
        st.stop()

    try:
        from access_control import log_access
        if "_auth_logged" not in st.session_state:
            log_access(
                email=email,
                action="authorized_session",
                success=True,
                reason=f"Access granted | page={page_name}",
                role=role,
            )
            st.session_state["_auth_logged"] = True
    except Exception:
        pass

    st.session_state["user_email"] = email
    st.session_state["user_role"] = role
    return email, role


def render_user_menu():
    email = st.session_state.get("user_email", "")
    role = st.session_state.get("user_role", "")
    with st.sidebar:
        st.caption(f"Signed in as: {email}")
        st.caption(f"Role: {role}")
        if st.button("Logout", use_container_width=True):
            st.logout()
