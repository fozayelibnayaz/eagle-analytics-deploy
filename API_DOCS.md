# Eagle 3D Streaming — Analytics API

Backend integration guide.

## Base URLs

- **Public (ngrok):** `https://unsoiling-tendenciously-marge.ngrok-free.dev`
- **Local network:** `http://127.0.0.1:8000`
- **Localhost:** `http://localhost:8000`

## Authentication

Send this header on every request:

```
X-API-Key: e3d_U4K1XjV1mn5TnH5X0hlIRtzQAxGgeACbLN-V0OKb0Vg
```

Missing or wrong key → 401 / 403.

## Quick Test

```bash
# Health (no auth)
curl "https://unsoiling-tendenciously-marge.ngrok-free.dev/health"

# KPI summary
curl -H "X-API-Key: e3d_U4K1XjV1mn5TnH5X0hlIRtzQAxGgeACbLN-V0OKb0Vg" \
     "https://unsoiling-tendenciously-marge.ngrok-free.dev/api/kpis/summary?start=2026-07-01&end=2026-07-31"
```

## Interactive Docs

Open in browser: **https://unsoiling-tendenciously-marge.ngrok-free.dev/docs**

Swagger UI with all endpoints and try-it-out interface.

## Endpoints

### System

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | No | List all endpoints |
| GET | `/health` | No | MongoDB + API status |
| GET | `/api/pipeline/health` | Yes | Data quality (missing/zero days) |

### KPIs

| Path | Query Params |
|------|--------------|
| `/api/kpis/summary` | `start`, `end` (YYYY-MM-DD) |
| `/api/kpis/daily` | `start`, `end` |

### Raw Data

| Path | Query Params |
|------|--------------|
| `/api/signups` | `status`, `start`, `end`, `limit` |
| `/api/uploads` | `status`, `start`, `end`, `limit` |
| `/api/payments` | `status`, `customer_type` (NEW_CUSTOMER / RECURRING), `start`, `end`, `limit` |

### Attribution

| Path | Description |
|------|-------------|
| `/api/attribution/signups` | Signups by normalized source |
| `/api/attribution/uploads` | Uploads by source |
| `/api/attribution/paying` | Paying customers by source |
| `/api/attribution/revenue` | Revenue by source |
| `/api/attribution/full-report?days=30` | All 4 in one call |

### YouTube

| Path |
|------|
| `/api/youtube/channel` |
| `/api/youtube/videos?limit=100&sort_by=views` |
| `/api/youtube/analytics?start=&end=` |

### LinkedIn

| Path |
|------|
| `/api/linkedin/latest` |
| `/api/linkedin/posts?limit=50` |
| `/api/linkedin/followers?limit=90` |

### Customer Success

| Path |
|------|
| `/api/customer-success?view=enriched&limit=500` |
| `/api/customer-success?view=master&limit=500` |

### GA4

| Path |
|------|
| `/api/ga4/cache` |

### Advanced (any collection)

| Path |
|------|
| `/api/collections` — list all |
| `/api/collections/{name}?limit=100&skip=0` |

## Response Example

`GET /api/kpis/summary?start=2026-07-01&end=2026-07-31`

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

## Data Freshness

- **All data updated 4× daily** (every 6 hours) via scheduled pipeline
- **Every API call is live** — reads directly from MongoDB, no cache

## Errors

| Code | Meaning |
|------|---------|
| 200 | Success |
| 401 | Missing X-API-Key header |
| 403 | Invalid API key |
| 404 | Not found |
| 500 | MongoDB offline or internal error |

## Notes for Integration

- All dates use ISO format: `YYYY-MM-DD`
- If `start` / `end` omitted, defaults to last 30 days
- Rate limit: none currently (be reasonable, ~10 req/sec max)
- Response format: always JSON

## ngrok Free Tier Notes

- URL may change if ngrok restarts. Currently: https://unsoiling-tendenciously-marge.ngrok-free.dev
- Free tier warns visitors on first request (browser only, curl works fine)
- To skip the warning in code: add header `ngrok-skip-browser-warning: any`

## Contact

- **API owner:** Fozayel Ibn Ayaz
- **Repo:** github.com/fozayelibnayaz/eagle3d-kpi-automation