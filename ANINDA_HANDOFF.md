# Eagle 3D Streaming - Backend API Handoff

**Recipient:** Aninda Sadman (Backend Developer)
**API Owner:** Fozayel Ibn Ayaz
**Status:** LIVE & production-ready

---

## Quick Reference

| Item | Value |
|---|---|
| Base URL | `https://unsoiling-tendenciously-marge.ngrok-free.dev` |
| Interactive docs | https://unsoiling-tendenciously-marge.ngrok-free.dev/docs |
| Auth header | `X-API-Key: e3d_U4K1XjV1mn5TnH5X0hlIRtzQAxGgeACbLN-V0OKb0Vg` |
| Health check (no auth) | `https://unsoiling-tendenciously-marge.ngrok-free.dev/health` |
| Response format | JSON |
| Data freshness | Every 6 hours, live queries always fresh |

## Important: ngrok Browser Warning

If you visit the URL in a browser, ngrok shows a one-time warning page.
**This does NOT affect API calls.** Curl/Python/Node requests work directly.

To skip the warning in code (recommended), add this header to every request:
```
ngrok-skip-browser-warning: any
```

## 30-Second Test

```bash
curl -H 'X-API-Key: e3d_U4K1XjV1mn5TnH5X0hlIRtzQAxGgeACbLN-V0OKb0Vg' \
     -H 'ngrok-skip-browser-warning: 1' \
     'https://unsoiling-tendenciously-marge.ngrok-free.dev/api/kpis/summary?start=2026-07-01&end=2026-07-31'
```

Returns JSON with signups / uploads / paying customers / revenue / conversion rates.

## All Endpoints

### System

| Method | Path | Auth |
|---|---|---|
| GET | `/` | No |
| GET | `/health` | No |
| GET | `/api/pipeline/health` | Yes |

### KPIs

| Path | Query Params |
|---|---|
| `/api/kpis/summary` | `start`, `end` (YYYY-MM-DD) |
| `/api/kpis/daily` | `start`, `end` |

### Raw Data

| Path | Query Params |
|---|---|
| `/api/signups` | status, start, end, limit |
| `/api/uploads` | status, start, end, limit |
| `/api/payments` | status, customer_type, start, end, limit |

- `status`: ACCEPTED / REJECTED / PENDING
- `customer_type`: NEW_CUSTOMER / RECURRING

### Attribution

| Path | Description |
|---|---|
| `/api/attribution/signups` | Signups by normalized source |
| `/api/attribution/uploads` | Uploads by source |
| `/api/attribution/paying?new_only=true` | Paying customers by source |
| `/api/attribution/revenue?new_only=false` | Revenue by source |
| `/api/attribution/full-report?days=30` | All 4 combined |

### YouTube

| Path |
|---|
| `/api/youtube/channel` |
| `/api/youtube/videos?limit=100&sort_by=views` |
| `/api/youtube/analytics?start=&end=` |

### LinkedIn

| Path |
|---|
| `/api/linkedin/latest` |
| `/api/linkedin/posts?limit=50` |
| `/api/linkedin/followers?limit=90` |

### Customer Success

| Path |
|---|
| `/api/customer-success?view=enriched&limit=500` |
| `/api/customer-success?view=master&limit=500` |

### GA4 Website Traffic

| Path |
|---|
| `/api/ga4/cache` |

### Advanced (direct MongoDB access)

| Path |
|---|
| `/api/collections` |
| `/api/collections/{name}?limit=100&skip=0` |

## Response Example

**GET /api/kpis/summary?start=2026-07-01&end=2026-07-31**

```json
{
  "period": {"start": "2026-07-01", "end": "2026-07-31", "days": 31},
  "signups": 25,
  "uploads": 11,
  "paying_customers": 1,
  "new_paying_customers": 1,
  "revenue": {
    "total": 29.0,
    "new_customer": 29.0,
    "recurring": 0.0
  },
  "conversion_rates": {
    "signup_to_upload_pct": 44.0,
    "upload_to_paid_pct": 9.09,
    "signup_to_paid_pct": 4.0
  }
}
```

## Code Examples

### Python

```python
import requests

BASE = "https://unsoiling-tendenciously-marge.ngrok-free.dev"
HEADERS = {
    "X-API-Key": "e3d_U4K1XjV1mn5TnH5X0hlIRtzQAxGgeACbLN-V0OKb0Vg",
    "ngrok-skip-browser-warning": "1"
}

r = requests.get(f"{BASE}/api/kpis/summary",
                 headers=HEADERS,
                 params={"start": "2026-07-01", "end": "2026-07-31"})
print(r.json())
```

### Node.js

```javascript
const BASE = "https://unsoiling-tendenciously-marge.ngrok-free.dev";
const HEADERS = {
  "X-API-Key": "e3d_U4K1XjV1mn5TnH5X0hlIRtzQAxGgeACbLN-V0OKb0Vg",
  "ngrok-skip-browser-warning": "1"
};

const url = `${BASE}/api/kpis/summary?start=2026-07-01&end=2026-07-31`;
const res = await fetch(url, { headers: HEADERS });
const data = await res.json();
console.log(data);
```

### PHP

```php
<?php
$base = "https://unsoiling-tendenciously-marge.ngrok-free.dev";
$headers = [
    "X-API-Key: e3d_U4K1XjV1mn5TnH5X0hlIRtzQAxGgeACbLN-V0OKb0Vg",
    "ngrok-skip-browser-warning: 1"
];
$ch = curl_init("$base/api/kpis/summary?start=2026-07-01&end=2026-07-31");
curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
$data = json_decode(curl_exec($ch), true);
print_r($data);
?>
```

## Validation Rules Applied Server-Side

**Signups** rejected if:
- Missing signup date
- Internal email (@eagle3dstreaming.com, @eagle3d.com)
- Invalid email (bad syntax / MX failure / disposable domain)

**Uploads** rejected if:
- Missing upload date
- Internal email
- Invalid email
- No matching signup found
- Upload before signup date
- Upload more than 30 days after signup (likely re-upload after delete)

**Payments** rejected if:
- Internal email
- Invalid email
- total_spend <= 0

**Customer type auto-tagged:**
- NEW_CUSTOMER = first-ever payment (based on payment_history ledger)
- RECURRING = has previous payment on record

## Data Freshness

| Data | Update frequency |
|---|---|
| KPI (signups/uploads) | Every 6 hours |
| Stripe payments | Every 6 hours |
| YouTube | Every 6 hours |
| LinkedIn | Every 6 hours |
| Customer Success | Every 6 hours |
| GA4 | Every 6 hours |
| API responses | Always live (no cache) |

## Error Codes

| Code | Meaning |
|---|---|
| 200 | Success |
| 401 | Missing X-API-Key header |
| 403 | Invalid API key |
| 404 | Not found |
| 500 | MongoDB offline or internal error |

## Contact

- **API owner:** Fozayel Ibn Ayaz
- **Repo:** github.com/fozayelibnayaz/eagle3d-kpi-automation
