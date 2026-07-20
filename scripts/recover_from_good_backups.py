from pathlib import Path
from datetime import datetime
import subprocess
import re

ROOT = Path.cwd()
BACKUPS = ROOT / "backups"

TARGETS = {
    "app.py": [
        "app.py.*.bak",
        "app.py*.bak",
    ],
    "pages_registry.py": [
        "pages_registry.py.*.bak",
        "pages_registry.py*.bak",
    ],
}

def can_compile(path: Path) -> bool:
    r = subprocess.run(
        ["python3", "-m", "py_compile", str(path)],
        capture_output=True, text=True
    )
    return r.returncode == 0

def find_latest_good_backup(name: str):
    patterns = TARGETS[name]
    candidates = []
    for pat in patterns:
        candidates.extend(BACKUPS.glob(pat))
    candidates = sorted(set(candidates), key=lambda p: p.stat().st_mtime, reverse=True)

    for c in candidates:
        if can_compile(c):
            return c
    return None

for name in TARGETS:
    dest = ROOT / name
    good = find_latest_good_backup(name)
    if not good:
        raise SystemExit(f"❌ No compilable backup found for {name}")
    dest.write_text(good.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
    print(f"✅ Restored {name} from good backup: {good}")

# -------------------------------------------------------------------
# Minimal safe fix for app.py
# -------------------------------------------------------------------
app = ROOT / "app.py"
text = app.read_text(encoding="utf-8", errors="ignore")

# Fix route naming
text = text.replace("def _route(page: str, user_email: str) -> None:", "def route(page: str, user_email: str) -> None:")
text = text.replace("_route(current_page, user_email)", "route(current_page, user_email)")

# Fix KPI field names only
text = text.replace("signups_accepted", "signups")
text = text.replace("uploads_accepted", "first_uploads")
text = text.replace("paid_accepted", "new_paid_customers")

# Fix labels only
text = text.replace("New New Paying Customers", "New Paying Customers")
text = text.replace("💳 Paid", "💳 New Paying Customers")
text = text.replace("Paying Customers", "New Paying Customers")

# Ensure _greeting exists
if "def _greeting() -> str:" not in text:
    block = '''
def _greeting() -> str:
    try:
        h = datetime.now().hour
        return "Good morning" if h < 12 else ("Good afternoon" if h < 18 else "Good evening")
    except Exception:
        return "Hello"

'''
    idx = text.find("def render_dashboard")
    if idx != -1:
        text = text[:idx] + block + text[idx:]
    else:
        text += "\\n" + block

app.write_text(text, encoding="utf-8")
print("✅ Applied minimal safe fixes to app.py")

# -------------------------------------------------------------------
# Minimal safe fix for pages_registry.py
# -------------------------------------------------------------------
pr = ROOT / "pages_registry.py"
text = pr.read_text(encoding="utf-8", errors="ignore")

text = text.replace("signups_accepted", "signups")
text = text.replace("uploads_accepted", "first_uploads")
text = text.replace("paid_accepted", "new_paid_customers")
text = text.replace("New New Paying Customers", "New Paying Customers")
text = text.replace('c3.metric("💳 PAID",', 'c3.metric("💳 New Paying Customers",')
text = text.replace('c3.metric("💳 Paid",', 'c3.metric("💳 New Paying Customers",')

# Remove recurring UI lines if they exist
text = re.sub(r'.*Recurring Customers.*\\n', '', text)
text = re.sub(r'.*Stopped Recurring.*\\n', '', text)

pr.write_text(text, encoding="utf-8")
print("✅ Applied minimal safe fixes to pages_registry.py")

# -------------------------------------------------------------------
# Clean rewrite of LinkedIn cookie installer
# -------------------------------------------------------------------
lic = ROOT / "scripts" / "install_linkedin_cookies_full.py"
lic.write_text(
'''from __future__ import annotations

import json
import html
import re
import os
from pathlib import Path
from urllib.parse import urlparse

INPUTS = [
    Path("data/linkedin_cookies.json"),
    Path("data_output/linkedin_cookies.json"),
    Path.home() / "Downloads" / "linkedin_cookies.json",
    Path("linkedin_cookies.json"),
]

OUTS = [
    Path("data/linkedin_cookies.json"),
    Path("data_output/linkedin_cookies.json"),
]

IMPORTANT = ["li_at", "JSESSIONID", "bcookie", "bscookie", "PLAY_SESSION", "fptctx2"]

def unesc(v):
    return html.unescape(str(v or "")).strip()

def extract_host(raw: str) -> str:
    s = unesc(raw).strip('"').strip("'")
    m = re.search(r'((?:www\\.)?linkedin\\.com)\\b', s, re.I)
    if m:
        return m.group(1).lower()
    if s.startswith("http://") or s.startswith("https://"):
        try:
            p = urlparse(s)
            if p.netloc:
                return p.netloc.lower()
        except Exception:
            pass
    return s.strip("/").lstrip(".").lower()

def clean_obj(obj):
    if isinstance(obj, dict):
        return {k: clean_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_obj(x) for x in obj]
    if isinstance(obj, str):
        return html.unescape(obj)
    return obj

def normalize_cookie(c):
    c = clean_obj(c)
    name = unesc(c.get("name"))
    value = unesc(c.get("value"))
    if not name:
        return None
    domain = extract_host(c.get("domain", ""))
    if not domain:
        return None
    fixed = dict(c)
    fixed["name"] = name
    fixed["value"] = value
    fixed["domain"] = domain if c.get("hostOnly", False) else "." + domain.lstrip(".")
    fixed["path"] = unesc(c.get("path") or "/") or "/"
    ss = unesc(c.get("sameSite"))
    if ss.lower() in ("no_restriction", "none", "no restriction"):
        fixed["sameSite"] = "no_restriction"
    elif ss.lower() in ("lax", "strict"):
        fixed["sameSite"] = ss.lower()
    else:
        fixed["sameSite"] = None
    return fixed

def main():
    raw_secret = os.environ.get("LINKEDIN_COOKIES_JSON", "").strip()
    if raw_secret:
        Path("data").mkdir(exist_ok=True)
        Path("data_output").mkdir(exist_ok=True)
        Path("data/linkedin_cookies.json").write_text(raw_secret, encoding="utf-8")
        Path("data_output/linkedin_cookies.json").write_text(raw_secret, encoding="utf-8")

    src = next((p for p in INPUTS if p.exists()), None)
    if src is None:
        print("❌ Could not find input cookie file.")
        for p in INPUTS:
            print(" -", p)
        raise SystemExit(1)

    raw = src.read_text(encoding="utf-8", errors="ignore").strip()
    if not raw:
        print(f"❌ Input file is empty: {src}")
        raise SystemExit(1)

    data = json.loads(raw)
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, list):
        print("❌ Cookie file is not a JSON list")
        raise SystemExit(1)

    cleaned = []
    for item in data:
        if isinstance(item, dict):
            norm = normalize_cookie(item)
            if norm:
                cleaned.append(norm)

    if not cleaned:
        print("❌ No valid cookies after normalization")
        raise SystemExit(1)

    names = {c.get("name") for c in cleaned}
    for out in OUTS:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
        print(f"OK: wrote full sanitized cookies -> {out}")

    print(f"Full cookie count: {len(cleaned)}")
    for k in IMPORTANT:
        print(f"{k}: {'PRESENT' if k in names else 'MISSING'}")

if __name__ == "__main__":
    main()
''',
encoding="utf-8"
)
print("✅ Rewrote scripts/install_linkedin_cookies_full.py")

print("✅ recovery + minimal fixes complete")
