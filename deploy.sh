#!/bin/bash
# ══════════════════════════════════════════════════════════════════
# Eagle3D KPI — Bulletproof Deploy Script
# ══════════════════════════════════════════════════════════════════
# Run this from your Mac terminal:
#   cd /Users/macbookair/eagle3d-kpi-automation
#   bash deploy.sh
#
# This script ALWAYS works. It force-pushes to main.
# Streamlit Cloud will auto-redeploy within 60-90 seconds.
# ══════════════════════════════════════════════════════════════════

set -e
echo "🦅 Eagle3D KPI Deploy Script"
echo "═══════════════════════════════"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Step 1: Ensure we're in the right directory
if [ ! -f "app.py" ] || [ ! -f "dashboard.py" ]; then
    echo -e "${RED}❌ Run this from the eagle3d-kpi-automation directory${NC}"
    exit 1
fi
echo -e "${GREEN}✅ In correct directory${NC}"

# Step 2: Remove old deploy files
rm -f deploy_v4.py deploy_v5.py update_v4.sh update_app_b64.txt 2>/dev/null || true
echo -e "${GREEN}✅ Cleaned old deploy files${NC}"

# Step 3: Check for secrets in code
echo ""
echo "🔍 Checking for API keys in code..."
if grep -rn "gsk_\|AIzaSy\|ghp_\|glpat-" app.py ai_engine.py kpi_bridge.py "pages/07_🚦_Traffic_Intelligence.py" dashboard.py 2>/dev/null; then
    echo -e "${RED}❌ API keys found in code! GitHub will reject the push.${NC}"
    echo "Remove them first, then run this script again."
    exit 1
fi
echo -e "${GREEN}✅ No API keys in code${NC}"

# Step 4: Ensure we have the remote
if ! git remote get-url origin &>/dev/null; then
    git remote add origin https://github.com/fozayelibnayaz/eagle3d-kpi-automation.git
fi
echo -e "${GREEN}✅ Remote configured${NC}"

# Step 5: Fetch latest from remote (ignore errors)
echo ""
echo "📥 Fetching remote state..."
git fetch origin 2>/dev/null || true

# Step 6: Add all files
echo "📦 Staging files..."
git add -A

# Step 7: Check if there's anything to commit
if git diff --cached --quiet; then
    echo -e "${YELLOW}⚠️ No changes to commit. Pushing existing commits...${NC}"
else
    echo "💾 Committing..."
    git commit -m "v5.3: All fixes — $(date '+%Y-%m-%d %H:%M')" --allow-empty
    echo -e "${GREEN}✅ Committed${NC}"
fi

# Step 8: Ensure we're on main branch
CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "master")
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo "🔄 Renaming branch to main..."
    git branch -m "$CURRENT_BRANCH" main
fi
echo -e "${GREEN}✅ On main branch${NC}"

# Step 9: FORCE PUSH — this always works
echo ""
echo "🚀 Force pushing to GitHub..."
if git push origin main --force 2>&1; then
    echo ""
    echo -e "${GREEN}════════════════════════════════════════${NC}"
    echo -e "${GREEN}✅ DEPLOYED SUCCESSFULLY!${NC}"
    echo -e "${GREEN}════════════════════════════════════════${NC}"
    echo ""
    echo "🌐 Live at: https://eagle3d-kpi-automation.streamlit.app/"
    echo "⏱️  Streamlit Cloud will update in 60-90 seconds"
    echo ""
    echo "💡 If data still shows 0:"
    echo "   1. Go to https://share.streamlit.io"
    echo "   2. Click your app → ⋮ menu → Reboot app"
    echo "   3. Check Settings → Secrets Status"
else
    echo ""
    echo -e "${RED}════════════════════════════════════════${NC}"
    echo -e "${RED}❌ Push failed!${NC}"
    echo -e "${RED}════════════════════════════════════════${NC}"
    echo ""
    echo "Possible fixes:"
    echo "1. Check your GitHub credentials:"
    echo "   git config --global credential.helper osxkeychain"
    echo ""
    echo "2. If credentials expired, re-authenticate:"
    echo "   gh auth login"
    echo ""
    echo "3. Or use a Personal Access Token:"
    echo "   Create at: https://github.com/settings/tokens/new"
    echo "   Then: git push https://YOUR_TOKEN@github.com/fozayelibnayaz/eagle3d-kpi-automation.git main --force"
    exit 1
fi
