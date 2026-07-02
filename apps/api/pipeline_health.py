"""
pipeline_health.py
Tracks pipeline health: cookie expiry, scrape failures, last successful run.
Writes to data_output/pipeline_health.json
Dashboard reads this to show alerts.
"""
import json
from pathlib import Path
from datetime import datetime, timedelta

DATA_DIR = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)

HEALTH_FILE = DATA_DIR / "pipeline_health.json"


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [Health] {msg}", flush=True)


def load_health():
    if not HEALTH_FILE.exists():
        return {
            "kpi": {"status": "unknown", "last_success": None, "last_failure": None,
                     "consecutive_failures": 0, "last_error": None},
            "stripe": {"status": "unknown", "last_success": None, "last_failure": None,
                        "consecutive_failures": 0, "last_error": None,
                        "cookie_age_days": None},
            "process": {"status": "unknown", "last_success": None, "last_failure": None},
            "alerts_sent": {},
        }
    try:
        with open(HEALTH_FILE) as f:
            return json.load(f)
    except Exception:
        return load_health.__wrapped__() if hasattr(load_health, "__wrapped__") else {}


def save_health(health):
    try:
        with open(HEALTH_FILE, "w") as f:
            json.dump(health, f, indent=2, sort_keys=True, default=str)
    except Exception as e:
        log(f"Save error: {e}")


def record_success(stage):
    """Mark a stage as successful."""
    health = load_health()
    if stage not in health:
        health[stage] = {}
    health[stage]["status"] = "ok"
    health[stage]["last_success"] = datetime.now().isoformat()
    health[stage]["consecutive_failures"] = 0
    health[stage]["last_error"] = None
    save_health(health)
    log(f"{stage}: marked SUCCESS")


def record_failure(stage, error_msg, error_type=None):
    """Mark a stage as failed."""
    health = load_health()
    if stage not in health:
        health[stage] = {}
    health[stage]["status"] = "failed"
    health[stage]["last_failure"] = datetime.now().isoformat()
    health[stage]["consecutive_failures"] = health[stage].get("consecutive_failures", 0) + 1
    health[stage]["last_error"] = str(error_msg)[:500]
    if error_type:
        health[stage]["error_type"] = error_type
    save_health(health)
    log(f"{stage}: marked FAILURE: {error_msg[:100]}")


def detect_stripe_cookie_issue(error_msg):
    """Returns True if error suggests Stripe cookies are expired/invalid."""
    if not error_msg:
        return False
    error_lower = str(error_msg).lower()
    cookie_indicators = [
        "login", "signin", "sign-in", "401", "unauthorized",
        "authentication", "session expired", "logged out",
        "no cookies", "cookie expired", "auth token",
    ]
    return any(ind in error_lower for ind in cookie_indicators)


def get_health_summary():
    """Get human-readable health summary."""
    health = load_health()
    issues = []
    
    for stage in ["kpi", "stripe", "process"]:
        s = health.get(stage, {})
        if s.get("status") == "failed":
            issues.append({
                "stage": stage,
                "consecutive_failures": s.get("consecutive_failures", 0),
                "last_error": s.get("last_error", "unknown"),
            })
    
    # Specific Stripe cookie warning
    stripe = health.get("stripe", {})
    cookie_warning = None
    if stripe.get("status") == "failed":
        if detect_stripe_cookie_issue(stripe.get("last_error", "")):
            cookie_warning = {
                "type": "stripe_cookies_expired",
                "consecutive_failures": stripe.get("consecutive_failures", 0),
                "last_failure": stripe.get("last_failure"),
            }
    
    return {
        "overall_ok": len(issues) == 0,
        "issues": issues,
        "cookie_warning": cookie_warning,
    }


def should_send_alert(alert_key, cooldown_hours=12):
    """Don't spam alerts - only send if we haven't sent same alert recently."""
    health = load_health()
    alerts = health.get("alerts_sent", {})
    
    last_sent = alerts.get(alert_key)
    if not last_sent:
        return True
    
    try:
        last_dt = datetime.fromisoformat(last_sent)
        if datetime.now() - last_dt > timedelta(hours=cooldown_hours):
            return True
    except Exception:
        return True
    
    return False


def mark_alert_sent(alert_key):
    """Record that we sent this alert."""
    health = load_health()
    if "alerts_sent" not in health:
        health["alerts_sent"] = {}
    health["alerts_sent"][alert_key] = datetime.now().isoformat()
    save_health(health)


if __name__ == "__main__":
    log("Pipeline health summary:")
    summary = get_health_summary()
    print(json.dumps(summary, indent=2, default=str))
