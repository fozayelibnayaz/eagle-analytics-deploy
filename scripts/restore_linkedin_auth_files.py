from pathlib import Path
import os

Path("data").mkdir(exist_ok=True)
Path("data_output").mkdir(exist_ok=True)

cookies = os.environ.get("LINKEDIN_COOKIES_JSON", "").strip()
state = os.environ.get("LINKEDIN_STORAGE_STATE_JSON", "").strip()

if state:
    Path("data/linkedin_session_state.json").write_text(state, encoding="utf-8")
    Path("data_output/linkedin_session_state.json").write_text(state, encoding="utf-8")
    Path("data/linkedin_storage_state_runtime.json").write_text(state, encoding="utf-8")
    Path("data_output/linkedin_storage_state_runtime.json").write_text(state, encoding="utf-8")
    print("✅ Restored LinkedIn storage state from secret")

if cookies:
    Path("data/linkedin_cookies.json").write_text(cookies, encoding="utf-8")
    Path("data_output/linkedin_cookies.json").write_text(cookies, encoding="utf-8")
    print("✅ Restored LinkedIn cookies from secret")

if not state and not cookies:
    raise SystemExit("❌ Neither LINKEDIN_STORAGE_STATE_JSON nor LINKEDIN_COOKIES_JSON is set")
