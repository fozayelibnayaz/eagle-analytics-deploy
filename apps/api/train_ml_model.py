"""
from mongo_client import (
    get_db, find_all, find_one, count_docs, count_accepted,
    upsert_many, upsert_one, insert_many, delete_many,
    get_analytics_cache, set_analytics_cache, get_mongo_status
)
from mongo_data_loader import (
    load_daily_kpis, load_signups, load_uploads, load_payments,
    load_tab, read_tab_data, load_master_sheet_tab,
    load_ml_training_data, load_all_ml_training_tabs,
    get_kpi_counts, get_earliest_upload_date,
    sync_daily_kpis, sync_signups, sync_uploads, sync_payments,
    load_linkedin_posts, load_linkedin_followers_daily,
    load_linkedin_posts_daily, load_linkedin_highlights,
    get_connection_status
)

train_ml_model.py
Trains RandomForest classifier from January 2026 accurate dataset.
"""
import json
import os
import pickle
from pathlib import Path
from datetime import datetime

DATA_DIR = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)

GROUND_TRUTH_FILE = DATA_DIR / "ground_truth_jan2026.json"
MODEL_FILE = DATA_DIR / "email_classifier.pkl"


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [TrainML] {msg}", flush=True)


def make_unique_headers(headers):
    out, seen = [], {}
    for i, h in enumerate(headers):
        name = str(h).strip() if h else f"col_{i}"
        if not name: name = f"col_{i}"
        if name in seen:
            seen[name] += 1
            out.append(f"{name}_{seen[name]}")
        else:
            seen[name] = 1
            out.append(name)
    return out


def worksheet_to_dict_rows(ws):
    values = ws.get_all_values()
    if not values: return []
    headers = make_unique_headers(values[0])
    rows = []
    for raw in values[1:]:
        if len(raw) < len(headers):
            raw = raw + [""] * (len(headers) - len(raw))
        elif len(raw) > len(headers):
            raw = raw[:len(headers)]
        rows.append(dict(zip(headers, raw)))
    return rows


def fetch_ground_truth_from_sheet():
    #     
    sheet_url = "https://docs.google.com/spreadsheets/d/1lwffyXWOa7Q7xim2EX9i4AdIs7dtkjOPyKYVBtPpfgY"
    creds_file = "google_creds.json"
    if not os.path.exists(creds_file):
        env = os.environ.get("GOOGLE_CREDS_JSON")
        if env:
            with open(creds_file, "w") as f: f.write(env)
        else:
            log("No credentials")
            return None

    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = None  # MIGRATED: no credentials needed
    gc = None  # MIGRATED: no sheets client needed
    sh = None  # MIGRATED: use load_tab() from mongo_data_loader

    truth = []
    for ws in sh.worksheets():
        log(f"Reading tab: {ws.title}")
        try:
            rows = worksheet_to_dict_rows(ws)
        except Exception as e:
            log(f"  Failed to read {ws.title}: {e}")
            continue
        log(f"  Got {len(rows)} rows")
        for r in rows:
            email = None
            for k in ("Email", "email", "EMAIL"):
                if k in r and r[k] and "@" in str(r[k]):
                    email = str(r[k]).strip().lower()
                    break
            if email:
                truth.append({
                    "email": email, "label": "real",
                    "source_tab": ws.title,
                })

    GROUND_TRUTH_FILE.write_text(json.dumps(truth, indent=2))
    log(f"Saved {len(truth)} ground truth records")
    return truth


def generate_negative_examples():
    from email_intelligence import get_disposable_set
    import random
    random.seed(42)

    disp = list(get_disposable_set())[:300]
    fakes = ["test","fake","demo","abc","user","asdfgh","qwerty","noreply",
             "spam","x","aaa","zzz","junk","tmp","admin","info"]
    out = []
    for d in disp:
        for local in random.sample(fakes, 2):
            out.append({
                "email": f"{local}{random.randint(0,9999)}@{d}",
                "label": "fake", "source_tab": "synthetic",
            })
    return out


def extract_features(email):
    from email_intelligence import get_domain_intelligence, localpart_signals
    try:
        domain = email.split("@")[1]
        dom = get_domain_intelligence(domain)
        local = localpart_signals(email)
        return [
            int(dom.get("is_major_provider", False)),
            int(dom.get("is_disposable", False)),
            int(dom.get("mx_ok", False)),
            int(dom.get("has_spf", False)),
            int(dom.get("has_dmarc", False)),
            int(dom.get("has_a_record", False)),
            dom.get("domain_age_days") or 0,
            dom.get("reputation_score", 0.0),
            local["length"],
            local["digit_count"],
            local["entropy"],
            int(local["is_random_pattern"]),
            int(local["is_numeric_heavy"]),
            int(local["is_suspicious"]),
        ]
    except Exception:
        return None


def main():
    log("=" * 60)
    log("TRAINING ML EMAIL CLASSIFIER")
    log("=" * 60)

    if GROUND_TRUTH_FILE.exists():
        truth = json.loads(GROUND_TRUTH_FILE.read_text())
        log(f"Loaded {len(truth)} positives from cache")
    else:
        truth = fetch_ground_truth_from_sheet()
        if not truth:
            log("FAIL: no ground truth")
            return

    negatives = generate_negative_examples()
    log(f"Generated {len(negatives)} negatives")

    all_data = truth + negatives
    log(f"Total samples: {len(all_data)}")

    X, y = [], []
    for i, item in enumerate(all_data):
        f = extract_features(item["email"])
        if f is None: continue
        X.append(f)
        y.append(1 if item["label"] == "real" else 0)
        if (i+1) % 50 == 0:
            log(f"  Extracted features: {i+1}/{len(all_data)}")

    log(f"Training on {len(X)} samples ({sum(y)} real, {len(y)-sum(y)} fake)")

    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import classification_report
    except ImportError:
        log("Install: pip install scikit-learn")
        return

    if len(set(y)) < 2:
        log("Need both classes"); return

    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)
    model = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42)
    model.fit(X_tr, y_tr)

    log("\n=== Classification Report ===")
    log("\n" + classification_report(y_te, model.predict(X_te),
                                     target_names=["fake","real"]))

    with open(MODEL_FILE, "wb") as f:
        pickle.dump(model, f)
    log(f"Saved model: {MODEL_FILE}")


if __name__ == "__main__":
    main()
