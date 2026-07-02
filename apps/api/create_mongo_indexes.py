"""
create_mongo_indexes.py — Create all indexes in MongoDB
"""
from mongo_client import get_db
from pymongo import ASCENDING, DESCENDING

db = get_db()
if db is None:
    print("ERROR: MongoDB not connected")
    exit(1)

INDEXES = [
    ("daily_kpis",                   [("date", ASCENDING)],                                          True),
    ("signups",                      [("email_normalized", ASCENDING)],                              True),
    ("uploads",                      [("email_normalized", ASCENDING)],                              True),
    ("payments",                     [("email_normalized", ASCENDING)],                              True),
    ("linkedin_posts",               [("urn", ASCENDING)],                                           True),
    ("linkedin_posts_daily",         [("post_urn", ASCENDING), ("snapshot_date", ASCENDING)],        True),
    ("linkedin_followers_daily",     [("date", ASCENDING)],                                          True),
    ("linkedin_visitors_daily",      [("snapshot_date", ASCENDING)],                                 False),
    ("linkedin_competitors_daily",   [("snapshot_date", ASCENDING), ("name", ASCENDING)],            True),
    ("linkedin_search_keywords",     [("snapshot_date", ASCENDING), ("keyword", ASCENDING)],         True),
    ("linkedin_newsletter_articles", [("urn", ASCENDING)],                                           True),
    ("linkedin_highlights_daily",    [("snapshot_date", ASCENDING)],                                 False),
    ("analytics_cache",              [("source", ASCENDING), ("period_type", ASCENDING), ("metric_date", ASCENDING)], True),
    ("access_control",               [("email", ASCENDING)],                                         True),
    ("access_log",                   [("timestamp", DESCENDING)],                                    False),
    ("manual_overrides",             [("is_active", ASCENDING)],                                     False),
    ("customer_success_master",      [("email", ASCENDING)],                                         False),
    ("customer_success_enriched",    [("email", ASCENDING)],                                         False),
]

print("\n" + "="*50)
print("CREATING MONGODB INDEXES")
print("="*50)

for collection_name, fields, unique in INDEXES:
    try:
        c = db[collection_name]
        c.create_index(fields, unique=unique, sparse=True)
        field_str = ", ".join(f"{f[0]}" for f in fields)
        print(f"  OK  {collection_name:<42} [{field_str}]  unique={unique}")
    except Exception as e:
        print(f"  ERR {collection_name}: {e}")

print("\nINDEXES_CREATED")
