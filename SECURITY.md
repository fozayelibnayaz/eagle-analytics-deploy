# Security Notice - Eagle 3D Streaming Analytics Hub

## URGENT: Rotate exposed API keys

Prior deployments committed secrets.toml values to Git or logged them in
GitHub Actions output. Rotate ALL of these keys immediately:

| Service | Where to rotate | Priority |
|---|---|---|
| Groq API key | https://console.groq.com/keys | HIGH |
| Gemini API key | https://aistudio.google.com/apikey | HIGH |
| Telegram bot token | Message @BotFather then /revoke then /newtoken | HIGH |
| Gmail app password | https://myaccount.google.com/apppasswords | MED |
| Google Service Account | GCP Console > IAM > SA > Keys > delete + create new | MED |
| YouTube API key | GCP Console > Credentials > regenerate | MED |
| Stripe cookies | Re-export from browser (expire every 4-6 weeks) | LOW |
| LinkedIn cookies | Re-export from browser (same) | LOW |
| KPI dashboard password | Change in Firebase auth (if leaked) | MED |

## After rotation

1. Update .streamlit/secrets.toml with new values
2. Restart the Streamlit app
3. Test pipeline: ./run_pipeline_local.sh
4. Verify .gitignore excludes secrets:
   grep -q secrets.toml .gitignore && echo OK || echo MISSING

## Local-only architecture

This project is now 100% local:

- Database: MongoDB on localhost:27017 (no cloud)
- Pipeline: runs on your MacBook via ./run_pipeline_local.sh
- Streamlit: streamlit run app.py (localhost)
- GitHub Actions: DISABLED (moved to .github/workflows_disabled/)

## What NOT to commit

Already in .gitignore, but double-check:

- .streamlit/secrets.toml
- google_creds.json
- stripe_cookies.json
- data_output/linkedin_cookies.json
- data_output/linkedin_session_state.json
- kpi_storage_state.json
- venv/
- logs/

## Monthly checks

Any secrets accidentally committed?
  git log --all -p | grep -iE "(sk-|gsk_|AIza|bot[0-9]+:)" | head

Recent access log:
  python3 -c "from access_control import get_access_logs; import json; print(json.dumps(get_access_logs(50), indent=2))"
