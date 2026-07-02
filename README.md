# Eagle Analytics Hub

Unified analytics command center for Eagle3D Streaming.

## Structure

```txt
apps/api  - FastAPI + MongoDB backend
apps/web  - Next.js frontend
docs      - documentation
scripts   - operational scripts
database  - database export/schema notes
assets    - shared assets
```

## Local Development

Backend: cd apps/api && source venv/bin/activate && python3 -m uvicorn api_server:app --host 0.0.0.0 --port 8080

Frontend: cd apps/web && npm run dev
