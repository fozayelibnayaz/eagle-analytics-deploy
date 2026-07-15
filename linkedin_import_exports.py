from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from io import StringIO

import pandas as pd

from mongo_client import delete_many, find_one, insert_many, upsert_one

EXPORT_DIR = Path("downloads/linkedin_exports")
JSON_DIR = Path("data_output/linkedin_exports_json")
JSON_DIR.mkdir(parents=True, exist_ok=True)

FILE_META_COL = "linkedin_export_files"
ROW_COL = "linkedin_export_rows"


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [LI-import] {msg}", flush=True)


def infer_dataset_key(filename: str) -> str:
    name = filename.lower()
    for key in [
        "updates",
        "content",
        "visitors",
        "followers",
        "search_appearances",
        "search-appearances",
        "competitors",
        "leads",
    ]:
        if key in name:
            return key.replace("-", "_")
    if "__" in filename:
        return filename.split("__", 1)[0]
    return "unknown"


def clean_value(v: Any):
    try:
        import pandas as _pd
        if _pd.isna(v):
            return None
    except Exception:
        pass

    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            pass

    if isinstance(v, str):
        s = v.strip()
        return s if s != "" else None

    return v


def dataframe_to_rows(df: pd.DataFrame) -> List[Dict[str, Any]]:
    cols = [str(c).strip() for c in df.columns]
    rows = []
    for _, row in df.iterrows():
        obj = {}
        for col in cols:
            obj[col] = clean_value(row[col])
        rows.append(obj)
    return rows


def try_excel_parse(path: Path):
    # 1) calamine first (best chance for odd xls/xlsx)
    for engine in ("calamine", "xlrd", None):
        try:
            xls = pd.ExcelFile(path, engine=engine)
            sheets = {}
            for name in xls.sheet_names:
                df = pd.read_excel(path, sheet_name=name, engine=engine)
                sheets[str(name)] = dataframe_to_rows(df)
            if sheets:
                return sheets, f"excel_{engine or 'auto'}"
        except Exception as e:
            log(f"Excel parse with engine={engine or 'auto'} failed for {path.name}: {e}")

    raise RuntimeError(f"All Excel engines failed for {path.name}")


def try_html_parse(path: Path):
    raw = path.read_bytes()
    encodings = ["utf-8", "utf-8-sig", "utf-16-le", "latin-1"]

    for enc in encodings:
        try:
            text = raw.decode(enc, errors="ignore")
        except Exception:
            continue

        low = text.lower()
        if "<table" not in low and "<html" not in low:
            continue

        for flavor in (None, "lxml", "html5lib", "bs4"):
            try:
                if flavor is None:
                    tables = pd.read_html(StringIO(text))
                else:
                    tables = pd.read_html(StringIO(text), flavor=flavor)
                sheets = {}
                for i, df in enumerate(tables, start=1):
                    sheets[f"{enc}_table_{i}"] = dataframe_to_rows(df)
                if sheets:
                    return sheets, f"html_{enc}_{flavor or 'auto'}"
            except Exception:
                continue

    raise RuntimeError(f"HTML parse failed for {path.name}")


def try_tsv_parse(path: Path):
    raw = path.read_bytes()
    encodings = ["utf-16-le", "utf-8", "utf-8-sig", "latin-1"]

    for enc in encodings:
        try:
            text = raw.decode(enc, errors="ignore")
        except Exception:
            continue

        if "\t" not in text:
            continue

        try:
            df = pd.read_csv(StringIO(text), sep="\t")
            return {"tsv_1": dataframe_to_rows(df)}, f"tsv_{enc}"
        except Exception:
            continue

    raise RuntimeError(f"TSV parse failed for {path.name}")


def parse_export_file(path: Path):
    try:
        return try_excel_parse(path)
    except Exception as e:
        log(str(e))

    try:
        return try_html_parse(path)
    except Exception as e:
        log(str(e))

    try:
        return try_tsv_parse(path)
    except Exception as e:
        log(str(e))

    raise RuntimeError(f"Could not parse export file: {path}")


def import_one(path: Path) -> Dict[str, Any]:
    stat = path.stat()
    meta_key = {
        "file_name": path.name,
        "file_size": int(stat.st_size),
    }

    existing = find_one(FILE_META_COL, meta_key)
    if existing and existing.get("status") == "imported":
        return {
            "file": path.name,
            "status": "skipped_already_imported",
            "rows": int(existing.get("row_count", 0) or 0),
        }

    dataset_key = infer_dataset_key(path.name)
    sheets, parse_mode = parse_export_file(path)

    delete_many(ROW_COL, {"file_name": path.name})

    all_rows = []
    total_rows = 0

    for sheet_name, rows in sheets.items():
        out_json = JSON_DIR / f"{path.stem}__{sheet_name}.json"
        out_json.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")

        for i, row in enumerate(rows):
            all_rows.append({
                "file_name": path.name,
                "dataset_key": dataset_key,
                "sheet_name": sheet_name,
                "row_index": i,
                "row_data": row,
                "file_mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "imported_at": datetime.utcnow().isoformat(),
            })
        total_rows += len(rows)

    if all_rows:
        insert_many(ROW_COL, all_rows)

    upsert_one(FILE_META_COL, {
        "file_name": path.name,
        "file_size": int(stat.st_size),
        "dataset_key": dataset_key,
        "parse_mode": parse_mode,
        "sheet_count": len(sheets),
        "row_count": total_rows,
        "status": "imported",
        "imported_at": datetime.utcnow().isoformat(),
        "file_mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
    }, ["file_name", "file_size"])

    return {
        "file": path.name,
        "status": "imported",
        "dataset_key": dataset_key,
        "parse_mode": parse_mode,
        "rows": total_rows,
        "sheets": len(sheets),
    }


def main():
    if not EXPORT_DIR.exists():
        raise SystemExit(f"Export directory not found: {EXPORT_DIR}")

    files = sorted(
        [p for p in EXPORT_DIR.iterdir() if p.is_file() and p.suffix.lower() in {".xls", ".xlsx", ".csv", ".bin"}],
        key=lambda p: p.stat().st_mtime,
    )

    if not files:
        print("No LinkedIn export files found.")
        return

    results = []
    for f in files:
        log(f"Importing {f.name}")
        try:
            results.append(import_one(f))
        except Exception as e:
            log(f"FAILED {f.name}: {e}")
            upsert_one(FILE_META_COL, {
                "file_name": f.name,
                "file_size": int(f.stat().st_size),
                "dataset_key": infer_dataset_key(f.name),
                "status": "failed",
                "error": str(e),
                "imported_at": datetime.utcnow().isoformat(),
            }, ["file_name", "file_size"])
            results.append({
                "file": f.name,
                "status": "failed",
                "error": str(e),
            })

    print()
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
