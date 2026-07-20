from pathlib import Path
from datetime import datetime
import subprocess

ROOT = Path.cwd()
BACKUPS = ROOT / "backups"
BACKUPS.mkdir(exist_ok=True)

def backup(path: Path):
    if path.exists():
        b = BACKUPS / f"{path.name}.restore_old_ui_shell.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
        b.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        print(f"BACKUP: {path} -> {b}")

def restore_from_git(commit: str, src: str, dest: Path):
    result = subprocess.run(
        ["git", "show", f"{commit}:{src}"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not restore {src} from {commit}: {result.stderr}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(result.stdout, encoding="utf-8")
    print(f"✅ restored {src} from {commit} -> {dest}")

# Backup current files
for fname in ["app.py", "pages_registry.py", "static/monetra.css"]:
    backup(ROOT / fname)

# Restore old UI shell
restore_from_git("11a5486", "app.py", ROOT / "app.py")
restore_from_git("11a5486", "pages_registry.py", ROOT / "pages_registry.py")
restore_from_git("11a5486", "static/monetra.css", ROOT / "static" / "monetra.css")

# Apply only minimal KPI/data fixes
for fname in ["app.py", "pages_registry.py"]:
    p = ROOT / fname
    text = p.read_text(encoding="utf-8", errors="ignore")

    # Use current daily_kpis fields
    text = text.replace("signups_accepted", "signups")
    text = text.replace("uploads_accepted", "first_uploads")
    text = text.replace("paid_accepted", "new_paid_customers")

    # Fix label only
    text = text.replace("New New Paying Customers", "New Paying Customers")
    text = text.replace('c3.metric("💳 Paid",', 'c3.metric("💳 New Paying Customers",')
    text = text.replace('("paid_accepted",    "Paid",', '("new_paid_customers",    "New Paying Customers",')
    text = text.replace('("new_paid_customers",    "Paid",', '("new_paid_customers",    "New Paying Customers",')

    # Keep old route name if needed, but normalize safe call in main
    text = text.replace("_route(current_page, user_email)", "route(current_page, user_email)")
    text = text.replace("def _route(page: str, user_email: str) -> None:", "def route(page: str, user_email: str) -> None:")

    p.write_text(text, encoding="utf-8")
    print(f"✅ patched KPI fields in {fname}")

print("✅ old UI shell restored with minimal KPI field fixes")
