from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)

from mongo_client import find_all, count_docs

rows = find_all("webhook_log", sort=[("received_at", -1)], limit=10)

print("Latest webhook_log rows:")
for r in rows:
    print(json.dumps(r, indent=2, default=str))

print("\nCollection counts:")
for c in ["signups", "uploads", "payments", "webhook_log"]:
    print(f"{c}: {count_docs(c)}")
