"""
ml_intelligence.py
LAYER 5 - ML INTELLIGENCE
- Trained on accurate data (legitimacy + conversion likelihood)
- Predicts: legitimacy_score (0-1), conversion_score (0-1)
- Retrains weekly as more verified data accumulates
"""
import os
import re
import json
import pickle
from pathlib import Path
from datetime import datetime, timedelta

DATA_DIR  = Path("data_output")
MODEL_DIR = Path("models")
MODEL_DIR.mkdir(exist_ok=True)

LEGIT_MODEL_FILE   = MODEL_DIR / "legitimacy_model.pkl"
CONVERT_MODEL_FILE = MODEL_DIR / "conversion_model.pkl"
LAST_TRAIN_FILE    = MODEL_DIR / "last_trained.txt"

PROFESSIONAL_DOMAINS = {
    "gmail.com","yahoo.com","hotmail.com","outlook.com",
    "icloud.com","protonmail.com","me.com","live.com",
}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [ML] {msg}", flush=True)


# ─── Feature extraction ────────────────────────────────
def extract_features(row: dict) -> dict:
    """Extract features for ML scoring."""
    email = ""
    for k in ("Email","email","__email_normalized__","__normalized_email__"):
        if k in row and row[k] and "@" in str(row[k]):
            email = str(row[k]).strip().lower()
            break
    
    domain = email.split("@")[-1] if "@" in email else ""
    local  = email.split("@")[0]  if "@" in email else ""
    
    lead_source = ""
    for k, v in row.items():
        if "lead" in k.lower() or "source" in k.lower():
            if v:
                lead_source = str(v).lower()
                break
    
    has_phone = False
    phone_len = 0
    for k, v in row.items():
        if "phone" in k.lower() and v:
            has_phone = True
            phone_len = len(str(v))
            break
    
    return {
        "domain_is_pro":      1 if domain in PROFESSIONAL_DOMAINS else 0,
        "domain_is_custom":   1 if (domain and "." in domain
                                    and domain not in PROFESSIONAL_DOMAINS) else 0,
        "local_has_dot":      1 if "." in local else 0,
        "local_has_underscore": 1 if "_" in local else 0,
        "local_has_dash":     1 if "-" in local else 0,
        "local_is_digits":    1 if local.isdigit() else 0,
        "local_length":       len(local),
        "local_has_random_pattern": 1 if re.match(r'^[a-z]{2,4}\d{3,}$', local) else 0,
        "local_is_namelike":  1 if re.match(r'^[a-zA-Z]+[\.\-_][a-zA-Z]+$', local) else 0,
        "domain_length":      len(domain),
        "lead_source_len":    len(lead_source),
        "lead_source_quality":
            2 if any(s in lead_source for s in ["recommend","friend","colleague","linkedin"])
            else 1 if any(s in lead_source for s in ["google","youtube","instagram","gemini","chatgpt","ai"])
            else 0,
        "has_phone":          1 if has_phone else 0,
        "phone_length":       phone_len,
    }


# ─── Heuristic scoring (fallback if no model) ─────────
def heuristic_legitimacy_score(features: dict) -> float:
    score = 0.5
    
    if features["domain_is_pro"]:    score += 0.10
    if features["domain_is_custom"]: score += 0.20  # company email
    if features["local_is_namelike"]: score += 0.15
    if features["local_has_dot"]:    score += 0.05
    if features["local_is_digits"]:  score -= 0.30
    if features["local_has_random_pattern"]: score -= 0.10
    if features["lead_source_quality"] >= 2: score += 0.15
    elif features["lead_source_quality"] >= 1: score += 0.05
    if features["has_phone"]:        score += 0.05
    if features["phone_length"] > 10: score += 0.05
    
    return round(min(max(score, 0.0), 1.0), 3)


def heuristic_conversion_score(features: dict) -> float:
    """Higher = more likely to become paid customer."""
    score = 0.3  # most don't convert
    
    if features["domain_is_custom"]: score += 0.20
    if features["lead_source_quality"] >= 2: score += 0.15
    if features["has_phone"] and features["phone_length"] > 10: score += 0.10
    if features["local_is_namelike"]: score += 0.05
    if features["local_is_digits"]:  score -= 0.15
    if features["local_has_random_pattern"]: score -= 0.10
    
    return round(min(max(score, 0.0), 1.0), 3)


# ─── Model loading ─────────────────────────────────────
def load_models():
    """Load trained models if available."""
    legit_model   = None
    convert_model = None
    
    try:
        if LEGIT_MODEL_FILE.exists():
            with open(LEGIT_MODEL_FILE, "rb") as f:
                legit_model = pickle.load(f)
            log(f"Loaded legitimacy model from {LEGIT_MODEL_FILE}")
    except Exception as e:
        log(f"Legitimacy model load failed: {e}")
    
    try:
        if CONVERT_MODEL_FILE.exists():
            with open(CONVERT_MODEL_FILE, "rb") as f:
                convert_model = pickle.load(f)
            log(f"Loaded conversion model from {CONVERT_MODEL_FILE}")
    except Exception as e:
        log(f"Conversion model load failed: {e}")
    
    return legit_model, convert_model


# ─── Scoring ────────────────────────────────────────────
def score_rows(rows: list) -> list:
    """Add ML scores to each row."""
    legit_model, convert_model = load_models()
    
    scored = []
    for row in rows:
        features = extract_features(row)
        
        # Legitimacy score
        if legit_model:
            try:
                import numpy as np
                X = np.array([[features[k] for k in sorted(features.keys())]])
                legit = float(legit_model.predict_proba(X)[0][1])
            except Exception:
                legit = heuristic_legitimacy_score(features)
        else:
            legit = heuristic_legitimacy_score(features)
        
        # Conversion score
        if convert_model:
            try:
                import numpy as np
                X = np.array([[features[k] for k in sorted(features.keys())]])
                convert = float(convert_model.predict_proba(X)[0][1])
            except Exception:
                convert = heuristic_conversion_score(features)
        else:
            convert = heuristic_conversion_score(features)
        
        scored.append({
            **row,
            "__ml_legitimacy_score__":   round(legit, 3),
            "__ml_conversion_score__":   round(convert, 3),
            "__ml_combined_score__":     round((legit + convert) / 2, 3),
            "__ml_scored_at__":          datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    
    return scored


# ─── Training (weekly) ─────────────────────────────────
def needs_retrain() -> bool:
    """Check if model needs retraining (weekly)."""
    if not LAST_TRAIN_FILE.exists():
        return True
    try:
        last = datetime.fromisoformat(LAST_TRAIN_FILE.read_text().strip())
        return (datetime.now() - last) > timedelta(days=7)
    except Exception:
        return True




def _retry_503(func, max_retries=3, *args, **kwargs):
    """Retry on 503 Service Unavailable errors."""
    import time as _time
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if "503" in str(e) and attempt < max_retries - 1:
                wait = 30 * (attempt + 1)
                print(f"[ML] 503 error, retrying in {wait}s (attempt {attempt+1}/{max_retries})", flush=True)
                _time.sleep(wait)
                continue
            raise

def train_models():
    """
    Train models on accurate data sheet.
    Uses sklearn GradientBoostingClassifier.
    """
    accurate_url = os.environ.get(
        "ACCURATE_DATA_SHEET_URL",
        "https://docs.google.com/spreadsheets/d/1lwffyXWOa7Q7xim2EX9i4AdIs7dtkjOPyKYVBtPpfgY"
    )
    
    if not accurate_url:
        log("No ACCURATE_DATA_SHEET_URL - skipping training")
        return
    
    try:
        from sklearn.ensemble import GradientBoostingClassifier
        import numpy as np
    except ImportError:
        log("sklearn not installed - cannot train. Install: pip install scikit-learn")
        return
    
    log("Loading training data from accurate sheet...")
    
    try:
        from sheets_writer import _get_client
        gc, _ = _get_client()
        ss = gc.open_by_url(accurate_url)
        
        # Collect labeled data
        legit_X, legit_y = [], []
        convert_X, convert_y = [], []
        
        for ws in ss.worksheets():
            try:
                rows = _retry_503(ws.get_all_records)
                tab_name = ws.title.lower()
                
                # Determine labels from tab name
                is_legit = "verified" in tab_name or "good" in tab_name or "real" in tab_name
                is_paid  = "paid" in tab_name or "stripe" in tab_name or "customer" in tab_name
                
                for row in rows:
                    features = extract_features(row)
                    feat_vec = [features[k] for k in sorted(features.keys())]
                    legit_X.append(feat_vec)
                    legit_y.append(1 if is_legit else 0)
                    convert_X.append(feat_vec)
                    convert_y.append(1 if is_paid else 0)
                
                log(f"  {ws.title}: {len(rows)} samples (legit={is_legit}, paid={is_paid})")
            except Exception as e:
                log(f"  {ws.title}: error - {e}")
        
        if len(set(legit_y)) < 2:
            log("Not enough labeled diversity for legitimacy model")
            return
        
        # Train
        log(f"Training legitimacy model on {len(legit_X)} samples...")
        X = np.array(legit_X)
        y = np.array(legit_y)
        legit_model = GradientBoostingClassifier(n_estimators=50, max_depth=3, random_state=42)
        legit_model.fit(X, y)
        with open(LEGIT_MODEL_FILE, "wb") as f:
            pickle.dump(legit_model, f)
        log(f"  Saved: {LEGIT_MODEL_FILE}")
        
        if len(set(convert_y)) >= 2:
            log(f"Training conversion model on {len(convert_X)} samples...")
            X = np.array(convert_X)
            y = np.array(convert_y)
            convert_model = GradientBoostingClassifier(n_estimators=50, max_depth=3, random_state=42)
            convert_model.fit(X, y)
            with open(CONVERT_MODEL_FILE, "wb") as f:
                pickle.dump(convert_model, f)
            log(f"  Saved: {CONVERT_MODEL_FILE}")
        
        # Mark trained
        LAST_TRAIN_FILE.write_text(datetime.now().isoformat())
        log("Training complete")
        
    except Exception as e:
        log(f"Training failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    if needs_retrain():
        log("Models need retraining (weekly schedule)")
        train_models()
    else:
        log("Models are recent - skipping training")
    
    # Test scoring
    test_rows = [
        {"Email":"john.doe@company.com","Lead Source":"LinkedIn","Phone":"+12345678901"},
        {"Email":"abc123@yopmail.com","Lead Source":"test"},
    ]
    scored = score_rows(test_rows)
    for r in scored:
        print(f"\n{r['Email']}")
        print(f"  Legitimacy: {r['__ml_legitimacy_score__']}")
        print(f"  Conversion: {r['__ml_conversion_score__']}")


# ─── Simple monthly predictor ─────────────────────────────────
def predict_monthly_metrics(month: str, lookback_days: int = 30):
    """Predict best/likely/worst for SignUps, FirstUploads, Paid for given month.
    month: 'YYYY-MM' string
    Returns dict {metric: {current, best, likely, worst, remaining_days, projected}}"""
    from sheets_writer import read_tab_data
    from datetime import datetime, date

    daily = read_tab_data('Daily_Counts')
    # metrics column mapping
    metric_cols = {
        'SignUps': 'SignUps_Accepted',
        'FirstUploads': 'FirstUploads_Accepted',
        'Paid': 'PaidSubscribers_Accepted'
    }

    # Parse month
    try:
        ym = datetime.strptime(month, '%Y-%m')
    except Exception:
        return {}

    # current sum for month
    month_rows = [r for r in daily if r.get('Date','').startswith(month)]
    current = {m: sum(int(float(r.get(c,0) or 0)) for r in month_rows) for m,c in metric_cols.items()}

    # build recent daily series (last lookback_days)
    all_dates = sorted({r.get('Date') for r in daily if r.get('Date')})
    recent_dates = [d for d in all_dates if d]
    # take last lookback_days
    recent = recent_dates[-lookback_days:] if len(recent_dates) >= lookback_days else recent_dates

    stats = {}
    for metric, col in metric_cols.items():
        # daily values for recent days
        vals = []
        for d in recent:
            rows = [r for r in daily if r.get('Date') == d]
            val = 0
            if rows:
                val = int(float(rows[0].get(col,0) or 0))
            vals.append(val)

        if not vals:
            avg = 0
            mn = 0
            mx = 0
        else:
            avg = sum(vals)/len(vals)
            mn = min(vals)
            mx = max(vals)

        # days in target month
        year = ym.year
        month_idx = ym.month
        # compute days in month
        import calendar
        days_in_month = calendar.monthrange(year, month_idx)[1]
        # days elapsed so far in that month (based on today)
        today = date.today()
        if today.year == year and today.month == month_idx:
            elapsed = today.day
        else:
            # if month in past, assume full month elapsed
            elapsed = days_in_month

        remaining = max(days_in_month - elapsed, 0)

        # projected totals
        # worst: assume remaining days will have min daily rate
        worst_proj = current[metric] + int(mn * remaining)
        # likely: use avg daily
        likely_proj = current[metric] + int(avg * remaining)
        # best: use max daily
        best_proj = current[metric] + int(mx * remaining)

        stats[metric] = {
            'current': current[metric],
            'best': best_proj,
            'likely': likely_proj,
            'worst': worst_proj,
            'remaining_days': remaining,
            'avg_daily': round(avg,2),
            'min_daily': mn,
            'max_daily': mx
        }

    return stats
