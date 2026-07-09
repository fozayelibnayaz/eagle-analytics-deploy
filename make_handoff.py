import re
from pathlib import Path

content = Path(".streamlit/secrets.toml").read_text()
m = re.search(r'^API_KEY\s*=\s*"([^"]+)"', content, re.MULTILINE)
api_key = m.group(1) if m else "MISSING"

BASE = "https://unsoiling-tendenciously-marge.ngrok-free.dev"

md = "# Eagle 3D Streaming - Backend API Handoff\n\n"
md += "**Recipient:** Aninda Sadman (Backend Developer)\n"
md += "**API Owner:** Fozayel Ibn Ayaz\n"
md += "**Status:** LIVE & production-ready\n\n"
md += "---\n\n"

md += "## Quick Reference\n\n"
md += "| Item | Value |\n"
md += "|---|---|\n"
md += f"| Base URL | `{BASE}` |\n"
md += f"| Interactive docs | {BASE}/docs |\n"
md += f"| Auth header | `X-API-Key: {api_key}` |\n"
md += f"| Health check (no auth) | `{BASE}/health` |\n"
md += "| Response format | JSON |\n"
md += "| Data freshness | Every 6 hours, live queries always fresh |\n\n"

md += "## Important: ngrok Browser Warning\n\n"
md += "If you visit the URL in a browser, ngrok shows a one-time warning page.\n"
md += "**This does NOT affect API calls.** Curl/Python/Node requests work directly.\n\n"
md += "To skip the warning in code (recommended), add this header to every request:\n"
md += "```\nngrok-skip-browser-warning: any\n```\n\n"

md += "## 30-Second Test\n\n"
md += "```bash\n"
md += f"curl -H 'X-API-Key: {api_key}' \\\n"
md += "     -H 'ngrok-skip-browser-warning: 1' \\\n"
md += f"     '{BASE}/api/kpis/summary?start=2026-07-01&end=2026-07-31'\n"
md += "```\n\n"
md += "Returns JSON with signups / uploads / paying customers / revenue / conversion rates.\n\n"

md += "## All Endpoints\n\n"
md += "### System\n\n"
md += "| Method | Path | Auth |\n"
md += "|---|---|---|\n"
md += "| GET | `/` | No |\n"
md += "| GET | `/health` | No |\n"
md += "| GET | `/api/pipeline/health` | Yes |\n\n"

md += "### KPIs\n\n"
md += "| Path | Query Params |\n"
md += "|---|---|\n"
md += "| `/api/kpis/summary` | `start`, `end` (YYYY-MM-DD) |\n"
md += "| `/api/kpis/daily` | `start`, `end` |\n\n"

md += "### Raw Data\n\n"
md += "| Path | Query Params |\n"
md += "|---|---|\n"
md += "| `/api/signups` | status, start, end, limit |\n"
md += "| `/api/uploads` | status, start, end, limit |\n"
md += "| `/api/payments` | status, customer_type, start, end, limit |\n\n"
md += "- `status`: ACCEPTED / REJECTED / PENDING\n"
md += "- `customer_type`: NEW_CUSTOMER / RECURRING\n\n"

md += "### Attribution\n\n"
md += "| Path | Description |\n"
md += "|---|---|\n"
md += "| `/api/attribution/signups` | Signups by normalized source |\n"
md += "| `/api/attribution/uploads` | Uploads by source |\n"
md += "| `/api/attribution/paying?new_only=true` | Paying customers by source |\n"
md += "| `/api/attribution/revenue?new_only=false` | Revenue by source |\n"
md += "| `/api/attribution/full-report?days=30` | All 4 combined |\n\n"

md += "### YouTube\n\n"
md += "| Path |\n"
md += "|---|\n"
md += "| `/api/youtube/channel` |\n"
md += "| `/api/youtube/videos?limit=100&sort_by=views` |\n"
md += "| `/api/youtube/analytics?start=&end=` |\n\n"

md += "### LinkedIn\n\n"
md += "| Path |\n"
md += "|---|\n"
md += "| `/api/linkedin/latest` |\n"
md += "| `/api/linkedin/posts?limit=50` |\n"
md += "| `/api/linkedin/followers?limit=90` |\n\n"

md += "### Customer Success\n\n"
md += "| Path |\n"
md += "|---|\n"
md += "| `/api/customer-success?view=enriched&limit=500` |\n"
md += "| `/api/customer-success?view=master&limit=500` |\n\n"

md += "### GA4 Website Traffic\n\n"
md += "| Path |\n"
md += "|---|\n"
md += "| `/api/ga4/cache` |\n\n"

md += "### Advanced (direct MongoDB access)\n\n"
md += "| Path |\n"
md += "|---|\n"
md += "| `/api/collections` |\n"
md += "| `/api/collections/{name}?limit=100&skip=0` |\n\n"

md += "## Response Example\n\n"
md += "**GET /api/kpis/summary?start=2026-07-01&end=2026-07-31**\n\n"
md += "```json\n"
md += "{\n"
md += '  "period": {"start": "2026-07-01", "end": "2026-07-31", "days": 31},\n'
md += '  "signups": 25,\n'
md += '  "uploads": 11,\n'
md += '  "paying_customers": 1,\n'
md += '  "new_paying_customers": 1,\n'
md += '  "revenue": {\n'
md += '    "total": 29.0,\n'
md += '    "new_customer": 29.0,\n'
md += '    "recurring": 0.0\n'
md += '  },\n'
md += '  "conversion_rates": {\n'
md += '    "signup_to_upload_pct": 44.0,\n'
md += '    "upload_to_paid_pct": 9.09,\n'
md += '    "signup_to_paid_pct": 4.0\n'
md += '  }\n'
md += "}\n"
md += "```\n\n"

md += "## Code Examples\n\n"
md += "### Python\n\n"
md += "```python\n"
md += "import requests\n\n"
md += f'BASE = "{BASE}"\n'
md += 'HEADERS = {\n'
md += f'    "X-API-Key": "{api_key}",\n'
md += '    "ngrok-skip-browser-warning": "1"\n'
md += '}\n\n'
md += 'r = requests.get(f"{BASE}/api/kpis/summary",\n'
md += '                 headers=HEADERS,\n'
md += '                 params={"start": "2026-07-01", "end": "2026-07-31"})\n'
md += 'print(r.json())\n'
md += "```\n\n"

md += "### Node.js\n\n"
md += "```javascript\n"
md += f'const BASE = "{BASE}";\n'
md += "const HEADERS = {\n"
md += f'  "X-API-Key": "{api_key}",\n'
md += '  "ngrok-skip-browser-warning": "1"\n'
md += "};\n\n"
md += 'const url = `${BASE}/api/kpis/summary?start=2026-07-01&end=2026-07-31`;\n'
md += "const res = await fetch(url, { headers: HEADERS });\n"
md += "const data = await res.json();\n"
md += "console.log(data);\n"
md += "```\n\n"

md += "### PHP\n\n"
md += "```php\n"
md += "<?php\n"
md += f'$base = "{BASE}";\n'
md += "$headers = [\n"
md += f'    "X-API-Key: {api_key}",\n'
md += '    "ngrok-skip-browser-warning: 1"\n'
md += "];\n"
md += '$ch = curl_init("$base/api/kpis/summary?start=2026-07-01&end=2026-07-31");\n'
md += "curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);\n"
md += "curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);\n"
md += "$data = json_decode(curl_exec($ch), true);\n"
md += "print_r($data);\n"
md += "?>\n"
md += "```\n\n"

md += "## Validation Rules Applied Server-Side\n\n"
md += "**Signups** rejected if:\n"
md += "- Missing signup date\n"
md += "- Internal email (@eagle3dstreaming.com, @eagle3d.com)\n"
md += "- Invalid email (bad syntax / MX failure / disposable domain)\n\n"

md += "**Uploads** rejected if:\n"
md += "- Missing upload date\n"
md += "- Internal email\n"
md += "- Invalid email\n"
md += "- No matching signup found\n"
md += "- Upload before signup date\n"
md += "- Upload more than 30 days after signup (likely re-upload after delete)\n\n"

md += "**Payments** rejected if:\n"
md += "- Internal email\n"
md += "- Invalid email\n"
md += "- total_spend <= 0\n\n"

md += "**Customer type auto-tagged:**\n"
md += "- NEW_CUSTOMER = first-ever payment (based on payment_history ledger)\n"
md += "- RECURRING = has previous payment on record\n\n"

md += "## Data Freshness\n\n"
md += "| Data | Update frequency |\n"
md += "|---|---|\n"
md += "| KPI (signups/uploads) | Every 6 hours |\n"
md += "| Stripe payments | Every 6 hours |\n"
md += "| YouTube | Every 6 hours |\n"
md += "| LinkedIn | Every 6 hours |\n"
md += "| Customer Success | Every 6 hours |\n"
md += "| GA4 | Every 6 hours |\n"
md += "| API responses | Always live (no cache) |\n\n"

md += "## Error Codes\n\n"
md += "| Code | Meaning |\n"
md += "|---|---|\n"
md += "| 200 | Success |\n"
md += "| 401 | Missing X-API-Key header |\n"
md += "| 403 | Invalid API key |\n"
md += "| 404 | Not found |\n"
md += "| 500 | MongoDB offline or internal error |\n\n"

md += "## Contact\n\n"
md += "- **API owner:** Fozayel Ibn Ayaz\n"
md += "- **Repo:** github.com/fozayelibnayaz/eagle3d-kpi-automation\n"

Path("ANINDA_HANDOFF.md").write_text(md)
print(f"OK: ANINDA_HANDOFF.md written ({len(md):,} chars)")
print()
print("=" * 60)
print("SEND ANINDA:")
print("=" * 60)
print(f"  1. Attach: ANINDA_HANDOFF.md")
print(f"  2. URL:    {BASE}")
print(f"  3. Docs:   {BASE}/docs")
print(f"  4. Key:    {api_key}")

