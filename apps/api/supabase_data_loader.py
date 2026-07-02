"""Legacy module name kept only for imports. Backend is MongoDB only."""
from mongo_data_loader import *  # noqa: F401,F403
from mongo_client import get_mongo_status

def get_connection_status():
    return get_mongo_status()
