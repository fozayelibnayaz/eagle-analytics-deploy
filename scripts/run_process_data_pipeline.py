from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import process_data as pd

results = {}

called = False
for name in [
    "process_signups",
    "process_uploads",
    "process_first_uploads",
    "process_payments",
]:
    fn = getattr(pd, name, None)
    if callable(fn):
        print(f"Running {name}() ...")
        results[name] = fn()
        called = True

if not called:
    main = getattr(pd, "main", None)
    if callable(main):
        print("Running process_data.main() ...")
        results["main"] = main()
        called = True

if not called:
    raise SystemExit("❌ No callable processing entrypoint found in process_data.py")

print(results)
