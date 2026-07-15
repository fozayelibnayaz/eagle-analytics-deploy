from pathlib import Path
from datetime import datetime
import re

ROOT = Path.cwd()
OUT = ROOT / "audits" / "ALERT_CODE_AUDIT.md"

IGNORE_DIRS = {
    ".git", "venv", ".venv", "__pycache__", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache"
}

PRIMARY_PATTERNS = [
    "engagement_alerts.py",
    "*engagement*alerts*.py",
    "run_engagement_alerts.sh",
    "*run*engagement*alerts*.sh",
    "telegram_alerts.py",
    "*telegram*alerts*.py",
]

SECONDARY_PATTERNS = [
    "*youtube*.py",
    "*linkedin*.py",
    "*telegram*.py",
    "config.py",
    "app.py",
]

KEY_RE = re.compile(
    r"snapshot|baseline|prev_|subscriber|subscribers|unsubscribe|lost|"
    r"follow|follower|followers|like|likes|dislike|reaction|comment|comments|"
    r"view|views|telegram|sendMessage|send_message|bot|chat_id|youtube|linkedin|"
    r"alert|delta|change|poll|interval",
    re.IGNORECASE,
)

SECRET_KEYS = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "YOUTUBE_API_KEY",
    "YOUTUBE_CHANNEL_ID",
    "LINKEDIN_COMPANY_PAGE",
    "MONGO_URI",
    "MONGO_DB",
]

def should_skip(path: Path) -> bool:
    return any(part in IGNORE_DIRS for part in path.parts)

def match_any(name: str, patterns) -> bool:
    from fnmatch import fnmatch
    return any(fnmatch(name, p) for p in patterns)

def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return f"<<READ ERROR: {e}>>"

def numbered(text: str) -> str:
    lines = text.splitlines()
    return "\n".join(f"{i+1:4d}: {line}" for i, line in enumerate(lines))

def collect_files(patterns):
    found = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        if should_skip(p):
            continue
        if match_any(p.name, patterns):
            found.append(p)
    return sorted(set(found))

def snippet_windows(text: str, radius: int = 4, max_hits: int = 20):
    lines = text.splitlines()
    hits = []
    for i, line in enumerate(lines):
        if KEY_RE.search(line):
            hits.append(i)
    if not hits:
        return []

    hits = hits[:max_hits]
    windows = []
    used = set()
    for idx in hits:
        start = max(0, idx - radius)
        end = min(len(lines), idx + radius + 1)
        block = []
        for j in range(start, end):
            if j not in used:
                block.append(f"{j+1:4d}: {lines[j]}")
                used.add(j)
        if block:
            windows.append("\n".join(block))
    return windows

primary_files = collect_files(PRIMARY_PATTERNS)
secondary_files = collect_files(SECONDARY_PATTERNS)

# Remove duplicates from secondary if already in primary
secondary_files = [p for p in secondary_files if p not in primary_files]

report = []
report.append("# ALERT CODE AUDIT")
report.append(f"Generated: {datetime.now().isoformat()}")
report.append("")

report.append("## FOUND PRIMARY FILES")
if primary_files:
    for p in primary_files:
        report.append(f"- {p.relative_to(ROOT)}")
else:
    report.append("- NONE FOUND")
report.append("")

report.append("## FOUND SECONDARY FILES")
if secondary_files:
    for p in secondary_files:
        report.append(f"- {p.relative_to(ROOT)}")
else:
    report.append("- NONE FOUND")
report.append("")

# Secrets presence only, values redacted
secrets_path = ROOT / ".streamlit" / "secrets.toml"
report.append("## SECRETS PRESENCE (VALUES REDACTED)")
if secrets_path.exists():
    s = read_text(secrets_path)
    for key in SECRET_KEYS:
        m = re.search(rf'^{re.escape(key)}\s*=\s*(.+)$', s, re.MULTILINE)
        if m:
            report.append(f"- {key}: PRESENT")
        else:
            report.append(f"- {key}: MISSING")
else:
    report.append("- .streamlit/secrets.toml: MISSING")
report.append("")

for p in primary_files:
    text = read_text(p)
    report.append(f"## PRIMARY FILE: {p.relative_to(ROOT)}")
    report.append(f"Size: {len(text):,} chars")
    report.append("")
    report.append("```text")
    report.append(numbered(text))
    report.append("```")
    report.append("")

for p in secondary_files:
    text = read_text(p)
    wins = snippet_windows(text)
    if not wins:
        continue
    report.append(f"## SECONDARY MATCHES: {p.relative_to(ROOT)}")
    report.append(f"Size: {len(text):,} chars")
    report.append("")
    for idx, block in enumerate(wins, start=1):
        report.append(f"### Snippet {idx}")
        report.append("```text")
        report.append(block)
        report.append("```")
        report.append("")
        
OUT.write_text("\n".join(report), encoding="utf-8")
print(f"OK: {OUT} written")
