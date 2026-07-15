from pathlib import Path
import re
import sys

ROOT = Path.cwd()
SECRETS = ROOT / ".streamlit" / "secrets.toml"

if not SECRETS.exists():
    print(f"❌ Missing file: {SECRETS}", file=sys.stderr)
    sys.exit(1)

content = SECRETS.read_text(encoding="utf-8")
m = re.search(r'^API_KEY\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)

if not m:
    print("❌ API_KEY not found in .streamlit/secrets.toml", file=sys.stderr)
    sys.exit(1)

api_key = m.group(1).strip()
BASE = "https://unsoiling-tendenciously-marge.ngrok-free.dev"

doc = f"""# Webhook Integration Guide

For: Aninda Sadman (Backend Developer)
Direction: Your backend POSTs data to Fozayel's API.
Purpose: Sync signups/uploads/payments to the analytics dashboard in real time.

--------------------------------------------------

TL;DR

POST to:
{BASE}/webhook

Header:
X-API-Key: {api_key}

Body:
{{
  "source": "your-backend-name",
  "data": [
    {{ "type": "signup",  "info": {{ ... }} }},
    {{ "type": "upload",  "info": {{ ... }} }},
    {{ "type": "payment", "info": {{ ... }} }}
  ]
}}

--------------------------------------------------

Example curl

curl -X POST "{BASE}/webhook" \\
  -H "X-API-Key: {api_key}" \\
  -H "Content-Type: application/json" \\
  -d '{{
    "source": "aninda-backend",
    "data": [
      {{"type": "signup", "info": {{"id": "sig-abc123", "email": "newuser@example.com", "signup_date": "2026-07-14", "lead_source": "google"}}}},
      {{"type": "upload", "info": {{"id": "up-xyz789", "email": "newuser@example.com", "upload_date": "2026-07-14", "app_name": "MyApp"}}}},
      {{"type": "payment", "info": {{"id": "pay-def456", "email": "newuser@example.com", "first_payment_date": "2026-07-14", "amount": 29.00}}}}
    ]
  }}'

--------------------------------------------------

Helper endpoints

Test:
{BASE}/webhook/test

Log:
{BASE}/webhook/log?limit=50

Docs:
{BASE}/docs

--------------------------------------------------

Message to send Aninda

Bhai, webhook ready to receive data.

POST endpoint:
{BASE}/webhook

Interactive docs:
{BASE}/docs

Send POST from your backend whenever signup/upload/payment happens.

Body:
{{"data": [{{"type": "signup", "info": {{...}}}}, ...]}}

Full guide + curl + Postman setup in attached WEBHOOK_GUIDE.md.

Quick test:
GET /webhook/test

Data lands in Mongo instantly. Telegram alert fires per call.
Dedup by email — safe to re-send same item.

Ping after you POST once — I can confirm data landed on my side.
"""

out = ROOT / "WEBHOOK_GUIDE.md"
out.write_text(doc, encoding="utf-8")

readme = ROOT / "README_WEBHOOK_FIX.md"
readme.write_text(
    "# Webhook Fix README\\n\\n"
    "Use this exact command to generate the guide:\\n"
    "python3 scripts/generate_webhook_guide.py\\n",
    encoding="utf-8"
)

(Path("skills")).mkdir(exist_ok=True)

Path("skills/terminal-paste-debugging.md").write_text(
    "# Skill: Terminal Paste Debugging\\n"
    "- Never paste Markdown filenames into terminal\\n"
    "- Use plain filenames only\\n"
    "- If you see heredoc> or >, press Ctrl+C\\n",
    encoding="utf-8"
)

Path("skills/webhook-doc-generation.md").write_text(
    "# Skill: Webhook Doc Generation\\n"
    "- Read API_KEY from .streamlit/secrets.toml\\n"
    "- Generate WEBHOOK_GUIDE.md\\n"
    "- Print success output\\n",
    encoding="utf-8"
)

print(f"OK: {out.name} written")
print("OK: README_WEBHOOK_FIX.md written")
print("OK: skills created")
