from __future__ import annotations

import json
import re
import secrets
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / ".streamlit" / "secrets.toml"
TARGET_REPO = "e3ds/eagle-analytics"

COOKIE_CANDIDATES = [
    ROOT / "data" / "linkedin_cookies.json",
    ROOT / "data_output" / "linkedin_cookies.json",
]

if not SECRETS.exists():
    raise SystemExit(f"Missing {SECRETS}")

text = SECRETS.read_text(encoding="utf-8", errors="ignore")

def get_simple_value(key: str) -> str:
    m = re.search(rf'^{re.escape(key)}\s*=\s*"(.*)"\s*$', text, re.MULTILINE)
    return m.group(1) if m else ""

def set_simple_value(key: str, value: str) -> None:
    global text
    line = f'{key} = "{value}"'
    pattern = rf'^{re.escape(key)}\s*=.*$'
    if re.search(pattern, text, flags=re.MULTILINE):
        text = re.sub(pattern, line, text, flags=re.MULTILINE)
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += line + "\n"

# 1) Ensure WEBHOOK_API_KEY exists
webhook_key = get_simple_value("WEBHOOK_API_KEY").strip()
if not webhook_key:
    webhook_key = "e3d_" + secrets.token_urlsafe(32)
    set_simple_value("WEBHOOK_API_KEY", webhook_key)
    print("OK: generated WEBHOOK_API_KEY and added to .streamlit/secrets.toml")
else:
    print("OK: WEBHOOK_API_KEY already exists in .streamlit/secrets.toml")

SECRETS.write_text(text, encoding="utf-8")

# 2) Load LinkedIn cookies from file if not in secrets.toml
linkedin_cookies_secret = get_simple_value("LINKEDIN_COOKIES_JSON").strip()

if not linkedin_cookies_secret:
    cookie_file = next((p for p in COOKIE_CANDIDATES if p.exists()), None)
    if cookie_file is None:
        raise SystemExit("❌ LINKEDIN_COOKIES_JSON missing and no local linkedin_cookies.json file found")

    raw = cookie_file.read_text(encoding="utf-8", errors="ignore").strip()
    if not raw:
        raise SystemExit(f"❌ Cookie file exists but is empty: {cookie_file}")

    # validate JSON
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise SystemExit("❌ linkedin_cookies.json is not a JSON list")

    linkedin_cookies_secret = raw
    print(f"OK: loaded LINKEDIN_COOKIES_JSON from {cookie_file}")
else:
    print("OK: LINKEDIN_COOKIES_JSON already exists in .streamlit/secrets.toml")

# 3) Rewrite push script with fallback logic
push_script = ROOT / "scripts" / "push_github_secrets.py"
push_script.write_text(
f'''from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / ".streamlit" / "secrets.toml"
TARGET_REPO = "{TARGET_REPO}"

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
    raise SystemExit(f"Missing {{SECRETS}}")

text = SECRETS.read_text(encoding="utf-8", errors="ignore")

def get_value(key: str) -> str:
    m = re.search(rf'^{{re.escape(key)}}\\s*=\\s*"(.*)"\\s*$', text, re.MULTILINE)
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

    print(f"Setting GitHub secret for {{TARGET_REPO}}: {{key}}")
    subprocess.run(
        ["gh", "secret", "set", key, "-R", TARGET_REPO],
        input=val.encode("utf-8"),
        check=True,
    )

if missing:
    print("\\nMissing keys (not pushed):")
    for k in missing:
        print(" -", k)

print(f"\\n✅ GitHub secrets push completed for {{TARGET_REPO}}")
''',
encoding="utf-8"
)

print("OK: patched scripts/push_github_secrets.py with cookie-file fallback")

# 4) Push the two secrets immediately
for key, val in [
    ("WEBHOOK_API_KEY", webhook_key),
    ("LINKEDIN_COOKIES_JSON", linkedin_cookies_secret),
]:
    print(f"Setting GitHub secret for {TARGET_REPO}: {key}")
    subprocess.run(
        ["gh", "secret", "set", key, "-R", TARGET_REPO],
        input=val.encode("utf-8"),
        check=True,
    )

print(f"✅ Missing GitHub secrets fixed and pushed for {TARGET_REPO}")
