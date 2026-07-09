"""
mongo_client.py — Eagle 3D Streaming Analytics Hub
==================================================
100% MongoDB local connection layer.
Also provides a compat shim so old .table().select().eq().execute()
calls keep working during the transition.

Requirements:
  - MongoDB running on localhost:27017
  - Database name: eagle3d (or set MONGO_DB env / secret)
  - Python: pymongo>=4.7
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Sequence

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import PyMongoError

# ─────────────────────────────────────────────────────────────────
# CONFIG RESOLUTION (env → Streamlit secrets → default local)
# ─────────────────────────────────────────────────────────────────
_DEFAULT_URI = "mongodb://localhost:27017"
_DEFAULT_DB  = "eagle3d"


def _resolve_secret(name: str, default: str = "") -> str:
    val = os.environ.get(name, "").strip()
    if val:
        return val
    try:
        import streamlit as st  # optional at import time
        val = str(st.secrets.get(name, "") or "").strip()
        if val:
            return val
    except Exception:
        pass
    return default


def _mongo_uri() -> str:
    return _resolve_secret("MONGO_URI", _DEFAULT_URI)


def _mongo_db_name() -> str:
    return _resolve_secret("MONGO_DB", _DEFAULT_DB)


# ─────────────────────────────────────────────────────────────────
# CONNECTION (cached client)
# ─────────────────────────────────────────────────────────────────
_CLIENT: Optional[MongoClient] = None
_DB_NAME: Optional[str] = None


def _client() -> Optional[MongoClient]:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    try:
        _CLIENT = MongoClient(
            _mongo_uri(),
            serverSelectionTimeoutMS=3000,
            connectTimeoutMS=3000,
        )
        # Force connection check
        _CLIENT.admin.command("ping")
        return _CLIENT
    except Exception as e:
        print(f"[mongo_client] Connection failed: {e}", flush=True)
        _CLIENT = None
        return None


def _raw_db():
    """Returns the raw pymongo Database, or None."""
    global _DB_NAME
    c = _client()
    if c is None:
        return None
    _DB_NAME = _mongo_db_name()
    return c[_DB_NAME]


# ─────────────────────────────────────────────────────────────────
# BASIC CRUD HELPERS (used across the app)
# ─────────────────────────────────────────────────────────────────
def find_all(
    collection: str,
    filters: Optional[Dict[str, Any]] = None,
    projection: Optional[Dict[str, int]] = None,
    sort: Optional[Sequence] = None,
    limit: int = 0,
) -> List[Dict[str, Any]]:
    db = _raw_db()
    if db is None:
        return []
    try:
        proj = projection if projection is not None else {"_id": 0}
        if "_id" not in proj:
            proj["_id"] = 0
        cur = db[collection].find(filters or {}, proj)
        if sort:
            cur = cur.sort(list(sort))
        if limit and limit > 0:
            cur = cur.limit(int(limit))
        return list(cur)
    except PyMongoError as e:
        print(f"[mongo_client] find_all({collection}) failed: {e}", flush=True)
        return []


def find_one(
    collection: str,
    filters: Optional[Dict[str, Any]] = None,
    projection: Optional[Dict[str, int]] = None,
) -> Optional[Dict[str, Any]]:
    db = _raw_db()
    if db is None:
        return None
    try:
        proj = projection if projection is not None else {"_id": 0}
        if "_id" not in proj:
            proj["_id"] = 0
        return db[collection].find_one(filters or {}, proj)
    except PyMongoError as e:
        print(f"[mongo_client] find_one({collection}) failed: {e}", flush=True)
        return None


def count_docs(collection: str, filters: Optional[Dict[str, Any]] = None) -> int:
    db = _raw_db()
    if db is None:
        return 0
    try:
        return int(db[collection].count_documents(filters or {}))
    except PyMongoError:
        return 0


def count_accepted(
    collection: str,
    date_field: Optional[str] = None,
    date_gte: Optional[str] = None,
    date_lte: Optional[str] = None,
) -> int:
    """Count docs where final_status == 'ACCEPTED' with optional date range."""
    filters: Dict[str, Any] = {"final_status": "ACCEPTED"}
    if date_field and (date_gte or date_lte):
        rng: Dict[str, Any] = {}
        if date_gte:
            rng["$gte"] = str(date_gte)
        if date_lte:
            rng["$lte"] = str(date_lte)
        filters[date_field] = rng
    return count_docs(collection, filters)


def insert_many(collection: str, docs: Iterable[Dict[str, Any]]) -> int:
    docs = list(docs or [])
    if not docs:
        return 0
    db = _raw_db()
    if db is None:
        return 0
    try:
        for d in docs:
            d["_inserted_at"] = datetime.now(timezone.utc).isoformat()
        db[collection].insert_many(docs, ordered=False)
        return len(docs)
    except PyMongoError as e:
        print(f"[mongo_client] insert_many({collection}) failed: {e}", flush=True)
        return 0


def upsert_one(
    collection: str,
    doc: Dict[str, Any],
    key_fields: Sequence[str],
) -> bool:
    if not doc or not key_fields:
        return False
    db = _raw_db()
    if db is None:
        return False
    try:
        filt = {k: doc.get(k) for k in key_fields if doc.get(k) is not None}
        if not filt:
            return False
        doc["_updated_at"] = datetime.now(timezone.utc).isoformat()
        db[collection].update_one(filt, {"$set": doc}, upsert=True)
        return True
    except PyMongoError as e:
        print(f"[mongo_client] upsert_one({collection}) failed: {e}", flush=True)
        return False


def upsert_many(
    collection: str,
    docs: Iterable[Dict[str, Any]],
    key_field_or_fields,
) -> int:
    docs = list(docs or [])
    if not docs:
        return 0
    if isinstance(key_field_or_fields, str):
        key_fields = [k.strip() for k in key_field_or_fields.split(",") if k.strip()]
    else:
        key_fields = list(key_field_or_fields or [])
    if not key_fields:
        return 0

    db = _raw_db()
    if db is None:
        return 0

    saved = 0
    for d in docs:
        filt = {k: d.get(k) for k in key_fields if d.get(k) is not None}
        if not filt:
            continue
        try:
            d["_updated_at"] = datetime.now(timezone.utc).isoformat()
            db[collection].update_one(filt, {"$set": d}, upsert=True)
            saved += 1
        except PyMongoError as e:
            print(f"[mongo_client] upsert_many item failed ({collection}): {e}", flush=True)
    return saved


def delete_many(collection: str, filters: Dict[str, Any]) -> int:
    if not filters:
        return 0
    db = _raw_db()
    if db is None:
        return 0
    try:
        res = db[collection].delete_many(filters)
        return int(res.deleted_count or 0)
    except PyMongoError:
        return 0


# ─────────────────────────────────────────────────────────────────
# LIGHTWEIGHT ANALYTICS CACHE (used by GA4/YouTube/LinkedIn loaders)
# ─────────────────────────────────────────────────────────────────
_CACHE_COL = "analytics_cache"


def get_analytics_cache(key: str) -> Optional[Dict[str, Any]]:
    doc = find_one(_CACHE_COL, {"key": key})
    return doc.get("value") if doc else None


def set_analytics_cache(key: str, value: Any) -> bool:
    return upsert_one(_CACHE_COL, {"key": key, "value": value}, ["key"])


# ─────────────────────────────────────────────────────────────────
# STATUS / DIAGNOSTICS
# ─────────────────────────────────────────────────────────────────
def get_mongo_status() -> Dict[str, Any]:
    db = _raw_db()
    if db is None:
        return {
            "connected": False,
            "source": "mongodb",
            "uri": _mongo_uri(),
            "db": _mongo_db_name(),
            "message": (
                "MongoDB not reachable. Verify: "
                "brew services list | grep mongodb "
                "and MONGO_URI in .streamlit/secrets.toml"
            ),
        }
    try:
        kpi_count = db["daily_kpis"].count_documents({}) if "daily_kpis" in db.list_collection_names() else 0
        return {
            "connected": True,
            "source": "mongodb",
            "uri": _mongo_uri(),
            "db": _mongo_db_name(),
            "collections": len(db.list_collection_names()),
            "daily_kpis_count": kpi_count,
            "message": f"MongoDB connected — db={_mongo_db_name()}, {kpi_count} daily_kpis rows",
        }
    except Exception as e:
        return {"connected": False, "source": "mongodb", "message": str(e)}


# ═════════════════════════════════════════════════════════════════
# COMPAT LAYER: keeps old .table().select() code working on MongoDB
# Supports: db.table("x").select(...).eq(...).order(...).limit(...).execute()
# ═════════════════════════════════════════════════════════════════
class _CompatQuery:
    def __init__(self, collection, name: str):
        self.collection = collection
        self.name = name
        self.query: Dict[str, Any] = {}
        self.projection: Dict[str, int] = {"_id": 0}
        self._count_exact = False
        self._sort: List = []
        self._limit = 0
        self._single = False

    def select(self, columns: str = "*", count: str = None, **kwargs):
        self._count_exact = (count == "exact") or (kwargs.get("count") == "exact")
        if columns and columns not in ("*", "count"):
            proj: Dict[str, int] = {}
            for col in str(columns).split(","):
                col = col.strip()
                if col:
                    proj[col] = 1
            proj["_id"] = 0
            self.projection = proj
        return self

    def eq(self, field, value):
        self.query[str(field)] = value
        return self

    def neq(self, field, value):
        self.query[str(field)] = {"$ne": value}
        return self

    def _range_op(self, field, op, value):
        field = str(field)
        cur = self.query.get(field)
        if not isinstance(cur, dict):
            cur = {}
            self.query[field] = cur
        cur[op] = str(value) if value is not None and op in ("$gte", "$lte") else value
        return self

    def gte(self, field, value): return self._range_op(field, "$gte", value)
    def lte(self, field, value): return self._range_op(field, "$lte", value)
    def gt(self,  field, value): return self._range_op(field, "$gt",  value)
    def lt(self,  field, value): return self._range_op(field, "$lt",  value)

    def in_(self, field, values):
        self.query[str(field)] = {"$in": list(values or [])}
        return self

    def is_(self, field, value):
        self.query[str(field)] = value
        return self

    def order(self, field, desc=False, ascending=None, **kwargs):
        if ascending is not None:
            desc = not bool(ascending)
        self._sort.append((str(field), DESCENDING if desc else ASCENDING))
        return self

    def limit(self, n):
        self._limit = int(n or 0)
        return self

    def range(self, start, end):
        try:
            self._limit = max(0, int(end) - int(start) + 1)
        except Exception:
            pass
        return self

    def single(self):
        self._single = True
        self._limit = 1
        return self

    def execute(self):
        try:
            count_val = None
            if self._count_exact:
                count_val = self.collection.count_documents(self.query)
            cur = self.collection.find(self.query, self.projection)
            if self._sort:
                cur = cur.sort(self._sort)
            if self._limit:
                cur = cur.limit(self._limit)
            data = list(cur)
            if self._single:
                data = data[0] if data else None
            return SimpleNamespace(
                data=data,
                count=count_val if count_val is not None else (
                    1 if (self._single and data) else (len(data) if isinstance(data, list) else 0)
                ),
                error=None,
            )
        except PyMongoError as e:
            print(f"[mongo_client compat] query failed for {self.name}: {e}", flush=True)
            return SimpleNamespace(data=None if self._single else [], count=0, error=e)

    def insert(self, rows):
        try:
            docs = rows if isinstance(rows, list) else [rows]
            docs = [dict(d) for d in docs]
            if docs:
                self.collection.insert_many(docs, ordered=False)
            return SimpleNamespace(data=docs, count=len(docs), error=None)
        except PyMongoError as e:
            return SimpleNamespace(data=[], count=0, error=e)

    def upsert(self, rows, on_conflict=None, **kwargs):
        try:
            docs = rows if isinstance(rows, list) else [rows]
            docs = [dict(d) for d in docs]
            conflict = on_conflict or kwargs.get("on_conflict") or kwargs.get("conflict_field")
            conflict_fields = (
                [x.strip() for x in str(conflict).split(",") if x.strip()]
                if conflict else []
            )
            total = 0
            for doc in docs:
                filt = {k: doc.get(k) for k in conflict_fields if k in doc and doc.get(k) is not None}
                if not filt:
                    for k in ("email_normalized", "email", "date",
                              "snapshot_date", "post_urn", "id"):
                        if k in doc and doc.get(k) is not None:
                            filt = {k: doc.get(k)}
                            break
                if filt:
                    self.collection.update_one(filt, {"$set": doc}, upsert=True)
                else:
                    self.collection.insert_one(doc)
                total += 1
            return SimpleNamespace(data=docs, count=total, error=None)
        except PyMongoError as e:
            return SimpleNamespace(data=[], count=0, error=e)

    def delete(self):
        try:
            result = self.collection.delete_many(self.query)
            return SimpleNamespace(data=[], count=result.deleted_count, error=None)
        except PyMongoError as e:
            return SimpleNamespace(data=[], count=0, error=e)


class _CompatDB:
    def __init__(self, raw):
        self._raw = raw
        self.name = getattr(raw, "name", _mongo_db_name())

    def __getitem__(self, name):
        return self._raw[name]

    def __getattr__(self, name):
        return getattr(self._raw, name)

    def table(self, name):
        return _CompatQuery(self._raw[str(name)], str(name))

    def raw(self):
        return self._raw


_COMPAT_CACHE: Optional[_CompatDB] = None
_COMPAT_RAW_ID: Optional[int] = None


def get_db():
    """Returns MongoDB database wrapped with a compat shim (legacy API)."""
    global _COMPAT_CACHE, _COMPAT_RAW_ID
    raw = _raw_db()
    if raw is None:
        return None
    if isinstance(raw, _CompatDB):
        return raw
    raw_id = id(raw)
    if _COMPAT_CACHE is not None and _COMPAT_RAW_ID == raw_id:
        return _COMPAT_CACHE
    _COMPAT_CACHE = _CompatDB(raw)
    _COMPAT_RAW_ID = raw_id
    return _COMPAT_CACHE


def get_raw_db():
    """Returns the raw pymongo Database (no compat shim)."""
    db = get_db()
    if db is None:
        return None
    return db.raw() if hasattr(db, "raw") else db


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    print(json.dumps(get_mongo_status(), indent=2, default=str))
