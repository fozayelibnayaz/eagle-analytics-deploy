"""
sheets_writer.py
Google Sheets I/O with rate limiting and CSV fallback.
"""
import csv
import os
import json
import time
import tempfile
import subprocess
import sys
from pathlib import Path

# Self-heal: auto-install gspread if missing
try:
    import gspread
except ImportError:
    print("[Sheets] gspread not found — auto-installing...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "gspread>=5.10", "-q"])
        import gspread
        print("[Sheets] ✅ gspread installed successfully")
    except Exception as _e:
        print(f"[Sheets] Auto-install failed: {_e}")
        gspread = None
from datetime import datetime

DATA_DIR = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)

MASTER_SHEET_URL = os.environ.get(
    "MASTER_SHEET_URL",
    "https://docs.google.com/spreadsheets/d/1E5PI3-m7mTMKRQ4Cy-WqpVCo5dQjbICcA2EnrC9ORE4"
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_client = None
_ss     = None

# Rate limiting state
_last_request_time = [0.0]
MIN_INTERVAL = 1.2  # seconds between requests (~50/min, safe under 60/min limit)


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [Sheets] {msg}", flush=True)


def _rate_limit():
    """Sleep if we're calling Sheets API too fast."""
    elapsed = time.time() - _last_request_time[0]
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_request_time[0] = time.time()


def _retry_on_quota(func, *args, max_retries=4, **kwargs):
    """Retry a Sheets API call on 429 / quota errors."""
    for attempt in range(max_retries):
        try:
            _rate_limit()
            return func(*args, **kwargs)
        except Exception as e:
            err = str(e).lower()
            is_quota = (
                "429" in err or
                "quota" in err or
                "rate" in err or
                "rateLimitExceeded" in str(e)
            )
            if is_quota and attempt < max_retries - 1:
                wait = 30 * (attempt + 1)
                log(f"Quota hit, waiting {wait}s (retry {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            raise
    raise Exception("Max retries exhausted")


def _get_client():
    global _client, _ss
    if _client is not None:
        return _client, _ss

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_env  = os.environ.get("GOOGLE_CREDS_JSON", "")
        creds_file = "google_creds.json"

        # Try st.secrets fallback (for Streamlit Cloud)
        if not creds_env:
            try:
                import streamlit as st
                for _sk in ["GOOGLE_CREDS_JSON", "GOOGLE_CREDS"]:
                    if _sk in st.secrets:
                        _r = st.secrets[_sk]
                        _c = json.loads(_r) if isinstance(_r, str) else dict(_r)
                        if "private_key" in _c:
                            _c["private_key"] = _c["private_key"].replace("\\n", "\n")
                        _t = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
                        json.dump(_c, _t)
                        _t.close()
                        creds_file = _t.name
                        creds_env = "from_secrets"
                        break
            except Exception:
                pass

        # Also try ga4_service_account in secrets
        if not creds_env:
            try:
                import streamlit as st
                if "ga4_service_account" in st.secrets:
                    _sa = dict(st.secrets["ga4_service_account"])
                    if "private_key" in _sa:
                        _sa["private_key"] = _sa["private_key"].replace("\\n", "\n")
                    _t = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
                    json.dump(_sa, _t)
                    _t.close()
                    creds_file = _t.name
                    creds_env = "from_secrets_ga4"
            except Exception:
                pass

        if creds_env and creds_env != "from_secrets" and creds_env != "from_secrets_ga4":
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
            tmp.write(creds_env)
            tmp.close()
            creds_file = tmp.name

        if not os.path.exists(creds_file):
            raise FileNotFoundError(f"No credentials: {creds_file}")

        creds  = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
        client = gspread.authorize(creds)

        # Try st.secrets for MASTER_SHEET_URL if env var is missing
        sheet_url = MASTER_SHEET_URL
        if not sheet_url or "docs.google.com" not in sheet_url:
            try:
                import streamlit as st
                if "MASTER_SHEET_URL" in st.secrets:
                    sheet_url = str(st.secrets["MASTER_SHEET_URL"])
            except Exception:
                pass

        ss     = client.open_by_url(sheet_url)

        _client = client
        _ss     = ss
        log(f"Connected: '{ss.title}'")
        return _client, _ss

    except Exception as e:
        log(f"Connection failed: {e}")
        raise


def test_connection() -> bool:
    try:
        _get_client()
        return True
    except Exception:
        return False


def _get_or_create_ws(ss, tab_name: str):
    try:
        import gspread
        try:
            return ss.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            ws = ss.add_worksheet(title=tab_name, rows=10000, cols=50)
            log(f"Created tab: '{tab_name}'")
            return ws
    except Exception as e:
        raise RuntimeError(f"Cannot get/create worksheet '{tab_name}': {e}")



def _auto_push_to_supabase(tab_name, rows):
    """Auto-mirror Sheets writes to Supabase (no Sheets dependency for reads)."""
    import os as _os
    url = _os.environ.get("SUPABASE_URL","")
    key = _os.environ.get("SUPABASE_SERVICE_KEY","")
    if not url or not key:
        try:
            import streamlit as _st
            url = str(_st.secrets.get("SUPABASE_URL","")).strip()
            key = str(_st.secrets.get("SUPABASE_SERVICE_KEY","")).strip()
        except Exception:
            return
    if not url or not key:
        return
    if not rows:
        return
    try:
        from supabase import create_client
        sb = create_client(url, key)
    except Exception:
        return

    import re as _re
    def _parse_date(v):
        if not v: return None
        s = str(v).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S","%Y-%m-%d","%m/%d/%y, %I:%M %p","%m/%d/%Y, %I:%M %p",
                    "%a, %d %b %Y %H:%M:%S %Z","%a, %d %b %Y %H:%M:%S GMT","%b %d, %Y"):
            try:
                from datetime import datetime as _dt
                return _dt.strptime(s.split("+")[0], fmt).strftime("%Y-%m-%d")
            except Exception:
                pass
        m = _re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return None

    def _parse_amount(v):
        if not v: return 0.0
        s = _re.sub(r"[$,\s\n\r]", "", str(v))
        s = _re.sub(r"[A-Za-z]+$", "", s).strip()
        try: return float(s)
        except: return 0.0

    def _norm_email(r):
        em = str(r.get("Email","") or r.get("email","") or r.get("__email_normalized__","")).strip().lower()
        return em if em and "@" in em else ""

    tab_to_table = {
        "Verified_FREE":         ("signups", "signup_date", ["Account Created On","row_date_used","__scraped_date__"], None),
        "Verified_FIRST_UPLOAD": ("uploads", "upload_date", ["Upload Date","row_date_used","__scraped_date__"], None),
        "Verified_STRIPE":       ("payments","first_payment_date",["First payment","row_date_used","Created","Created (UTC)"], "amount"),
    }
    cfg = tab_to_table.get(tab_name)
    if not cfg:
        return  # only mirror Verified_* tabs
    table, date_col, date_fields, has_amount = cfg

    upsert = []
    for r in rows:
        em = _norm_email(r)
        if not em: continue
        d = None
        for f in date_fields:
            v = r.get(f)
            if v:
                d = _parse_date(v)
                if d: break
        row = {
            "email": em, "email_normalized": em,
            date_col: d,
            "final_status": str(r.get("final_status","PENDING") or "PENDING").upper()[:20],
            "category": str(r.get("category","") or "")[:50],
        }
        if has_amount:
            for af in ("Amount","Total spend","Total Spend","__amount__"):
                v = r.get(af)
                if v:
                    a = _parse_amount(v)
                    if a > 0:
                        row["total_spend"] = a
                        break
            try:
                row["payment_count"] = int(r.get("Payment Count", r.get("payment_count",0)) or 0)
            except:
                row["payment_count"] = 0
        if tab_name == "Verified_FREE":
            row["lead_source"] = str(r.get("Lead Source","") or "")[:200]
            row["rejection_reason"] = str(r.get("__rejection_reason__","") or "")[:300]
        upsert.append(row)

    log(f"[Supabase mirror] {tab_name} -> {table}: {len(upsert)} rows")
    errors = 0
    for i in range(0, len(upsert), 50):
        try:
            sb.table(table).upsert(upsert[i:i+50], on_conflict="email_normalized").execute()
        except Exception as e:
            errors += 1
            if errors <= 2:
                log(f"  Upsert err: {e}")
    if errors == 0:
        log(f"[Supabase mirror] {table} synced OK")
    else:
        log(f"[Supabase mirror] {table}: {errors} chunk errors")


def write_tab_data(tab_name: str, rows: list) -> bool:
    """Write rows to Sheets. CSV fallback if Sheets fails."""
    if not rows:
        log(f"{tab_name}: 0 rows")
        return False

    fields = sorted({k for r in rows for k in r.keys()})
    log(f"{tab_name}: writing {len(rows)} rows...")

    try:
        client, ss = _get_client()
        ws = _get_or_create_ws(ss, tab_name)

        matrix = [fields] + [[str(r.get(f, "")) for f in fields] for r in rows]

        _retry_on_quota(ws.clear)
        _retry_on_quota(ws.update, "A1", matrix)

        # Verify
        rb = _retry_on_quota(ws.get_all_values)
        if len(rb) - 1 == len(rows):
            log(f"{tab_name}: Sheets OK - {len(rows)} rows")
            return True
        log(f"{tab_name}: verify mismatch wrote={len(rows)} read={len(rb)-1}")

    except Exception as e:
        log(f"{tab_name}: Sheets failed ({e}) -> CSV")

    # CSV fallback
    try:
        path = DATA_DIR / f"{tab_name}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        log(f"{tab_name}: CSV fallback -> {path}")
    except Exception as e:
        log(f"{tab_name}: CSV failed: {e}")
    return False


def read_tab_data(tab_name: str) -> list:
    """Read from Sheets. CSV fallback if Sheets fails."""
    try:
        client, ss = _get_client()
        ws   = ss.worksheet(tab_name)
        rows = _retry_on_quota(ws.get_all_records)
        log(f"{tab_name}: read {len(rows)} rows from Sheets")
        return rows
    except Exception as e:
        log(f"{tab_name}: Sheets read failed ({e}) -> CSV")

    for fname in (f"{tab_name}.csv", f"Raw_{tab_name}.csv", f"Verified_{tab_name}.csv"):
        path = DATA_DIR / fname
        if path.exists() and path.stat().st_size > 0:
            try:
                with open(path, "r", newline="", encoding="utf-8") as f:
                    rows = list(csv.DictReader(f))
                log(f"{tab_name}: read {len(rows)} rows from {fname}")
                return rows
            except Exception:
                pass
    return []


REQUIRED_TABS = [
    "Raw_FREE", "Raw_FIRST_UPLOAD", "Raw_STRIPE", "Raw_PAID", "Raw_500_MIN",
    "Verified_FREE", "Verified_FIRST_UPLOAD", "Verified_STRIPE", "Verified_PAID", "Verified_500_MIN",
    "Daily_Counts", "Monthly_Counts",
    "LinkedIn", "LinkedIn_Posts",
    "YouTube", "GA4", "Cross_Platform",
    "Daily_Report", "Phase2_Summary",
]


def ensure_tabs_exist():
    """Create any missing Google Sheet tabs needed by the system."""
    try:
        client, ss = _get_client()
        existing = {ws.title for ws in ss.worksheets()}
        created = []
        for tab in REQUIRED_TABS:
            if tab not in existing:
                try:
                    ss.add_worksheet(title=tab, rows=100, cols=26)
                    created.append(tab)
                    time.sleep(0.5)
                except Exception as e:
                    log(f"Could not create tab '{tab}': {e}")
        if created:
            log(f"Created missing tabs: {', '.join(created)}")
        return created
    except Exception as e:
        log(f"ensure_tabs_exist failed: {e}")
        return []


def write_run_summary(summary: dict) -> bool:
    """Append one row to Daily_Report tab."""
    try:
        client, ss = _get_client()
        ws = _get_or_create_ws(ss, "Daily_Report")
        existing = _retry_on_quota(ws.get_all_values)
        headers  = existing[0] if existing else sorted(summary.keys())
        if not existing:
            _retry_on_quota(ws.append_row, headers)
        _retry_on_quota(ws.append_row, [str(summary.get(h, "")) for h in headers])
        log("Daily_Report: appended")
        return True
    except Exception as e:
        log(f"Summary append failed: {e}")
        try:
            path = DATA_DIR / "run_summaries.json"
            data = json.load(open(path)) if path.exists() else []
            data.append({"ts": datetime.now().isoformat(), **summary})
            json.dump(data[-200:], open(path, "w"), indent=2, default=str)
        except Exception:
            pass
        return False
