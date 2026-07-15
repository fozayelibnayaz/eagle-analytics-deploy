from pathlib import Path
from datetime import datetime
import re

ROOT = Path.cwd()
TARGETS = [
    "app.py",
    "config.py",
    "mongo_client.py",
    "linkedin_daily_pipeline.py",
    ".github/workflows/daily_pipeline.yml",
    ".streamlit/secrets.toml",
]

PATTERNS = {
    "markdown_link_artifacts": re.compile(r'\[[^\]]+\]\(https?://[^)]+\)'),
    "markdown_identifier_artifacts": re.compile(r'(?<!\w)\*[A-Za-z_][A-Za-z0-9_]*\*'),
    "supabase_refs": re.compile(r'supabase|SUPABASE'),
    "github_actions_refs": re.compile(r'github|workflow|GITHUB_TOKEN', re.IGNORECASE),
    "streamlit_refs": re.compile(r'\bst\.', re.IGNORECASE),
    "mongo_refs": re.compile(r'mongo|MongoClient|pymongo', re.IGNORECASE),
}

report = []
report.append(f"# System Reality Check")
report.append(f"Generated: {datetime.now().isoformat()}")
report.append("")

for rel in TARGETS:
    p = ROOT / rel
    report.append(f"## {rel}")
    if not p.exists():
        report.append("Status: MISSING")
        report.append("")
        continue

    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        report.append(f"Status: READ ERROR - {e}")
        report.append("")
        continue

    report.append("Status: FOUND")
    report.append(f"Size: {len(text):,} chars")
    report.append("")

    hits = {}
    for name, pattern in PATTERNS.items():
        matches = pattern.findall(text)
        hits[name] = len(matches)

    for name, count in hits.items():
        report.append(f"- {name}: {count}")

    report.append("")
    sample_lines = []
    for i, line in enumerate(text.splitlines(), start=1):
        if any(p.search(line) for p in PATTERNS.values()):
            sample_lines.append(f"{i}: {line[:180]}")
        if len(sample_lines) >= 12:
            break

    if sample_lines:
        report.append("Sample flagged lines:")
        report.extend(sample_lines)
    else:
        report.append("Sample flagged lines: none")

    report.append("")

out = ROOT / "audits" / "SYSTEM_REALITY_CHECK.md"
out.write_text("\n".join(report), encoding="utf-8")
print(f"OK: {out} written")
