#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Eagle3D KPI System — Local Setup & Run Script
# Run this on your MacBook terminal
# ═══════════════════════════════════════════════════════════════

echo "🦅 Eagle3D KPI System — Local Setup"
echo "════════════════════════════════════════════════════════"

# Navigate to project
cd "$(dirname "$0")"

# Step 1: Pull remote changes
echo ""
echo "📦 Step 1: Syncing with GitHub..."
git stash 2>/dev/null
git pull --rebase origin main 2>&1
if [ $? -ne 0 ]; then
    echo "⚠️  Pull had conflicts. Resolving..."
    # Accept our changes for data files
    for f in data_output/upload_history.json data_output/upload_registry.json data_output/domain_cache.json; do
        if [ -f "$f" ]; then
            git checkout --ours "$f" 2>/dev/null
        fi
    done
    git add -A 2>/dev/null
    git rebase --continue 2>/dev/null
fi
git stash pop 2>/dev/null

# Step 2: Install dependencies
echo ""
echo "📦 Step 2: Installing dependencies..."
pip install -r requirements.txt 2>/dev/null || pip3 install -r requirements.txt
pip install scikit-learn email-validator dnspython 2>/dev/null || true

# Step 3: Test all modules
echo ""
echo "🧪 Step 3: Testing modules..."
python3 -c "
modules = [
    'source_normalizer', 'ai_engine', 'prediction_engine', 'report_generator',
    'first_upload_logic', 'email_intelligence', 'dedup_engine',
    'kpi_bridge', 'manual_override_engine', 'process_data',
]
ok = 0
for m in modules:
    try:
        __import__(m)
        print(f'  ✅ {m}')
        ok += 1
    except Exception as e:
        print(f'  ⚠️  {m}: {str(e)[:50]}')
print(f'  {ok}/{len(modules)} modules OK')
"

# Step 4: Run
echo ""
echo "════════════════════════════════════════════════════════"
echo "🚀 Step 4: Starting Streamlit"
echo ""
echo "  Run ONE of these commands:"
echo ""
echo "  Option A — New Unified App (RECOMMENDED):"
echo "    streamlit run app.py --server.port 8501"
echo ""
echo "  Option B — Original Dashboard:"
echo "    streamlit run dashboard.py --server.port 8501"
echo ""
echo "  Option C — Traffic Intelligence only:"
echo "    streamlit run 'pages/07_🚦_Traffic_Intelligence.py' --server.port 8502"
echo ""
echo "════════════════════════════════════════════════════════"
echo ""
echo "🌐 Open browser: http://localhost:8501"
echo ""
echo "🤖 To enable AI (optional):"
echo "  export GROQ_API_KEY=your_key_here    # Get free: https://console.groq.com"
echo "  export GEMINI_API_KEY=your_key_here  # Get free: https://aistudio.google.com"
echo ""
echo "📤 To push to GitHub:"
echo "  git push origin main"
echo "  # or if rejected:"
echo "  git push --force-with-lease origin main"
echo ""
echo "════════════════════════════════════════════════════════"
