"""
migrate_sheets_to_mongo.py
One-time migration: Google Sheets → MongoDB (with SSL fix)
"""
import os
import sys
import json
from datetime import datetime

print("\n" + "="*60)
print("GOOGLE SHEETS → MONGODB MIGRATION")
print("="*60)

# ── Read secrets ───────────────────────────────────────────────
def read_secret(key):
    val = os.environ.get(key, "")
    if val:
        return val
    try:
        import toml
        secrets = toml.load(".streamlit/secrets.toml")
        return secrets.get(key, "")
    except Exception:
        return ""

# ── Google credentials ─────────────────────────────────────────
def get_gspread_client():
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    creds_file = "google_creds.json"

    # Build from secrets.toml fields
    if not os.path.exists(creds_file):
        try:
            import toml
            secrets = toml.load(".streamlit/secrets.toml")
            creds_dict = {
                "type":                        secrets.get("type", "service_account"),
                "project_id":                  secrets.get("project_id", ""),
                "private_key_id":              secrets.get("private_key_id", ""),
                "private_key":                 secrets.get("private_key", ""),
                "client_email":                secrets.get("client_email", ""),
                "client_id":                   secrets.get("client_id", ""),
                "auth_uri":                    secrets.get("auth_uri", ""),
                "token_uri":                   secrets.get("token_uri", ""),
                "auth_provider_x509_cert_url": secrets.get("auth_provider_x509_cert_url", ""),
                "client_x509_cert_url":        secrets.get("client_x509_cert_url", ""),
                "universe_domain":             secrets.get("universe_domain", "googleapis.com"),
            }
            with open(creds_file, "w") as f:
                json.dump(creds_dict, f, indent=2)
            print("  Built google_creds.json from secrets.toml")
        except Exception as e:
            print(f"  Could not build google_creds.json: {e}")
            return None

    if not os.path.exists(creds_file):
        print("  ERROR: google_creds.json not found")
        return None

    try:
        creds = Credentials.from_service_account_file(creds_file, scopes=scopes)
        client = gspread.authorize(creds)
        print("  Google Sheets client connected")
        return client
    except Exception as e:
        print(f"  Google auth error: {e}")
        return None

# ── MongoDB ────────────────────────────────────────────────────
from mongo_client import get_db, insert_many
db = get_db()
if db is None:
    print("ERROR: MongoDB not connected.")
    sys.exit(1)
print("MongoDB connected")

# ── Connect Sheets ─────────────────────────────────────────────
gc = get_gspread_client()
if gc is None:
    print("ERROR: Google Sheets auth failed.")
    sys.exit(1)

# ── Sheet URLs ─────────────────────────────────────────────────
SHEETS = {
    "MASTER_SHEET_URL": read_secret("MASTER_SHEET_URL") or
        "https://docs.google.com/spreadsheets/d/1E5PI3-m7mTMKRQ4Cy-WqpVCo5dQjbICcA2EnrC9ORE4/edit?usp=sharing",
    "ACCURATE_DATA_SHEET_URL": read_secret("ACCURATE_DATA_SHEET_URL") or
        "https://docs.google.com/spreadsheets/d/1lwffyXWOa7Q7xim2EX9i4AdIs7dtkjOPyKYVBtPpfgY",
}

# ── Helpers ────────────────────────────────────────────────────
def make_unique_headers(headers):
    out, seen = [], {}
    for i, h in enumerate(headers):
        name = str(h).strip() if h else f"col_{i}"
        if not name:
            name = f"col_{i}"
        if name in seen:
            seen[name] += 1
            out.append(f"{name}_{seen[name]}")
        else:
            seen[name] = 1
            out.append(name)
    return out

def read_worksheet(ws):
    values = ws.get_all_values()
    if not values or len(values) < 2:
        return []
    headers = make_unique_headers(values[0])
    rows = []
    for raw in values[1:]:
        if any(str(v).strip() for v in raw):
            padded = (raw + [""] * len(headers))[:len(headers)]
            rows.append(dict(zip(headers, padded)))
    return rows

# ── Migrate ────────────────────────────────────────────────────
grand_total = 0

for sheet_key, sheet_url in SHEETS.items():
    if not sheet_url:
        print(f"\nSkipping {sheet_key} — no URL")
        continue

    print(f"\n{'='*50}")
    print(f"Sheet: {sheet_key}")
    print(f"URL: {sheet_url[:70]}...")

    try:
        sh = gc.open_by_url(sheet_url)
        worksheets = sh.worksheets()
        print(f"Found {len(worksheets)} tabs")

        for ws in worksheets:
            tab = ws.title.strip()
            safe_tab = tab.lower().replace(" ", "_").replace("-", "_").replace("/", "_")

            if sheet_key == "MASTER_SHEET_URL":
                mongo_col = f"sheet_{safe_tab}"
            else:
                mongo_col = f"ml_training_{safe_tab}"

            print(f"\n  Tab: '{tab}' → {mongo_col}")

            try:
                rows = read_worksheet(ws)
                if not rows:
                    print(f"  empty tab — skipping")
                    continue

                ts = datetime.utcnow().isoformat()
                for r in rows:
                    r["_sheet_key"] = sheet_key
                    r["_tab_name"] = tab
                    r["_migrated_at"] = ts

                db[mongo_col].drop()
                db[mongo_col].insert_many(rows, ordered=False)
                print(f"  OK — {len(rows)} rows written")
                grand_total += len(rows)

            except Exception as e:
                print(f"  ERROR on tab '{tab}': {e}")

    except Exception as e:
        print(f"ERROR opening {sheet_key}: {e}")

print("\n" + "="*60)
print(f"TOTAL ROWS FROM SHEETS: {grand_total:,}")
print("SHEETS_MIGRATION_COMPLETE")
