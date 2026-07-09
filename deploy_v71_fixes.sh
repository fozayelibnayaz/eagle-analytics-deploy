#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# Eagle Analytics Hub — v7.1 DEPLOY & VERIFY
# Run this on your LOCAL machine where the git repo is cloned
# ═══════════════════════════════════════════════════════════════════════
set -e

echo "🦅 Eagle Analytics Hub — v7.1 Deploy"
echo "====================================="

# 1. Pull latest (pipeline may have auto-committed state files)
echo ""
echo "📥 Step 1: Pulling latest..."
git pull --rebase origin main || true

# 2. Stage all changes
echo ""
echo "📦 Step 2: Staging all changes..."
git add -A

# 3. Commit
echo ""
echo "💾 Step 3: Committing..."
git commit -m "v7.1: Combined Sources smart dedup + Stripe paid count fix + pipeline auto-run

FIX 1: Combined Sources now uses source_normalizer for smart dedup
- Google/google/Google Search Console -> single Google row
- LinkedIn/linkedin -> single LinkedIn row
- AI/ChatGPT/Claude/Gemini -> single AI Tools row

FIX 2: Stripe paid count - customers with First payment date
are now ACCEPTED even if Total spend is \$0
- Added Payment Count field support
- 3-tier acceptance: First payment > Payment Count > Spend

FIX 3: Stripe date priority unified across all files
- First payment -> row_date_used -> Created (consistent)

FIX 4: Auto-trigger toast now says refresh in ~5 min" --allow-empty

# 4. Push
echo ""
echo "🚀 Step 4: Pushing to GitHub..."
for i in 1 2 3; do
    if git push origin main; then
        echo "✅ Pushed!"
        break
    else
        echo "Push $i failed, retrying..."
        git pull --rebase origin main || true
        sleep 3
    fi
done

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "✅ DEPLOYED! Now verify:"
echo ""
echo "STEP 1: Enable GitHub Actions workflow"
echo "  → https://github.com/fozayelibnayaz/eagle3d-kpi-automation/actions"
echo "  → Click 'I understand my workflows, go ahead and enable them'"
echo "  → Make sure 'Daily KPI Pipeline' is ACTIVE"
echo ""
echo "STEP 2: Manually trigger pipeline once"
echo "  → Click 'Daily KPI Pipeline' → 'Run workflow' → 'Run workflow'"
echo "  → Wait ~5 min for green checkmark"
echo ""
echo "STEP 3: Verify Stripe cookies secret exists"
echo "  → https://github.com/fozayelibnayaz/eagle3d-kpi-automation/settings/secrets/actions"
echo "  → STRIPE_COOKIES_JSON must be set"
echo "  → If missing: export cookies from browser as JSON array"
echo ""
echo "STEP 4: Check dashboard"
echo "  → https://eagle3d-kpi-automation.streamlit.app/"
echo "  → Paid count should now be higher (First payment date customers)"
echo "  → Combined Sources should show deduplicated rows"
echo ""
echo "STEP 5: Check Telegram"
echo "  → Should receive per-subsystem messages after pipeline runs"
echo "  → Stripe section should show updated paid counts"
echo "════════════════════════════════════════════════════════════════"
