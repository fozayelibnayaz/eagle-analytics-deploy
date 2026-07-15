# Free Cloud Deployment Bundle

## Architecture
- Frontend: Render free web service (Streamlit)
- Backend webhook API: Render free web service (FastAPI)
- Database: MongoDB Atlas M0
- Scheduled jobs: GitHub Actions cron
- Free URLs:
  - https://<render-ui>.onrender.com
  - https://<render-api>.onrender.com

## One-time actions still required
1. Create MongoDB Atlas M0 cluster and obtain MONGO_URI
2. Push this repo to GitHub
3. Run: python3 scripts/push_github_secrets.py
4. In Render:
   - New + Blueprint
   - connect this repo
   - deploy render.yaml
   - set missing env vars if Render asks
5. Use the Render API URL for backend webhook

## After backend developer starts posting
- POST target: https://<render-api>.onrender.com/webhook
- You should receive Telegram webhook receipt alerts
- You can verify with:
  - python3 scripts/check_webhook_ingest.py

## Cutover rule
After webhook is trusted:
- stop using signups/uploads/payments scraping as primary source
- webhook becomes source of truth
- keep LinkedIn/YouTube external sync jobs active
