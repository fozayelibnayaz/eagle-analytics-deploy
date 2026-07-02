"""
storage_adapter.py - thin wrapper around sheets_writer
Only imports functions that actually exist in sheets_writer.py
"""
import csv
import json
from pathlib import Path
from datetime import datetime

DATA_DIR = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)

# These are the ONLY functions imported - all exist in sheets_writer.py
from sheets_writer import (
    write_tab_data,
    read_tab_data,
    write_run_summary,
    test_connection,
    _get_client,
)

# Test connection at import
try:
    SHEETS_AVAILABLE = test_connection()
    status = "AVAILABLE" if SHEETS_AVAILABLE else "unavailable"
    print(f"[StorageAdapter] Google Sheets: {status}", flush=True)
except Exception:
    SHEETS_AVAILABLE = False
    print("[StorageAdapter] Google Sheets: unavailable", flush=True)


def _get_sheets_client():
    try:
        return _get_client()
    except Exception:
        return None, None


def get_storage_status() -> dict:
    status = {
        "sheets_available": SHEETS_AVAILABLE,
        "data_dir": str(DATA_DIR.absolute()),
        "files": {},
    }
    for f in sorted(DATA_DIR.glob("*.csv")):
        try:
            with open(f) as fh:
                count = sum(1 for _ in fh) - 1
            status["files"][f.name] = {
                "rows":     max(0, count),
                "size_kb":  round(f.stat().st_size / 1024, 1),
                "modified": datetime.fromtimestamp(
                    f.stat().st_mtime
                ).strftime("%Y-%m-%d %H:%M:%S"),
            }
        except Exception:
            status["files"][f.name] = {"error": "unreadable"}
    return status


def read_archive(tab_name: str) -> list:
    p = DATA_DIR / f"ARCHIVE_{tab_name}.csv"
    if not p.exists():
        return []
    try:
        with open(p, "r", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []
