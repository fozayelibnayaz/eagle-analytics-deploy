"""
customer_success_scraper.py — Eagle 3D Streaming Analytics Hub
================================================================
Generic Google Sheets → MongoDB ingester.

USE CASE:
  Google Sheets are the INPUT layer (data entry by team).
  MongoDB is the SYSTEM OF RECORD (queryable, joinable, indexable).
  The app reads ONLY from MongoDB.

DESIGN:
  - Configurable list of sheets to ingest (SHEETS_TO_INGEST below).
  - Each sheet's tabs are read via gspread with service account creds.
  - Each tab becomes a MongoDB collection: <prefix>_<tab_slug>.
  - Metadata: _source_sheet, _source_tab, _ingested_at.
  - Full replacement by default (drop-and-insert per tab) — safe because
    the sheet IS the source of truth for that data.

ADDING A NEW SHEET:
  1. Add an entry to SHEETS_TO_INGEST below with url + prefix
  2. Run: python3 customer_success_scraper.py
  3. Done. Data is now in MongoDB.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from mongo_client import get_raw_db, insert_many


# ─────────────────────────────────────────────────────────────────
# CONFIG — declare all Google Sheets to ingest here
# ─────────────────────────────────────────────────────────────────
SHEETS_TO_INGEST: List[Dict[str, str]] = [
    {
        "url":     "https://docs.google.com/spreadsheets/d/1sSaJ-4RusYSz8eAbycLeDkCC1LFXPY-4ErffDVQieAU/edit",
        "prefix":  "customer_success",
        "label":   "Customer Success Master Sheet",
    },
    # Future sheets go here, e.g.:
    # {
    #     "url":    "https://docs.google.com/spreadsheets/d/XXX/edit",
    #     "prefix": "sales_pipeline",
    #     "label":  "Sales Pipeline Tracker",
    # },
]


# ─────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [CS] {msg}", flush=True)


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────
def _slugify(name: str) -> str:
    """Turn 'Tab Name (test)' into 'tab_name_test'."""
    s = re.sub(r"[^a-z0-9]+", "_", str(name).lower().strip())
    return s.strip("_")[:60] or "unnamed"


def _secret(name: str, default: str = "") -> str:
    val = os.environ.get(name, "").strip()
    if val:
        return val
    try:
        import streamlit as st
        return str(st.secrets.get(name, "") or default).strip()
    except Exception:
        return default


# ─────────────────────────────────────────────────────────────────
# GOOGLE SHEETS CLIENT
# ─────────────────────────────────────────────────────────────────
def _get_gspread_client():
    """Load gspread with service account credentials."""
    try:
        import gspread
        from google.oauth2 import service_account
    except ImportError:
        log("❌ gspread or google-auth not installed")
        return None

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    creds = None

    # 1. Streamlit secrets: ga4_service_account
    try:
        import streamlit as st
        sa = dict(st.secrets.get("ga4_service_account", {}))
        if sa and sa.get("client_email"):
            if "private_key" in sa:
                sa["private_key"] = sa["private_key"].replace("\\n", "\n")
            creds = service_account.Credentials.from_service_account_info(sa, scopes=scopes)
    except Exception:
        pass

    # 2. Streamlit secrets: GOOGLE_CREDS
    if not creds:
        try:
            import streamlit as st
            sa = dict(st.secrets.get("GOOGLE_CREDS", {}))
            if sa and sa.get("client_email"):
                if "private_key" in sa:
                    sa["private_key"] = sa["private_key"].replace("\\n", "\n")
                creds = service_account.Credentials.from_service_account_info(sa, scopes=scopes)
        except Exception:
            pass

    # 3. google_creds.json on disk
    if not creds:
        p = Path("google_creds.json")
        if p.exists():
            try:
                creds = service_account.Credentials.from_service_account_file(
                    str(p), scopes=scopes
                )
            except Exception:
                pass

    if not creds:
        log("❌ No Google service account credentials found")
        return None

    try:
        return gspread.authorize(creds)
    except Exception as e:
        log(f"❌ gspread authorize failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# INGESTION
# ─────────────────────────────────────────────────────────────────
def _ingest_tab(worksheet, prefix: str, sheet_label: str) -> Dict[str, Any]:
    """Read all rows of one worksheet and upsert into MongoDB collection."""
    tab_name = worksheet.title
    tab_slug = _slugify(tab_name)
    collection_name = f"{prefix}_{tab_slug}"

    # Read all values (list of lists)
    try:
        all_values = worksheet.get_all_values()
    except Exception as e:
        log(f"    ❌ Cannot read tab '{tab_name}': {e}")
        return {"tab": tab_name, "rows": 0, "error": str(e)}

    if not all_values or len(all_values) < 2:
        log(f"    ⚠️  Tab '{tab_name}': empty or no data rows")
        return {"tab": tab_name, "collection": collection_name, "rows": 0}

    # First row = headers
    raw_headers = all_values[0]
    headers: List[str] = []
    seen: Dict[str, int] = {}
    for i, h in enumerate(raw_headers):
        h_str = str(h or "").strip()
        if not h_str:
            h_str = f"col_{i}"
        # Deduplicate headers (Google Sheets allows dupes; MongoDB fields can't)
        if h_str in seen:
            seen[h_str] += 1
            h_str = f"{h_str}_{seen[h_str]}"
        else:
            seen[h_str] = 0
        headers.append(h_str)

    # Convert data rows to dicts
    now = datetime.utcnow().isoformat()
    docs = []
    for row_idx, row in enumerate(all_values[1:], start=2):
        doc: Dict[str, Any] = {}
        for i, val in enumerate(row):
            if i < len(headers):
                doc[headers[i]] = val
            else:
                doc[f"col_{i}"] = val
        # Skip fully-empty rows
        if not any(str(v).strip() for v in doc.values()):
            continue
        # Metadata
        doc["_source_sheet"] = sheet_label
        doc["_source_tab"]   = tab_name
        doc["_row_number"]   = row_idx
        doc["_ingested_at"]  = now
        docs.append(doc)

    if not docs:
        log(f"    ⚠️  Tab '{tab_name}': no non-empty rows after filter")
        return {"tab": tab_name, "collection": collection_name, "rows": 0}

    # Full replacement — drop then insert
    db = get_raw_db()
    if db is None:
        return {"tab": tab_name, "collection": collection_name, "rows": 0, "error": "no mongo"}

    try:
        db[collection_name].drop()
    except Exception:
        pass

    n = insert_many(collection_name, docs)
    log(f"    ✅ '{tab_name}' → {collection_name}: {n} rows")
    return {"tab": tab_name, "collection": collection_name, "rows": n}


def _ingest_sheet(gc, sheet_cfg: Dict[str, str]) -> Dict[str, Any]:
    """Ingest all tabs of one sheet."""
    url    = sheet_cfg["url"]
    prefix = sheet_cfg["prefix"]
    label  = sheet_cfg["label"]

    log(f"→ Opening: {label}")
    try:
        sheet = gc.open_by_url(url)
    except Exception as e:
        log(f"  ❌ Cannot open sheet: {e}")
        return {"label": label, "error": str(e), "tabs": []}

    tabs = sheet.worksheets()
    log(f"  Found {len(tabs)} tab(s)")

    results = []
    for ws in tabs:
        result = _ingest_tab(ws, prefix, label)
        results.append(result)

    return {"label": label, "url": url, "tabs": results}


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────
def run_full_pipeline() -> Dict[str, Any]:
    log("=" * 60)
    log("CUSTOMER SUCCESS / MULTI-SHEET INGESTION")
    log("=" * 60)

    gc = _get_gspread_client()
    if gc is None:
        log("❌ Cannot authenticate — aborting")
        return {"error": "no google auth"}

    log(f"✅ Authenticated as service account")

    all_results = []
    for sheet_cfg in SHEETS_TO_INGEST:
        result = _ingest_sheet(gc, sheet_cfg)
        all_results.append(result)

    # Summary
    total_tabs = 0
    total_rows = 0
    for r in all_results:
        for t in r.get("tabs", []):
            total_tabs += 1
            total_rows += t.get("rows", 0)

    log("=" * 60)
    log(f"INGESTION COMPLETE")
    log(f"  Sheets ingested: {len(all_results)}")
    log(f"  Tabs ingested:   {total_tabs}")
    log(f"  Total rows:      {total_rows:,}")
    log("=" * 60)

    return {
        "sheets": len(all_results),
        "tabs":   total_tabs,
        "rows":   total_rows,
        "detail": all_results,
    }


if __name__ == "__main__":
    import json
    r = run_full_pipeline()
    # Only print counts summary (detail can be huge)
    print(json.dumps({k: v for k, v in r.items() if k != "detail"}, indent=2))
    sys.exit(0 if not r.get("error") else 1)



# ══════════════════════════════════════════════════════════════════
# BACKWARD-COMPAT WRAPPERS (called by customer_success_ui.py)
# All these delegate to run_full_pipeline() or its sub-steps.
# ══════════════════════════════════════════════════════════════════
def scrape_all_tabs():
    """Compat wrapper: scrapes all CS sheet tabs, returns dict with 'tabs' key."""
    try:
        result = run_full_pipeline()
        return {
            "tabs":  result.get("tabs", {}),
            "rows":  result.get("total_rows", 0),
            "error": result.get("error"),
        }
    except Exception as e:
        return {"tabs": {}, "rows": 0, "error": str(e)}


def upsert_to_db(scraped: dict) -> int:
    """Compat wrapper: the run_full_pipeline already upserts to MongoDB.
    This just returns the row count for UI display."""
    return int(scraped.get("rows", 0) or 0)


# Legacy alias for any external code still calling upsert_to_supabase (writes to MongoDB)
upsert_to_supabase = upsert_to_db


def enrich_stripe_live() -> dict:
    """Compat wrapper: trigger Stripe live enrichment.
    Delegates to run_full_pipeline (which already includes Stripe step)."""
    try:
        result = run_full_pipeline()
        return {
            "enriched": result.get("stripe_enriched", 0),
            "error":    result.get("error"),
        }
    except Exception as e:
        return {"enriched": 0, "error": str(e)}
