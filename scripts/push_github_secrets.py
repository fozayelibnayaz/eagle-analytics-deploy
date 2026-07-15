from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / ".streamlit" / "secrets.toml"
TARGET_REPO = "e3ds/eagle-analytics"

KEYS = [
    "MONGO_URI",
    "MONGO_DB",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "YOUTUBE_API_KEY",
    "YOUTUBE_CHANNEL_ID",
    "WEBHOOK_API_KEY",
    "APP_PASSWORD",
    "LINKEDIN_COOKIES_JSON",
]

COOKIE_CANDIDATES = [
    ROOT / "data" / "linkedin_cookies.json",
    ROOT / "data_output" / "linkedin_cookies.json",
]

if not SECRETS.exists():
    raise SystemExit(f"Missing {SECRETS}")

text = SECRETS.read_text(encoding="utf-8", errors="ignore")

def get_value(key: str) -> str:
    m = re.search(rf'^{re.escape(key)}\s*=\s*"(.*)"\s*$', text, re.MULTILINE)
    if m:
        return m.group(1)
    return ""

def get_cookie_file_value() -> str:
    for p in COOKIE_CANDIDATES:
        if p.exists():
            raw = p.read_text(encoding="utf-8", errors="ignore").strip()
            if raw:
                data = json.loads(raw)
                if isinstance(data, list):
                    return raw
    return ""

missing = []
for key in KEYS:
    val = get_value(key)

    if not val and key == "LINKEDIN_COOKIES_JSON":
        val = get_cookie_file_value()

    if not val:
        missing.append(key)
        continue

    print(f"Setting GitHub secret for {TARGET_REPO}: {key}")
    subprocess.run(
        ["gh", "secret", "set", key, "-R", TARGET_REPO],
        input=val.encode("utf-8"),
        check=True,
    )

if missing:
    print("\nMissing keys (not pushed):")
    for k in missing:
        print(" -", k)

print(f"\n✅ GitHub secrets push completed for {TARGET_REPO}")
