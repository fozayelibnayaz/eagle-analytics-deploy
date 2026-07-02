"""Legacy module name kept only for imports. Backend is MongoDB only."""
from mongo_client import get_db, get_mongo_status

def get_supabase():
    return get_db()

def get_client():
    return get_db()

def get_status():
    return get_mongo_status()
