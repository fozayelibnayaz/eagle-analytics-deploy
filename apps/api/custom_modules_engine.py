
"""
Custom Team Modules Engine — MongoDB only.

Allows teams like HR, Customer Success, Marketing, Sales, Finance, etc.
to create their own dashboard tab from Settings by uploading a CSV/XLSX.

Collections:
- custom_modules
- custom_module_<slug>
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Any, Optional

import pandas as pd

from mongo_client import get_db, upsert_one, find_all, delete_many


def slugify(name: str) -> str:
    s = str(name or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "custom_module"


def module_collection(slug: str) -> str:
    return f"custom_module_{slugify(slug)}"


def list_modules(active_only: bool = True) -> List[Dict[str, Any]]:
    q = {"is_active": True} if active_only else {}
    rows = find_all("custom_modules", q, sort=[("created_at", -1)])
    return rows or []


def get_module(slug: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    if db is None:
        return None
    return db["custom_modules"].find_one({"slug": slugify(slug)}, {"_id": 0})


def create_module(
    name: str,
    description: str = "",
    team: str = "",
    requested_analysis: str = "",
    created_by: str = "system",
) -> Dict[str, Any]:
    db = get_db()
    if db is None:
        return {"success": False, "message": "MongoDB not connected"}

    clean_name = str(name or "").strip()
    if not clean_name:
        return {"success": False, "message": "Module name is required"}

    slug = slugify(clean_name)

    doc = {
        "slug": slug,
        "name": clean_name,
        "team": str(team or clean_name).strip(),
        "description": str(description or "").strip(),
        "requested_analysis": str(requested_analysis or "").strip(),
        "collection": module_collection(slug),
        "is_active": True,
        "created_by": str(created_by or "system"),
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }

    db["custom_modules"].update_one(
        {"slug": slug},
        {"$set": doc},
        upsert=True,
    )

    return {"success": True, "message": f"Module created: {clean_name}", "module": doc}


def deactivate_module(slug: str) -> Dict[str, Any]:
    db = get_db()
    if db is None:
        return {"success": False, "message": "MongoDB not connected"}

    db["custom_modules"].update_one(
        {"slug": slugify(slug)},
        {"$set": {"is_active": False, "updated_at": datetime.utcnow().isoformat()}},
    )

    return {"success": True, "message": "Module deactivated"}


def read_uploaded_file(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name.lower()

    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file)

    if name.endswith(".xlsx") or name.endswith(".xls"):
        return pd.read_excel(uploaded_file)

    raise ValueError("Only CSV/XLS/XLSX files are supported")


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Normalize column names
    df.columns = [
        re.sub(r"_+", "_", re.sub(r"[^a-zA-Z0-9]+", "_", str(c).strip())).strip("_") or f"col_{i}"
        for i, c in enumerate(df.columns)
    ]

    # Remove fully empty rows/cols
    df = df.dropna(axis=0, how="all")
    df = df.dropna(axis=1, how="all")

    # Convert unsupported values to strings/primitive values
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].astype(str)

    return df


def ingest_dataframe(slug: str, df: pd.DataFrame, replace: bool = True) -> Dict[str, Any]:
    db = get_db()
    if db is None:
        return {"success": False, "message": "MongoDB not connected"}

    slug = slugify(slug)
    module = get_module(slug)

    if not module:
        return {"success": False, "message": f"Module not found: {slug}"}

    df = clean_dataframe(df)
    collection = module_collection(slug)

    records = df.fillna("").to_dict("records")
    now = datetime.utcnow().isoformat()

    for idx, row in enumerate(records):
        row["_row_index"] = idx
        row["_module_slug"] = slug
        row["_ingested_at"] = now

    if replace:
        db[collection].delete_many({})

    if records:
        db[collection].insert_many(records, ordered=False)

    db["custom_modules"].update_one(
        {"slug": slug},
        {
            "$set": {
                "row_count": len(records),
                "columns": list(df.columns),
                "last_ingested_at": now,
                "updated_at": now,
            }
        },
    )

    return {
        "success": True,
        "message": f"Ingested {len(records)} rows into {module.get('name', slug)}",
        "rows": len(records),
        "columns": list(df.columns),
    }


def get_module_df(slug: str, limit: int = 5000) -> pd.DataFrame:
    rows = find_all(module_collection(slug), limit=limit)
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    drop_cols = [c for c in ["_id", "_module_slug", "_ingested_at"] if c in df.columns]
    df = df.drop(columns=drop_cols, errors="ignore")
    return df


def summarize_dataframe(df: pd.DataFrame) -> Dict[str, Any]:
    if df is None or df.empty:
        return {
            "rows": 0,
            "columns": 0,
            "numeric_columns": [],
            "date_columns": [],
            "text_columns": [],
            "missing_cells": 0,
        }

    numeric_cols = []
    date_cols = []
    text_cols = []

    for c in df.columns:
        series = df[c]

        converted_num = pd.to_numeric(series, errors="coerce")
        if converted_num.notna().sum() >= max(3, len(series) * 0.5):
            numeric_cols.append(c)
            continue

        converted_date = pd.to_datetime(series, errors="coerce")
        if converted_date.notna().sum() >= max(3, len(series) * 0.5):
            date_cols.append(c)
            continue

        text_cols.append(c)

    return {
        "rows": len(df),
        "columns": len(df.columns),
        "numeric_columns": numeric_cols,
        "date_columns": date_cols,
        "text_columns": text_cols,
        "missing_cells": int(df.isna().sum().sum()),
    }


def generate_auto_insights(df: pd.DataFrame, requested_analysis: str = "") -> List[str]:
    insights = []
    summary = summarize_dataframe(df)

    insights.append(f"Dataset has {summary['rows']:,} rows and {summary['columns']:,} columns.")

    if summary["missing_cells"]:
        insights.append(f"There are {summary['missing_cells']:,} missing cells. Consider cleaning required fields.")

    if summary["numeric_columns"]:
        for c in summary["numeric_columns"][:5]:
            vals = pd.to_numeric(df[c], errors="coerce").dropna()
            if not vals.empty:
                insights.append(
                    f"{c}: total={vals.sum():,.2f}, avg={vals.mean():,.2f}, min={vals.min():,.2f}, max={vals.max():,.2f}"
                )

    if summary["date_columns"]:
        c = summary["date_columns"][0]
        dates = pd.to_datetime(df[c], errors="coerce").dropna()
        if not dates.empty:
            insights.append(f"Date range in {c}: {dates.min().date()} to {dates.max().date()}")

    if requested_analysis:
        insights.append(f"Requested analysis focus: {requested_analysis}")

    return insights
