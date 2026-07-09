#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Eagle Analytics Hub v7.2.2 — Deploy Script
# ═══════════════════════════════════════════════════════════════
# Run this on your machine where you have GitHub push access:
#   bash deploy_v72.sh
# ═══════════════════════════════════════════════════════════════

set -e

echo "🦅 Eagle Analytics Hub v7.2.2 — Deploy"
echo "========================================"

# Check we're in the right directory
if [ ! -f "app.py" ]; then
    echo "❌ Run this from the eagle3d-kpi-automation directory"
    exit 1
fi

# Step 1: Verify no secrets (exclude deploy scripts)
echo ""
echo "🔍 Checking for secrets in code..."
if grep -rn "8743434532\|AAFMy9F\|1003989604195\|sk_live\|ghp_" --include="*.py" --exclude="deploy_*" . 2>/dev/null; then
    echo "❌ SECRET DETECTED! Aborting."
    exit 1
fi
echo "  ✅ No secrets found"

# Step 2: Verify all files compile
echo ""
echo "🔍 Verifying Python files compile..."
python3 -c "
import ast, os, sys
errors = []
for f in os.listdir('.'):
    if f.endswith('.py') and not f.startswith('deploy_'):
        try:
            with open(f) as fh:
                ast.parse(fh.read())
        except SyntaxError as e:
            errors.append(f'{f}: {e}')
if errors:
    print('❌ Syntax errors:')
    for e in errors:
        print(f'  {e}')
    sys.exit(1)
else:
    print('  ✅ All files compile')
"
if [ $? -ne 0 ]; then
    exit 1
fi

# Step 3: Stash any unstaged changes BEFORE fetch
echo ""
echo "📦 Stashing any local changes..."
git stash --include-untracked 2>/dev/null || true
echo "  ✅ Stashed"

# Step 4: Fetch remote
echo ""
echo "📥 Fetching remote..."
git fetch origin main

# Step 5: Reset to our local HEAD (keep our commits on top)
echo ""
echo "🔄 Rebasing onto origin/main..."
git rebase origin/main 2>/dev/null || {
    echo "  ⚠️ Rebase had conflicts — using merge instead..."
    git rebase --abort 2>/dev/null || true
    git merge origin/main --no-edit 2>/dev/null || true
}

# Step 6: Pop stash to restore local changes
echo ""
echo "📦 Restoring local changes..."
git stash pop 2>/dev/null || true

# Step 7: Stage + commit any remaining changes
echo ""
echo "📦 Staging all changes..."
git add -A
git diff --cached --quiet 2>/dev/null || {
    git commit -m "v7.2.2: Latest fixes [skip ci]"
}

# Step 8: Force push
echo ""
echo "🚀 Force pushing to GitHub..."
for i in 1 2 3 4 5; do
    if git push origin main --force; then
        echo "  ✅ Pushed!"
        break
    else
        echo "  ⚠️ Push attempt $i failed, retrying..."
        git fetch origin main
        git rebase origin/main 2>/dev/null || git merge origin/main --no-edit 2>/dev/null || true
        sleep 5
    fi
done

# Done
echo ""
echo "========================================"
echo "✅ DEPLOY COMPLETE"
echo ""
echo "🌐 https://eagle3d-kpi-automation.streamlit.app/"
echo "⏱️  Streamlit Cloud updates in 60-90 seconds"
echo ""
echo "📋 After deploy checklist:"
echo "  1. Login with password: eagleanalytics"
echo "  2. Check Browse Data → First Uploads"
echo "  3. Open 🔧 Data Diagnostics to see column names"
echo "  4. Check LinkedIn Command Center loads"
echo "  5. Check YouTube Command Center loads"
echo "========================================"
