# dashboard.py — Redirect to app.py (v4)
# Streamlit Cloud is configured to run this file.
# This simply delegates to the real app.
import os, runpy
os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
runpy.run_path("app.py", run_name="__main__")
