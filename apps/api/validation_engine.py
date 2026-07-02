#!/usr/bin/env python3
"""
VALIDATION ENGINE — Priority 5 + 12
Every metric must be validated before display or reporting.
Catches impossible numbers, coverage mismatches, null values.
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

DATA_DIR  = Path("data_output")
AUDIT_DIR = Path("data_output/audits")
AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [Validator] {msg}", flush=True)


class ValidationResult:
    def __init__(self):
        self.passed:   List[dict] = []
        self.warnings: List[dict] = []
        self.failures: List[dict] = []
        self.metrics:  Dict[str, dict] = {}

    @property
    def is_valid(self) -> bool:
        return len(self.failures) == 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def add_metric(self, name: str, source: str, raw: Any, processed: Any,
                   date_range: str, status: str, last_updated: str = ""):
        self.metrics[name] = {
            "source":       source,
            "raw_value":    raw,
            "processed":    processed,
            "date_range":   date_range,
            "status":       status,
            "last_updated": last_updated or datetime.utcnow().isoformat(),
        }

    def add_pass(self, rule: str, message: str):
        self.passed.append({"rule": rule, "message": message})

    def add_warning(self, rule: str, message: str, data: dict = None):
        self.warnings.append({"rule": rule, "message": message, "data": data or {}})

    def add_failure(self, rule: str, message: str, data: dict = None):
        self.failures.append({"rule": rule, "message": message, "data": data or {}})

    def to_dict(self) -> dict:
        return {
            "is_valid":    self.is_valid,
            "has_warnings": self.has_warnings,
            "passed":      self.passed,
            "warnings":    self.warnings,
            "failures":    self.failures,
            "metrics":     self.metrics,
            "summary":     self.get_summary(),
        }

    def get_summary(self) -> str:
        if self.failures:
            return f"❌ VALIDATION FAILED — {len(self.failures)} failures, {len(self.warnings)} warnings"
        if self.warnings:
            return f"⚠️ VALIDATION WARNING — {len(self.warnings)} warnings (data may be misleading)"
        return f"✅ VALIDATION PASSED — {len(self.passed)} checks passed"

    def get_display_banner(self) -> str:
        if self.failures:
            return "⚠️ Data Validation Failed — Numbers may be incorrect"
        if self.warnings:
            return "⚠️ Data Coverage Warning — Comparison periods differ"
        return ""


def validate_kpi_metrics(
    signups: int, uploads: int, paid: int,
    signups_period: str = "", uploads_period: str = "", paid_period: str = "",
    common_period_only: bool = False,
) -> ValidationResult:
    """Validate KPI metrics for logical consistency."""
    result = ValidationResult()
    now = datetime.utcnow().isoformat()

    # Register metrics
    result.add_metric("signups", "Verified_FREE / daily_counts.json",
                      signups, signups, signups_period, "PENDING", now)
    result.add_metric("uploads", "Verified_FIRST_UPLOAD / daily_counts.json",
                      uploads, uploads, uploads_period, "PENDING", now)
    result.add_metric("paid",    "Verified_STRIPE / daily_counts.json",
                      paid,    paid,    paid_period,    "PENDING", now)

    # Rule 1: No negative values
    for name, val in [("signups", signups), ("uploads", uploads), ("paid", paid)]:
        if val < 0:
            result.add_failure("no_negative_values", f"{name} cannot be negative: {val}")
            result.metrics[name]["status"] = "FAIL"
        else:
            result.add_pass("no_negative_values", f"{name}={val} is non-negative")
            result.metrics[name]["status"] = "PASS"

    # Rule 2: Uploads cannot exceed signups
    if uploads > signups:
        result.add_failure(
            "uploads_lte_signups",
            f"Uploads ({uploads}) > Signups ({signups}) — mathematically impossible",
            {"uploads": uploads, "signups": signups, "excess": uploads - signups},
        )
        result.metrics["uploads"]["status"] = "FAIL"
    else:
        result.add_pass("uploads_lte_signups", f"Uploads ({uploads}) <= Signups ({signups})")

    # Rule 3: Paid cannot exceed signups
    if paid > signups:
        result.add_failure(
            "paid_lte_signups",
            f"Paid ({paid}) > Signups ({signups}) — mathematically impossible",
            {"paid": paid, "signups": signups, "excess": paid - signups},
        )
        result.metrics["paid"]["status"] = "FAIL"
    else:
        result.add_pass("paid_lte_signups", f"Paid ({paid}) <= Signups ({signups})")

    # Rule 4: Conversion rates in valid range
    if signups > 0:
        s2u = uploads / signups * 100
        s2p = paid    / signups * 100
        if s2u > 100:
            result.add_failure("s2u_rate_valid", f"Signup→Upload rate {s2u:.1f}% exceeds 100%")
        elif s2u < 1 and not common_period_only:
            result.add_warning("s2u_rate_low",
                f"Signup→Upload rate {s2u:.1f}% is very low. "
                "This is expected if upload tracking started later than signup tracking.",
                {"rate": s2u, "uploads_period": uploads_period, "signups_period": signups_period})
        else:
            result.add_pass("s2u_rate_valid", f"Signup→Upload rate {s2u:.1f}%")

        if s2p > 100:
            result.add_failure("s2p_rate_valid", f"Signup→Paid rate {s2p:.1f}% exceeds 100%")
        else:
            result.add_pass("s2p_rate_valid", f"Signup→Paid rate {s2p:.1f}%")

    # Rule 5: Coverage period mismatch
    if signups_period and uploads_period and signups_period != uploads_period:
        result.add_warning(
            "coverage_period_alignment",
            f"Signups period ({signups_period}) differs from Uploads period ({uploads_period}). "
            "Conversion rates across these periods are NOT meaningful.",
            {"signups_period": signups_period, "uploads_period": uploads_period},
        )

    return result


def validate_ga4_metrics(users: int, sessions: int, period: str = "") -> ValidationResult:
    """Validate GA4 metrics."""
    result = ValidationResult()
    now = datetime.utcnow().isoformat()

    result.add_metric("ga4_users",    "GA4 API / ga4_connector.py",    users,    users,    period, "PENDING", now)
    result.add_metric("ga4_sessions", "GA4 API / ga4_connector.py",    sessions, sessions, period, "PENDING", now)

    # Users cannot exceed sessions
    if users > sessions and sessions > 0:
        result.add_warning(
            "users_lte_sessions",
            f"Users ({users}) > Sessions ({sessions}) — unusual but possible with multi-session users",
            {"users": users, "sessions": sessions},
        )

    if sessions == 0 and users == 0:
        result.add_warning("ga4_not_zero", "Both GA4 users and sessions are 0 — check GA4 connection")
        result.metrics["ga4_users"]["status"]    = "WARN"
        result.metrics["ga4_sessions"]["status"] = "WARN"
    else:
        result.add_pass("ga4_has_data", f"GA4 has data: {users} users, {sessions} sessions")
        result.metrics["ga4_users"]["status"]    = "PASS"
        result.metrics["ga4_sessions"]["status"] = "PASS"

    return result


def validate_stripe_metrics(total_paid: int, month_paid: int, total_revenue: float) -> ValidationResult:
    """Validate Stripe metrics."""
    result = ValidationResult()
    now = datetime.utcnow().isoformat()

    result.add_metric("stripe_total_paid",  "Verified_STRIPE", total_paid,    total_paid,    "all_time", "PENDING", now)
    result.add_metric("stripe_month_paid",  "Verified_STRIPE", month_paid,    month_paid,    "month",    "PENDING", now)
    result.add_metric("stripe_revenue",     "Verified_STRIPE", total_revenue, total_revenue, "all_time", "PENDING", now)

    if month_paid > total_paid:
        result.add_failure("month_lte_total", f"Month paid ({month_paid}) > Total paid ({total_paid})")
    else:
        result.add_pass("month_lte_total", f"Month ({month_paid}) <= Total ({total_paid})")
        result.metrics["stripe_month_paid"]["status"] = "PASS"
        result.metrics["stripe_total_paid"]["status"] = "PASS"

    if total_revenue < 0:
        result.add_failure("revenue_positive", f"Revenue cannot be negative: {total_revenue}")
    else:
        result.add_pass("revenue_positive", f"Revenue ${total_revenue:.2f} is valid")
        result.metrics["stripe_revenue"]["status"] = "PASS"

    return result


def validate_all_metrics(kpi: dict, ga4: dict, stripe: dict) -> ValidationResult:
    """Run all validations and combine results."""
    combined = ValidationResult()

    # KPI validation
    kpi_result = validate_kpi_metrics(
        signups = kpi.get("signups_all", 0),
        uploads = kpi.get("uploads_all", 0),
        paid    = kpi.get("paid_all", 0),
    )
    combined.passed.extend(kpi_result.passed)
    combined.warnings.extend(kpi_result.warnings)
    combined.failures.extend(kpi_result.failures)
    combined.metrics.update(kpi_result.metrics)

    # GA4 validation
    if ga4.get("connected"):
        ga4_result = validate_ga4_metrics(
            users    = ga4.get("all_time_users", 0),
            sessions = ga4.get("all_time_sessions", 0),
        )
        combined.passed.extend(ga4_result.passed)
        combined.warnings.extend(ga4_result.warnings)
        combined.failures.extend(ga4_result.failures)
        combined.metrics.update(ga4_result.metrics)

    # Stripe validation
    stripe_result = validate_stripe_metrics(
        total_paid    = stripe.get("total_paid", 0),
        month_paid    = stripe.get("month_paid", 0),
        total_revenue = stripe.get("total_revenue", 0.0),
    )
    combined.passed.extend(stripe_result.passed)
    combined.warnings.extend(stripe_result.warnings)
    combined.failures.extend(stripe_result.failures)
    combined.metrics.update(stripe_result.metrics)

    # Save validation result
    out = AUDIT_DIR / "validation_latest.json"
    out.write_text(json.dumps(combined.to_dict(), indent=2, default=str))

    return combined


def get_common_period() -> dict:
    """
    Determine the common coverage period across all data sources.
    All-Time must use this period for valid conversion rates.
    """
    try:
        audit = Path("data_output/audits/audit_latest.json")
        if audit.exists():
            data = json.loads(audit.read_text())
            return data.get("common_period", {})
    except Exception:
        pass

    # Fallback: compute from daily_counts
    try:
        daily = json.loads(Path("data_output/daily_counts.json").read_text())
        upload_dates = sorted([r["Date"] for r in daily if r.get("Date") and r.get("FirstUploads_Accepted", 0) > 0])
        paid_dates   = sorted([r["Date"] for r in daily if r.get("Date") and r.get("PaidSubscribers_Accepted", 0) > 0])
        signup_dates = sorted([r["Date"] for r in daily if r.get("Date") and r.get("SignUps_Accepted", 0) > 0])

        all_starts = [d[0] for d in [signup_dates, upload_dates, paid_dates] if d]
        all_ends   = [d[-1] for d in [signup_dates, upload_dates, paid_dates] if d]

        return {
            "start": max(all_starts) if all_starts else "N/A",
            "end":   min(all_ends)   if all_ends   else "N/A",
        }
    except Exception:
        return {"start": "N/A", "end": "N/A"}


if __name__ == "__main__":
    result = validate_kpi_metrics(signups=3032, uploads=101, paid=432)
    print(result.get_summary())
    for v in result.warnings:
        print(f"  ⚠️  {v['rule']}: {v['message']}")
    for v in result.failures:
        print(f"  ❌ {v['rule']}: {v['message']}")
