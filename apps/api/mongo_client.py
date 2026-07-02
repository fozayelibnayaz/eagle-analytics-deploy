"""
mongo_client.py
SINGLE SOURCE OF TRUTH — MongoDB connection for entire project.
Includes SSL fixes for macOS + older Python environments.
"""
import os
import ssl
import certifi
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import ConnectionFailure, DuplicateKeyError
from datetime import datetime

def _get_mongo_uri():
    try:
        import streamlit as st
        uri = st.secrets.get("MONGO_URI", "")
        if uri:
            return str(uri).strip()
    except Exception:
        pass
    uri = os.environ.get("MONGO_URI", "")
    if uri:
        return uri.strip()
    return "mongodb://localhost:27017"

def _get_db_name():
    try:
        import streamlit as st
        return str(st.secrets.get("MONGO_DB", "eagle3d")).strip()
    except Exception:
        pass
    return os.environ.get("MONGO_DB", "eagle3d")

_client = None
_db = None

def _make_client(uri):
    """Try multiple SSL configurations until one works."""
    errors = []

    # Attempt 1: certifi CA bundle (best)
    try:
        c = MongoClient(
            uri,
            serverSelectionTimeoutMS=10000,
            tls=True,
            tlsCAFile=certifi.where(),
        )
        c.admin.command("ping")
        print("[MongoDB] Connected with certifi TLS", flush=True)
        return c
    except Exception as e:
        errors.append(f"certifi: {str(e)[:80]}")

    # Attempt 2: allow invalid certs
    try:
        c = MongoClient(
            uri,
            serverSelectionTimeoutMS=10000,
            tls=True,
            tlsAllowInvalidCertificates=True,
        )
        c.admin.command("ping")
        print("[MongoDB] Connected with tlsAllowInvalidCertificates", flush=True)
        return c
    except Exception as e:
        errors.append(f"tlsAllowInvalid: {str(e)[:80]}")

    # Attempt 3: no TLS flags (works on some setups)
    try:
        c = MongoClient(uri, serverSelectionTimeoutMS=10000)
        c.admin.command("ping")
        print("[MongoDB] Connected with default settings", flush=True)
        return c
    except Exception as e:
        errors.append(f"default: {str(e)[:80]}")

    print(f"[MongoDB] All connection attempts failed:", flush=True)
    for err in errors:
        print(f"  {err}", flush=True)
    return None

def get_db():
    global _client, _db
    if _db is not None:
        return _db
    try:
        uri = _get_mongo_uri()
        db_name = _get_db_name()
        _client = _make_client(uri)
        if _client is None:
            return None
        _db = _client[db_name]
        return _db
    except Exception as e:
        print(f"[MongoDB] get_db failed: {e}", flush=True)
        return None

def col(name):
    db = get_db()
    if db is None:
        raise RuntimeError(f"MongoDB not connected — cannot access '{name}'")
    return db[name]

def find_all(collection_name, filters=None, projection=None, sort=None, limit=0):
    try:
        c = col(collection_name)
        query = filters or {}
        proj = {k: v for k, v in (projection or {}).items()}
        proj["_id"] = 0
        cursor = c.find(query, proj)
        if sort:
            cursor = cursor.sort(sort)
        if limit:
            cursor = cursor.limit(limit)
        return list(cursor)
    except Exception as e:
        print(f"[MongoDB] find_all({collection_name}) error: {e}", flush=True)
        return []

def find_one(collection_name, filters):
    try:
        result = col(collection_name).find_one(filters or {}, {"_id": 0})
        return result
    except Exception as e:
        print(f"[MongoDB] find_one({collection_name}) error: {e}", flush=True)
        return None

def count_docs(collection_name, filters=None):
    try:
        return col(collection_name).count_documents(filters or {})
    except Exception as e:
        print(f"[MongoDB] count_docs({collection_name}) error: {e}", flush=True)
        return 0

def upsert_one(collection_name, filter_key, document):
    try:
        c = col(collection_name)
        document["_updated_at"] = datetime.utcnow().isoformat()
        c.update_one(filter_key, {"$set": document}, upsert=True)
        return True
    except Exception as e:
        print(f"[MongoDB] upsert_one({collection_name}) error: {e}", flush=True)
        return False

def upsert_many(collection_name, documents, conflict_field):
    if not documents:
        return 0
    success = 0
    ts = datetime.utcnow().isoformat()
    c = col(collection_name)
    for doc in documents:
        try:
            doc_copy = dict(doc)
            doc_copy["_updated_at"] = ts
            if isinstance(conflict_field, list):
                filter_key = {k: doc_copy.get(k) for k in conflict_field if k in doc_copy}
            elif conflict_field and conflict_field in doc_copy:
                filter_key = {conflict_field: doc_copy[conflict_field]}
            else:
                filter_key = {}
            if filter_key:
                c.update_one(filter_key, {"$set": doc_copy}, upsert=True)
            else:
                c.insert_one(doc_copy)
            success += 1
        except Exception as e:
            print(f"[MongoDB] upsert_many error: {e}", flush=True)
    return success

def insert_many(collection_name, documents):
    if not documents:
        return 0
    try:
        ts = datetime.utcnow().isoformat()
        docs = [dict(d) for d in documents]
        for d in docs:
            d["_inserted_at"] = ts
        col(collection_name).insert_many(docs, ordered=False)
        return len(docs)
    except Exception as e:
        print(f"[MongoDB] insert_many({collection_name}) error: {e}", flush=True)
        return 0

def delete_many(collection_name, filters):
    try:
        result = col(collection_name).delete_many(filters or {})
        return result.deleted_count
    except Exception as e:
        print(f"[MongoDB] delete_many({collection_name}) error: {e}", flush=True)
        return 0

def aggregate(collection_name, pipeline):
    try:
        return list(col(collection_name).aggregate(pipeline))
    except Exception as e:
        print(f"[MongoDB] aggregate({collection_name}) error: {e}", flush=True)
        return []

def count_accepted(collection_name, date_field, date_gte=None, date_lte=None):
    filters = {"final_status": "ACCEPTED"}
    if date_gte or date_lte:
        filters[date_field] = {}
        if date_gte:
            filters[date_field]["$gte"] = str(date_gte)
        if date_lte:
            filters[date_field]["$lte"] = str(date_lte)
    return count_docs(collection_name, filters)

def get_analytics_cache(source, period_type, metric_date):
    return find_one("analytics_cache", {
        "source": source,
        "period_type": period_type,
        "metric_date": str(metric_date)
    })

def set_analytics_cache(source, period_type, metric_date, data_json, ttl_hours=24):
    upsert_one(
        "analytics_cache",
        {"source": source, "period_type": period_type, "metric_date": str(metric_date)},
        {
            "source": source,
            "period_type": period_type,
            "metric_date": str(metric_date),
            "data_json": data_json,
            "ttl_hours": ttl_hours,
            "cached_at": datetime.utcnow().isoformat()
        }
    )

def get_mongo_status():
    try:
        db = get_db()
        if db is None:
            return {
                "connected": False,
                "message": "MongoDB not connected. Set MONGO_URI in secrets.toml",
                "setup_steps": [
                    "1. Create free MongoDB Atlas at https://mongodb.com/atlas",
                    "2. Get connection string",
                    "3. Add MONGO_URI to .streamlit/secrets.toml",
                    "4. Add MONGO_DB = 'eagle3d' to secrets.toml",
                ]
            }
        count = db["daily_kpis"].count_documents({})
        return {
            "connected": True,
            "source": "mongodb",
            "daily_kpis_count": count,
            "message": f"MongoDB connected — {count} KPI rows"
        }
    except Exception as e:
        return {"connected": False, "message": str(e)}

if __name__ == "__main__":
    status = get_mongo_status()
    print(status)

# === MONGODB_ONLY_COMPAT_LAYER_START ===
# Added by fix_mongodb_only_system.py
# Purpose: keep legacy MongoDB-style .table().select().eq().execute() calls working,
# while actual storage remains 100% MongoDB.

from types import SimpleNamespace as _MongoCompatNamespace

try:
    from pymongo import ASCENDING as _MONGO_ASC, DESCENDING as _MONGO_DESC
except Exception:
    _MONGO_ASC, _MONGO_DESC = 1, -1

class _MongoCompatQuery:
    def __init__(self, collection, name):
        self.collection = collection
        self.name = name
        self.query = {}
        self.projection = {"_id": 0}
        self._count_exact = False
        self._sort = []
        self._limit = 0
        self._single = False

    def select(self, columns="*", count=None, **kwargs):
        self._count_exact = count == "exact" or kwargs.get("count") == "exact"
        if columns and columns not in ("*", "count"):
            proj = {}
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

    def gte(self, field, value):
        field = str(field)
        cur = self.query.get(field)
        if not isinstance(cur, dict):
            cur = {}
            self.query[field] = cur
        cur["$gte"] = str(value) if value is not None else value
        return self

    def lte(self, field, value):
        field = str(field)
        cur = self.query.get(field)
        if not isinstance(cur, dict):
            cur = {}
            self.query[field] = cur
        cur["$lte"] = str(value) if value is not None else value
        return self

    def gt(self, field, value):
        field = str(field)
        cur = self.query.get(field)
        if not isinstance(cur, dict):
            cur = {}
            self.query[field] = cur
        cur["$gt"] = value
        return self

    def lt(self, field, value):
        field = str(field)
        cur = self.query.get(field)
        if not isinstance(cur, dict):
            cur = {}
            self.query[field] = cur
        cur["$lt"] = value
        return self

    def in_(self, field, values):
        self.query[str(field)] = {"$in": list(values or [])}
        return self

    def is_(self, field, value):
        self.query[str(field)] = value
        return self

    def order(self, field, desc=False, ascending=None, **kwargs):
        if ascending is not None:
            desc = not bool(ascending)
        self._sort.append((str(field), _MONGO_DESC if desc else _MONGO_ASC))
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
            count_val = self.collection.count_documents(self.query) if self._count_exact else None
            cur = self.collection.find(self.query, self.projection)
            if self._sort:
                cur = cur.sort(self._sort)
            if self._limit:
                cur = cur.limit(self._limit)
            data = list(cur)
            if self._single:
                data = data[0] if data else None
            return _MongoCompatNamespace(
                data=data,
                count=count_val if count_val is not None else (1 if self._single and data else (len(data) if isinstance(data, list) else 0)),
                error=None,
            )
        except Exception as e:
            print(f"[MongoDB compat] query failed for {self.name}: {e}", flush=True)
            return _MongoCompatNamespace(data=None if self._single else [], count=0, error=e)

    def insert(self, rows):
        try:
            docs = rows if isinstance(rows, list) else [rows]
            docs = [dict(d) for d in docs]
            if docs:
                self.collection.insert_many(docs, ordered=False)
            return _MongoCompatNamespace(data=docs, count=len(docs), error=None)
        except Exception as e:
            return _MongoCompatNamespace(data=[], count=0, error=e)

    def upsert(self, rows, on_conflict=None, **kwargs):
        try:
            docs = rows if isinstance(rows, list) else [rows]
            docs = [dict(d) for d in docs]
            conflict = on_conflict or kwargs.get("on_conflict") or kwargs.get("conflict_field")
            conflict_fields = [x.strip() for x in str(conflict).split(",") if x.strip()] if conflict else []
            total = 0

            for doc in docs:
                filt = {k: doc.get(k) for k in conflict_fields if k in doc and doc.get(k) is not None}

                if not filt:
                    for k in ("email_normalized", "email", "date", "snapshot_date", "post_urn", "id"):
                        if k in doc and doc.get(k) is not None:
                            filt = {k: doc.get(k)}
                            break

                if filt:
                    self.collection.update_one(filt, {"$set": doc}, upsert=True)
                else:
                    self.collection.insert_one(doc)

                total += 1

            return _MongoCompatNamespace(data=docs, count=total, error=None)
        except Exception as e:
            return _MongoCompatNamespace(data=[], count=0, error=e)

    def delete(self):
        try:
            result = self.collection.delete_many(self.query)
            return _MongoCompatNamespace(data=[], count=result.deleted_count, error=None)
        except Exception as e:
            return _MongoCompatNamespace(data=[], count=0, error=e)

class _MongoCompatDB:
    def __init__(self, raw_db):
        self._raw_db = raw_db
        self.name = getattr(raw_db, "name", "mongodb")

    def __getitem__(self, name):
        return self._raw_db[name]

    def __getattr__(self, name):
        return getattr(self._raw_db, name)

    def table(self, name):
        return _MongoCompatQuery(self._raw_db[str(name)], str(name))

    def raw(self):
        return self._raw_db

_mongo_original_get_db = get_db
_mongo_compat_cached = None
_mongo_compat_raw_id = None

def get_db():
    global _mongo_compat_cached, _mongo_compat_raw_id
    raw = _mongo_original_get_db()
    if raw is None:
        return None

    if isinstance(raw, _MongoCompatDB):
        return raw

    raw_id = id(raw)
    if _mongo_compat_cached is not None and _mongo_compat_raw_id == raw_id:
        return _mongo_compat_cached

    _mongo_compat_cached = _MongoCompatDB(raw)
    _mongo_compat_raw_id = raw_id
    return _mongo_compat_cached

def get_raw_db():
    db = get_db()
    if db is None:
        return None
    return db.raw() if hasattr(db, "raw") else db

# === MONGODB_ONLY_COMPAT_LAYER_END ===
