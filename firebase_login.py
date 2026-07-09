"""
firebase_login.py — Eagle 3D Streaming Analytics Hub
======================================================
One-time Firebase login to the KPI dashboard.
Saves storage_state to kpi_storage_state.json so future scrapes
don't need to re-authenticate.

Run standalone:  python3 firebase_login.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


KPI_URL = "https://kpidashboard.eagle3dstreaming.com/"
STORAGE_FILE = Path("kpi_storage_state.json")


def _secret(name: str, default: str = "") -> str:
    val = os.environ.get(name, "").strip()
    if val:
        return val
    try:
        import streamlit as st
        return str(st.secrets.get(name, "") or default).strip()
    except Exception:
        return default


def log(msg: str) -> None:
    print(f"[firebase_login] {msg}", flush=True)


def login_and_save() -> bool:
    email = _secret("KPI_EMAIL")
    password = _secret("KPI_PASSWORD")

    if not email or not password:
        log("❌ KPI_EMAIL or KPI_PASSWORD missing in secrets.toml/env")
        return False

    log(f"Logging in as {email}...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"),
        )
        page = ctx.new_page()

        try:
            page.goto(KPI_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)

            # Try to find email input
            email_selectors = [
                'input[type="email"]',
                'input[type="text"]',
                'input[placeholder*="mail" i]',
                'input[name*="email" i]',
            ]
            filled_email = False
            for sel in email_selectors:
                if page.locator(sel).count() > 0:
                    page.locator(sel).first.fill(email)
                    filled_email = True
                    log(f"  ✓ Email filled via '{sel}'")
                    break
            if not filled_email:
                log("❌ Could not find email input")
                browser.close()
                return False

            # Fill password
            pw_selectors = ['input[type="password"]', 'input[name*="pass" i]']
            filled_pw = False
            for sel in pw_selectors:
                if page.locator(sel).count() > 0:
                    page.locator(sel).first.fill(password)
                    filled_pw = True
                    log(f"  ✓ Password filled via '{sel}'")
                    break
            if not filled_pw:
                log("❌ Could not find password input")
                browser.close()
                return False

            # Click submit
            btn_selectors = [
                'button[type="submit"]',
                'button:has-text("Login")',
                'button:has-text("Log in")',
                'button:has-text("Sign in")',
                'input[type="submit"]',
            ]
            clicked = False
            for sel in btn_selectors:
                if page.locator(sel).count() > 0:
                    page.locator(sel).first.click()
                    clicked = True
                    log(f"  ✓ Submit clicked via '{sel}'")
                    break
            if not clicked:
                # Fallback: press Enter
                page.keyboard.press("Enter")
                log("  ✓ Submitted via Enter key")

            # Wait for post-login redirect
            page.wait_for_timeout(8000)

            # Check success: password field should be gone
            if page.locator('input[type="password"]').count() > 0:
                log("❌ Login failed — password field still visible")
                page.screenshot(path="data_output/debug_login_failed.png")
                browser.close()
                return False

            log("✅ Login successful")

            # Save storage state
            ctx.storage_state(path=str(STORAGE_FILE))
            log(f"✅ Storage state saved to {STORAGE_FILE}")

            browser.close()
            return True

        except Exception as e:
            log(f"❌ Login error: {e}")
            try:
                page.screenshot(path="data_output/debug_login_error.png")
            except Exception:
                pass
            browser.close()
            return False


if __name__ == "__main__":
    ok = login_and_save()
    sys.exit(0 if ok else 1)
