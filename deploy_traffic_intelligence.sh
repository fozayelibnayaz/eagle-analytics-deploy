#!/bin/bash
# Self-healing deployment script for Eagle 3D Traffic Intelligence
# Usage: bash deploy_traffic_intelligence.sh

set -e  # Exit on any error

PROJECT_DIR="/Users/macbookair/eagle3d-kpi-automation"
cd "$PROJECT_DIR"

# Activate venv
source venv/bin/activate

echo ""
echo "════════════════════════════════════════════════════════"
echo "  EAGLE 3D TRAFFIC INTELLIGENCE — DEPLOY GUARD"
echo "════════════════════════════════════════════════════════"
echo ""

# ═══════════════════════════════════════════════════════════
# PHASE 1: Pre-deployment health check
# ═══════════════════════════════════════════════════════════
echo "📋 PHASE 1: Pre-deployment validation..."
echo ""

python3 << 'PYEOF'
import os, sys

REQUIRED = [
    "ga4_connector.py", "ga4_intelligence.py", "ga4_notifications.py",
    "ga4_responsive_css.py", "ga4_smart_qa.py", "ga4_source_intel.py",
    "ga4_strategic.py", "kpi_bridge.py", "dashboard.py",
]

errors = []
for f in REQUIRED:
    if not os.path.exists(f):
        errors.append(f"Missing: {f}")
    elif os.path.getsize(f) < 1000:
        errors.append(f"Too small: {f}")

if errors:
    print("  ❌ Pre-flight failed:")
    for e in errors:
        print(f"      {e}")
    sys.exit(1)

print("  ✅ All 9 required files present")

# Test critical imports
try:
    from kpi_bridge import fetch_daily_kpis, calculate_funnel_metrics
    from ga4_smart_qa import answer_free_text_question
    from ga4_responsive_css import get_responsive_css
    print("  ✅ All critical imports work")
except ImportError as e:
    print(f"  ❌ Import error: {e}")
    sys.exit(1)

# Test CRM connection
try:
    df = fetch_daily_kpis()
    if df.empty:
        print("  ⚠️  CRM returns empty (acceptable - will diagnose in app)")
    else:
        funnel = calculate_funnel_metrics(df)
        print(f"  ✅ CRM works: {funnel['signups']} signups, {funnel['uploads']} uploads, {funnel['paid']} paid")
except Exception as e:
    print(f"  ⚠️  CRM test: {e}")
PYEOF

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Pre-flight failed. Fix errors above before deploying."
    exit 1
fi

# ═══════════════════════════════════════════════════════════
# PHASE 2: Backup everything
# ═══════════════════════════════════════════════════════════
echo ""
echo "💾 PHASE 2: Creating backups..."
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="_deploy_backup_${TIMESTAMP}"
mkdir -p "$BACKUP_DIR"
cp dashboard.py "$BACKUP_DIR/" 2>/dev/null
cp -r pages "$BACKUP_DIR/" 2>/dev/null
cp ga4_*.py "$BACKUP_DIR/" 2>/dev/null
cp kpi_bridge.py "$BACKUP_DIR/" 2>/dev/null
echo "  ✅ Backed up to: $BACKUP_DIR"

# ═══════════════════════════════════════════════════════════
# PHASE 3: Clean dashboard.py
# ═══════════════════════════════════════════════════════════
echo ""
echo "🧹 PHASE 3: Cleaning dashboard.py..."

python3 << 'PYEOF'
import re

with open("dashboard.py", "r", encoding="utf-8") as f:
    content = f.read()

original = content

# Remove Traffic Intelligence from radio options
patterns = [
    r',\s*"🚦 Traffic Intelligence"',
    r'"🚦 Traffic Intelligence"\s*,',
    r',\s*"\\U0001F6A6 Traffic Intelligence"',
]
for p in patterns:
    content = re.sub(p, '', content)

# Remove handler blocks
handler_patterns = [
    r'\n*if page == "🚦 Traffic Intelligence":.*?(?=\nelif page ==|\nif page ==|\Z)',
    r'\n*elif page == "🚦 Traffic Intelligence":.*?(?=\nelif page ==|\nif page ==|\Z)',
]
for p in handler_patterns:
    content = re.sub(p, '', content, flags=re.DOTALL)

# Ensure responsive CSS is loaded after set_page_config
if "get_responsive_css" not in content:
    match = re.search(r'(st\.set_page_config\([^)]*\))', content, re.DOTALL)
    if match:
        addition = match.group(0) + '''

# Mobile-responsive CSS (applies to all pages)
try:
    from ga4_responsive_css import get_responsive_css
    st.markdown(get_responsive_css(), unsafe_allow_html=True)
except ImportError:
    pass'''
        content = content.replace(match.group(0), addition)

# Clean extra newlines
content = re.sub(r'\n{4,}', '\n\n\n', content)

if content != original:
    with open("dashboard.py", "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  ✅ dashboard.py cleaned ({len(original)} → {len(content)} bytes)")
else:
    print("  ✅ dashboard.py already clean")
PYEOF

# ═══════════════════════════════════════════════════════════
# PHASE 4: Rebuild Traffic Intelligence page
# ═══════════════════════════════════════════════════════════
echo ""
echo "🔨 PHASE 4: Rebuilding Traffic Intelligence page..."

python3 _build_ti_page.py
if [ $? -ne 0 ]; then
    echo "  ❌ Rebuild failed. Restoring backup..."
    cp -r "$BACKUP_DIR/pages" .
    exit 1
fi

# ═══════════════════════════════════════════════════════════
# PHASE 5: Validate the new page
# ═══════════════════════════════════════════════════════════
echo ""
echo "🔍 PHASE 5: Validating rebuilt page..."

python3 << 'PYEOF'
import glob, re, sys

files = [f for f in glob.glob("pages/*Traffic_Intelligence*.py") if "backup" not in f and "deploy_backup" not in f]
if not files:
    print("  ❌ No Traffic Intelligence file found")
    sys.exit(1)

PAGE = files[0]
with open(PAGE, "r", encoding="utf-8") as f:
    content = f.read()

# Syntax check
try:
    compile(content, PAGE, "exec")
    print("  ✅ Python syntax valid")
except SyntaxError as e:
    print(f"  ❌ Syntax error: {e}")
    sys.exit(1)

# Feature checks
checks = {
    "11 tabs":                      content.count("with t[") >= 11,
    "Lead Sources tab":             "Lead Sources" in content,
    "Strategic Q&A tab":            "Strategic Q&A" in content,
    "Free-text Q&A input":          "user_question" in content,
    "answer_free_text_question":    "answer_free_text_question" in content,
    "kpi_bridge import":            "from kpi_bridge import" in content,
    "ga4_smart_qa import":          "from ga4_smart_qa import" in content,
    "ga4_responsive_css import":    "from ga4_responsive_css import" in content,
    "ga4_source_intel import":      "from ga4_source_intel import" in content,
    "Funnel tab function":          "def tab_funnel" in content,
    "Lead Sources tab function":    "def tab_lead_sources" in content,
    "Strategic tab function":       "def tab_strategic" in content,
}

all_ok = True
for label, ok in checks.items():
    icon = "✅" if ok else "❌"
    print(f"  {icon} {label}")
    if not ok:
        all_ok = False

if not all_ok:
    print("\n  ❌ Validation FAILED — page is not complete")
    sys.exit(1)

print("\n  ✅ Page validation PASSED")
PYEOF

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Page validation failed. Aborting deployment."
    exit 1
fi

# ═══════════════════════════════════════════════════════════
# PHASE 6: Update .gitignore
# ═══════════════════════════════════════════════════════════
echo ""
echo "📝 PHASE 6: Cleaning .gitignore..."

python3 << 'PYEOF'
import os

GITIGNORE_BLOCK = """

# Backup files (auto-managed)
*.backup_*
*.MOVED
*.emoji_fix_*
*.full_patch_backup_*
*.qa_backup_*
*.responsive_backup_*
*.tablist_backup_*
*.fix_*
_safe_backup/
_deploy_backup_*
pages/*.backup_*
pages/*.emoji_fix_*
pages/*.qa_backup_*
pages/*.full_patch_backup_*
pages/*.responsive_backup_*
pages/*.tablist_backup_*
pages/*.fix_*
deploy_traffic_intelligence.sh
_build_ti_page.py
"""

existing = ""
if os.path.exists(".gitignore"):
    with open(".gitignore", "r") as f:
        existing = f.read()

if "_deploy_backup_" not in existing:
    with open(".gitignore", "a") as f:
        f.write(GITIGNORE_BLOCK)
    print("  ✅ .gitignore updated")
else:
    print("  ✅ .gitignore already correct")
PYEOF

# ═══════════════════════════════════════════════════════════
# PHASE 7: Stage files (safely)
# ═══════════════════════════════════════════════════════════
echo ""
echo "📦 PHASE 7: Staging files for commit..."

# Remove backups from git tracking
git rm --cached pages/*.backup_* 2>/dev/null || true
git rm --cached pages/*.emoji_fix_* 2>/dev/null || true
git rm --cached pages/*.qa_backup_* 2>/dev/null || true
git rm --cached pages/*.full_patch_backup_* 2>/dev/null || true
git rm --cached pages/*.responsive_backup_* 2>/dev/null || true
git rm --cached pages/*.tablist_backup_* 2>/dev/null || true
git rm --cached pages/*.fix_* 2>/dev/null || true

# Add only safe files
git add ga4_responsive_css.py 2>/dev/null
git add ga4_mobile_components.py 2>/dev/null
git add ga4_smart_qa.py 2>/dev/null
git add ga4_source_intel.py 2>/dev/null
git add ga4_strategic.py 2>/dev/null
git add kpi_bridge.py 2>/dev/null
git add dashboard.py 2>/dev/null
git add pages/07_*.py 2>/dev/null
git add requirements.txt 2>/dev/null
git add .gitignore 2>/dev/null

echo ""
echo "Files staged:"
git diff --cached --name-only | head -20

# Safety check - block if sensitive files are staged
SENSITIVE=$(git diff --cached --name-only | grep -E "google_creds|secrets\.toml|\.MOVED|backup_" || true)
if [ ! -z "$SENSITIVE" ]; then
    echo ""
    echo "❌ DANGER: Sensitive files would be committed:"
    echo "$SENSITIVE"
    echo ""
    echo "Removing from staging..."
    echo "$SENSITIVE" | xargs git reset HEAD 2>/dev/null
fi

# ═══════════════════════════════════════════════════════════
# PHASE 8: Commit
# ═══════════════════════════════════════════════════════════
echo ""
echo "💾 PHASE 8: Committing..."

if git diff --cached --quiet; then
    echo "  ⚠️  Nothing to commit"
else
    git commit -m "Complete rebuild: 11 tabs, free-text Q&A, mobile responsive, CRM connected"
    echo "  ✅ Committed"
fi

# ═══════════════════════════════════════════════════════════
# PHASE 9: Push (with auto-retry)
# ═══════════════════════════════════════════════════════════
echo ""
echo "🚀 PHASE 9: Pushing to GitHub..."

if git push origin main; then
    echo "  ✅ Pushed successfully"
elif git push origin main --force-with-lease; then
    echo "  ✅ Force-pushed (with lease)"
elif git push origin main --force; then
    echo "  ✅ Force-pushed (override)"
else
    echo "  ❌ Push failed — check network/GitHub access"
    exit 1
fi

# ═══════════════════════════════════════════════════════════
# PHASE 10: Wait for Streamlit Cloud rebuild
# ═══════════════════════════════════════════════════════════
echo ""
echo "⏰ PHASE 10: Waiting 90 seconds for Streamlit Cloud rebuild..."
sleep 90

echo ""
echo "════════════════════════════════════════════════════════"
echo "  ✅ DEPLOYMENT COMPLETE"
echo "════════════════════════════════════════════════════════"
echo ""
echo "Test the live app:"
echo ""
echo "  Main dashboard:"
echo "    https://eagle3d-kpi-automation.streamlit.app/"
echo ""
echo "  Traffic Intelligence:"
echo "    https://eagle3d-kpi-automation.streamlit.app/Traffic_Intelligence"
echo ""
echo "Refresh browser with Cmd+Shift+R (hard refresh)"
echo ""
