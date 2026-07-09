"""
reporting_engine.py — Eagle 3D Streaming Analytics Hub
========================================================
Minimal Telegram sender. Used by all_alerts.py + individual alert modules.
"""

from __future__ import annotations

import os
import time
from typing import Optional

import requests


def _secret(name: str, default: str = "") -> str:
    val = os.environ.get(name, "").strip()
    if val:
        return val
    try:
        import streamlit as st
        return str(st.secrets.get(name, "") or default).strip()
    except Exception:
        return default


def _bot_token() -> str:
    return _secret("TELEGRAM_BOT_TOKEN")


def _chat_id() -> str:
    return _secret("TELEGRAM_CHAT_ID")


def send_telegram(message: str,
                  parse_mode: str = "Markdown",
                  disable_preview: bool = True,
                  retries: int = 3) -> bool:
    """Send a message to the configured Telegram chat."""
    if not message or not message.strip():
        return False

    token = _bot_token()
    chat  = _chat_id()
    if not token or not chat:
        print("[reporting_engine] Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    # Telegram limit: 4096 chars per message
    chunks = []
    remaining = message.strip()
    while len(remaining) > 4000:
        cut = remaining.rfind("\n", 0, 4000)
        if cut == -1:
            cut = 4000
        chunks.append(remaining[:cut])
        remaining = remaining[cut:]
    chunks.append(remaining)

    for chunk in chunks:
        payload = {
            "chat_id": chat,
            "text": chunk,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_preview,
        }
        for attempt in range(retries):
            try:
                r = requests.post(url, json=payload, timeout=15)
                if r.status_code == 200:
                    break
                # Bad markdown → retry as plain text
                if r.status_code == 400 and parse_mode:
                    payload.pop("parse_mode", None)
                    continue
                # Rate limit
                if r.status_code == 429:
                    time.sleep(int(r.headers.get("Retry-After", 5)))
                    continue
                print(f"[reporting_engine] send failed {r.status_code}: {r.text[:200]}")
            except requests.RequestException as e:
                print(f"[reporting_engine] request error attempt {attempt+1}: {e}")
                time.sleep(2)
        else:
            return False

    return True


def send_report(title: str, body: str) -> bool:
    """Send a titled report."""
    msg = f"*{title}*\n\n{body}"
    return send_telegram(msg)


if __name__ == "__main__":
    from datetime import datetime
    ok = send_telegram(f"🦅 Test from Eagle 3D Streaming Analytics Hub at {datetime.utcnow().isoformat()}")
    print("Sent:", ok)
