from pathlib import Path
import os

raw = os.environ.get("STRIPE_COOKIES_JSON", "").strip()
if not raw:
    raise SystemExit("❌ Missing STRIPE_COOKIES_JSON")

Path("data_output").mkdir(exist_ok=True)
Path("stripe_cookies.json").write_text(raw, encoding="utf-8")
Path("data_output/stripe_cookies.json").write_text(raw, encoding="utf-8")
print("✅ Stripe cookies restored from secret")
