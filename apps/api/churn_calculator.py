#!/usr/bin/env python3
# CHURN RATE AND AVG SUBSCRIPTION CALCULATOR - Priority 8 - Fixed v3
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

DATA_DIR = Path("data_output")
log = lambda m: print(f"[{datetime.now().strftime('%H:%M:%S')}] [Churn] {m}", flush=True)


def _safe_float(val) -> float:
    if not val and val != 0:
        return 0.0
    s = str(val).strip()
    if s in ("", "nan", "None", "-", "--"):
        return 0.0
    # Remove currency symbols, commas, newlines, USD suffix
    s = re.sub(r"[$,€£\s\n\r]", "", s)
    s = re.sub(r"[A-Za-z]+$", "", s)  # remove trailing letters like USD, EUR
    s = s.strip()
    if not s:
        return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0


def _safe_date(val) -> Optional[str]:
    if not val or str(val).strip() in ("", "nan", "None", "--", "-"):
        return None
    raw = str(val).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
        "%m/%d/%y, %I:%M %p", "%m/%d/%Y, %I:%M %p",
        "%-m/%-d/%y, %-I:%M %p",
        "%b %d, %Y", "%d %b %Y",
    ):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def _get_email(row: dict) -> str:
    for k in ("__email_normalized__", "Email", "email", "EMAIL"):
        v = row.get(k, "")
        if v and "@" in str(v):
            return str(v).strip().lower()
    return ""


def _get_amount(row: dict) -> float:
    # Priority order based on debug output:
    # 1. "Amount" field - already parsed float, most reliable
    # 2. "Total spend" - has "$300.00\nUSD" format, needs cleaning
    # 3. "__amount__" - stored but was 0.0 in debug
    # 4. Other fallbacks

    # Try Amount first (already a number in most rows)
    v = row.get("Amount", "")
    if v and str(v).strip() not in ("", "nan", "None", "0", "0.0"):
        f = _safe_float(v)
        if f > 0:
            return f

    # Try Total spend (has "$300.00\nUSD" format)
    v = row.get("Total spend", "") or row.get("Total Spend", "")
    if v and str(v).strip() not in ("", "nan", "None"):
        f = _safe_float(v)
        if f > 0:
            return f

    # Try __amount__
    v = row.get("__amount__", 0)
    if v and float(str(v).strip() or "0") > 0:
        f = _safe_float(v)
        if f > 0:
            return f

    return 0.0


def _get_date(row: dict) -> Optional[str]:
    # Priority: First payment > row_date_used > Created
    for k in ("First payment", "row_date_used", "Created", "Created (UTC)", "__scraped_date__"):
        v = row.get(k, "")
        d = _safe_date(v)
        if d:
            return d
    return None


def calculate_churn_and_subscription(stripe_rows: list) -> dict:
    result = {
        "churn_rate":                None,
        "churn_rate_display":        "Not Available",
        "churn_reason":              "",
        "avg_subscription":          None,
        "avg_subscription_display":  "Not Available",
        "avg_subscription_reason":   "",
        "total_revenue":             0.0,
        "total_paid":                0,
        "monthly_paid":              0,
        "calculation_date":          datetime.now().strftime("%Y-%m-%d"),
    }

    if not stripe_rows:
        result["churn_reason"]            = "No Stripe data available"
        result["avg_subscription_reason"] = "No Stripe data available"
        return result

    accepted = [r for r in stripe_rows if str(r.get("final_status", "")).upper() == "ACCEPTED"]

    if not accepted:
        result["churn_reason"]            = "No accepted Stripe customers"
        result["avg_subscription_reason"] = "No accepted Stripe customers"
        return result

    # ── Average Subscription ──
    amounts      = [_get_amount(r) for r in accepted]
    nonzero_amts = [a for a in amounts if a > 0]
    total_spend  = sum(amounts)
    total_count  = len(accepted)

    result["total_revenue"] = round(total_spend, 2)
    result["total_paid"]    = total_count

    if total_count > 0 and total_spend > 0:
        avg = total_spend / total_count
        result["avg_subscription"]         = round(avg, 2)
        result["avg_subscription_display"] = f"${avg:,.2f}"
        result["avg_subscription_reason"]  = (
            f"Based on {total_count} customers, "
            f"{len(nonzero_amts)} have spend data, "
            f"${total_spend:,.2f} total revenue"
        )
    elif len(nonzero_amts) == 0:
        result["avg_subscription_reason"] = (
            f"Cannot calculate: {total_count} customers all show $0 spend. "
            "Check Stripe scraper is capturing Amount or Total spend column."
        )
    else:
        result["avg_subscription_reason"] = (
            f"Cannot calculate: {total_count} customers, ${total_spend:.2f} total"
        )

    # ── Churn Rate ──
    # We only have first payment dates, not subscription end dates.
    # Cannot calculate true churn without cancel events.
    # Show meaningful stats instead of wrong number.

    today         = datetime.now()
    cur_month     = today.strftime("%Y-%m")
    prev_month    = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    monthly_new   = {}
    undated       = 0

    for r in accepted:
        d = _get_date(r)
        if d:
            m = d[:7]
            monthly_new[m] = monthly_new.get(m, 0) + 1
        else:
            undated += 1

    new_this_month = monthly_new.get(cur_month,  0)
    new_last_month = monthly_new.get(prev_month, 0)
    result["monthly_paid"] = new_this_month

    # Churn cannot be calculated from first-payment-only data
    result["churn_rate"]         = None
    result["churn_rate_display"] = "Not Available"
    result["churn_reason"] = (
        f"Churn requires subscription cancel/end dates which are not captured by scraper. "
        f"New subscribers this month ({cur_month}): {new_this_month}. "
        f"New subscribers last month ({prev_month}): {new_last_month}. "
        f"Total active subscribers in Stripe: {total_count}. "
        f"To calculate churn accurately: connect Stripe API with STRIPE_SECRET_KEY "
        f"and use subscription cancel events."
    )

    log(f"Total={total_count} NewThisMonth={new_this_month} AvgSub=${avg if total_spend > 0 else 0:.2f} TotalRevenue=${total_spend:,.2f}")
    return result


def get_churn_display(stripe_rows: list = None) -> dict:
    if stripe_rows is None:
        try:
            from sheets_writer import read_tab_data
            stripe_rows = read_tab_data("Verified_STRIPE")
        except Exception as e:
            return {
                "churn_rate_display":       "Not Available",
                "avg_subscription_display": "Not Available",
                "churn_reason":             f"Could not load Stripe data: {e}",
                "avg_subscription_reason":  f"Could not load Stripe data: {e}",
            }
    return calculate_churn_and_subscription(stripe_rows)


if __name__ == "__main__":
    result = get_churn_display()
    print(json.dumps(result, indent=2))
