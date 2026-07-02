#!/usr/bin/env python3
"""
from mongo_client import (
    get_db, find_all, find_one, count_docs, count_accepted,
    upsert_many, upsert_one, insert_many, delete_many,
    get_analytics_cache, set_analytics_cache, get_mongo_status
)
    load_daily_kpis, load_signups, load_uploads, load_payments,
    load_tab, read_tab_data, get_kpi_counts, get_earliest_upload_date,
    sync_daily_kpis, sync_signups, sync_uploads, sync_payments,
    load_linkedin_posts, load_linkedin_followers_daily,
    load_linkedin_posts_daily, load_linkedin_highlights,
    get_connection_status, load_all_ml_training_tabs
)
    get_db, find_all, find_one, count_docs, count_accepted,
    upsert_many, upsert_one, insert_many, delete_many,
    get_analytics_cache, set_analytics_cache, get_mongo_status
)
    load_daily_kpis, load_signups, load_uploads, load_payments,
    load_tab, read_tab_data, load_master_sheet_tab,
    load_ml_training_data, load_all_ml_training_tabs,
    get_kpi_counts, get_earliest_upload_date,
    sync_daily_kpis, sync_signups, sync_uploads, sync_payments,
    load_linkedin_posts, load_linkedin_followers_daily,
    load_linkedin_posts_daily, load_linkedin_highlights,
    get_connection_status
)

Customer Success Scraper
Scrapes ALL tabs from: https://docs.google.com/spreadsheets/d/1sSaJ-4RusYSz8eAbycLeDkCC1LFXPY-4ErffDVQieAU
Stores in MongoDB: customer_success_<tab_slug>

Then enriches with:
- Stripe payment data (matched by email)
- Signup date (from signups table)
- First upload date (from uploads table)
- Total spend, last payment, subscription status
"""

import os
import re
import json
from datetime import datetime
from pathlib import Path

CS_SHEET_URL = "https://docs.google.com/spreadsheets/d/1sSaJ-4RusYSz8eAbycLeDkCC1LFXPY-4ErffDVQieAU/edit"


def log(m):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [CS] {m}", flush=True)


def _slugify(name):
    return re.sub(r"[^a-z0-9_]", "_", name.lower().strip()).strip("_")[:60]


def _get_sb():
    return get_db()


def _get_sheet_client():
        
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly",
              "https://www.googleapis.com/auth/drive.readonly"]

    creds = None
    try:
        import streamlit as st
        d = dict(st.secrets["GOOGLE_CREDS"])
        if "private_key" in d:
            d["private_key"] = d["private_key"].replace("\\n", "\n")
        creds = service_account.Credentials.from_service_account_info(d, scopes=SCOPES)
    except Exception:
        pass

    if not creds:
        try:
            import streamlit as st
            d = dict(st.secrets["ga4_service_account"])
            if "private_key" in d:
                d["private_key"] = d["private_key"].replace("\\n", "\n")
            creds = service_account.Credentials.from_service_account_info(d, scopes=SCOPES)
        except Exception:
            pass

    if not creds and Path("google_creds.json").exists():
        creds = None  # MIGRATED: no credentials needed

    if not creds:
        return None
    return None  # MIGRATED: no sheets client needed


def scrape_all_tabs():
    """Scrape every tab from the Customer Success sheet."""
    gc = _get_sheet_client()
    if not gc:
        return {"error": "Could not authenticate Google Sheets"}

    try:
        sheet = None  # MIGRATED: use load_tab() from mongo_data_loader
    except Exception as e:
        return {"error": f"Cannot open sheet: {e}"}

    result = {"tabs": {}, "scraped_at": datetime.utcnow().isoformat()}

    for ws in sheet.worksheets():
        try:
            log(f"Reading tab: {ws.title}")
            # Use get_all_values to bypass duplicate-header errors
            all_values = ws.get_all_values()
            if not all_values:
                log(f"  -> EMPTY tab")
                result["tabs"][ws.title] = {"slug": _slugify(ws.title), "rows": 0, "data": [], "columns": []}
                continue

            # Detect header row: first non-empty row
            header_row_idx = 0
            for i, row in enumerate(all_values):
                non_empty = [c.strip() for c in row if c and c.strip()]
                if len(non_empty) >= 2:
                    header_row_idx = i
                    break

            raw_headers = all_values[header_row_idx]
            # Make headers unique
            headers = []
            seen = {}
            for j, h in enumerate(raw_headers):
                h = (h or "").strip()
                if not h:
                    h = f"col_{j+1}"
                if h in seen:
                    seen[h] += 1
                    h = f"{h}_{seen[h]}"
                else:
                    seen[h] = 0
                headers.append(h)

            # Build records from rows after header
            rows = []
            for r in all_values[header_row_idx + 1:]:
                row_dict = {}
                for k, val in zip(headers, r):
                    row_dict[k] = val
                # Skip completely empty rows
                if any(v and str(v).strip() for v in row_dict.values()):
                    rows.append(row_dict)

            slug = _slugify(ws.title)
            result["tabs"][ws.title] = {
                "slug":     slug,
                "rows":     len(rows),
                "data":     rows[:5000],
                "columns":  headers,
                "header_row": header_row_idx + 1,
            }
            log(f"  -> {len(rows)} rows, {len(headers)} columns")
        except Exception as e:
            log(f"  ERROR reading {ws.title}: {e}")
            result["tabs"][ws.title] = {"error": str(e)}

    # Save raw
    Path("data_output").mkdir(exist_ok=True)
    Path("data_output/customer_success_raw.json").write_text(json.dumps(result, indent=2, default=str))
    log(f"Saved raw to data_output/customer_success_raw.json")
    return result


def upsert_to_supabase(scraped):
    """Push each tab into customer_success_master table with tab name as category."""
    sb = _get_sb()
    if not sb:
        return {"error": "MongoDB not connected"}

    all_rows = []
    for tab_name, tab_info in scraped.get("tabs", {}).items():
        if tab_info.get("error"):
            continue
        slug = tab_info.get("slug", _slugify(tab_name))
        for r in tab_info.get("data", []):
            # Find email in ANY field
            email = ""
            for k, v in r.items():
                v_str = str(v) if v else ""
                if "@" in v_str and "." in v_str.split("@")[-1]:
                    # Validate looks like email
                    if " " not in v_str.strip() and len(v_str) < 100:
                        email = v_str.strip().lower()
                        break

            all_rows.append({
                "tab_name":   tab_name,
                "tab_slug":   slug,
                "email":      email,
                "row_data":   r,
                "scraped_at": scraped.get("scraped_at"),
            })

    if not all_rows:
        return {"error": "No rows"}

    # Upsert in chunks
    try:
        for i in range(0, len(all_rows), 100):
            sb.table("customer_success_master").upsert(all_rows[i:i+100]).execute()
        log(f"Upserted {len(all_rows)} rows to customer_success_master")
        return {"success": True, "count": len(all_rows)}
    except Exception as e:
        return {"error": str(e)}


def enrich_customers():
    """
    Match each customer from customer_success_master with:
    - signups table (by email)
    - uploads table (by email)
    - payments table (by email) + Stripe API for live data
    """
    sb = _get_sb()
    if not sb:
        return {"error": "MongoDB not connected"}

    # Get all unique emails from customer success
    try:
        cs_rows = sb.table("customer_success_master").select("email").execute().data
    except Exception as e:
        return {"error": f"Read CS error: {e}"}

    emails = list(set(r["email"] for r in cs_rows if r.get("email") and "@" in r["email"]))
    log(f"Enriching {len(emails)} unique emails")

    enriched = []
    for email in emails:
        e = email.strip().lower()
        row = {"email": e, "enriched_at": datetime.utcnow().isoformat()}

        # Signup
        try:
            r = sb.table("signups").select("signup_date,final_status,lead_source").eq("email_normalized", e).limit(1).execute()
            if r.data:
                row["signup_date"] = r.data[0].get("signup_date")
                row["signup_status"] = r.data[0].get("final_status")
                row["lead_source"] = r.data[0].get("lead_source")
        except Exception:
            pass

        # Upload
        try:
            r = sb.table("uploads").select("upload_date,final_status").eq("email_normalized", e).limit(1).execute()
            if r.data:
                row["first_upload_date"] = r.data[0].get("upload_date")
                row["upload_status"] = r.data[0].get("final_status")
        except Exception:
            pass

        # Payment
        try:
            r = sb.table("payments").select("first_payment_date,total_spend,payment_count,final_status").eq("email_normalized", e).limit(1).execute()
            if r.data:
                row["first_payment_date"] = r.data[0].get("first_payment_date")
                row["total_spend"]        = float(r.data[0].get("total_spend") or 0)
                row["payment_count"]      = int(r.data[0].get("payment_count") or 0)
                row["payment_status"]     = r.data[0].get("final_status")
        except Exception:
            pass

        # Compute funnel
        if row.get("signup_date") and row.get("first_upload_date"):
            try:
                s = datetime.fromisoformat(str(row["signup_date"])[:10])
                u = datetime.fromisoformat(str(row["first_upload_date"])[:10])
                row["days_signup_to_upload"] = (u - s).days
            except Exception:
                pass

        if row.get("signup_date") and row.get("first_payment_date"):
            try:
                s = datetime.fromisoformat(str(row["signup_date"])[:10])
                p = datetime.fromisoformat(str(row["first_payment_date"])[:10])
                row["days_signup_to_paid"] = (p - s).days
            except Exception:
                pass

        enriched.append(row)

    # Save enriched data
    try:
        for i in range(0, len(enriched), 100):
            upsert_many("customer_success_enriched", enriched[i:i+100], "email")
        log(f"Enriched {len(enriched)} customers")
        return {"success": True, "count": len(enriched)}
    except Exception as e:
        return {"error": str(e), "count": len(enriched)}


def enrich_stripe_live():
    """Fetch live Stripe data for each customer email."""
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not stripe_key:
        try:
            import streamlit as st
            stripe_key = str(st.secrets.get("STRIPE_SECRET_KEY", "")).strip()
        except Exception:
            pass
    if not stripe_key:
        return {"error": "STRIPE_SECRET_KEY not set"}

    try:
        import stripe
        stripe.api_key = stripe_key
    except ImportError:
        return {"error": "stripe library missing"}

    sb = _get_sb()
    if not sb:
        return {"error": "MongoDB missing"}

    try:
        rows = sb.table("customer_success_enriched").select("email").execute().data
    except Exception as e:
        return {"error": str(e)}

    enriched = 0
    for r in rows:
        email = r.get("email", "")
        if not email or "@" not in email:
            continue
        try:
            customers = stripe.Customer.list(email=email, limit=1)
            if customers.data:
                c = customers.data[0]
                # Get subscriptions
                subs = stripe.Subscription.list(customer=c.id, status="all", limit=10)
                sub_status = None
                mrr = 0
                if subs.data:
                    active = [s for s in subs.data if s.status in ("active", "trialing")]
                    canceled = [s for s in subs.data if s.status == "canceled"]
                    if active:
                        sub_status = "active"
                        mrr = sum(item.price.unit_amount/100 for s in active for item in s.items.data if item.price.unit_amount)
                    elif canceled:
                        sub_status = "canceled"
                    else:
                        sub_status = subs.data[0].status

                sb.table("customer_success_enriched").update({
                    "stripe_customer_id": c.id,
                    "stripe_created":     datetime.fromtimestamp(c.created).isoformat(),
                    "stripe_balance":     c.balance / 100,
                    "stripe_currency":    c.currency,
                    "stripe_delinquent":  c.delinquent,
                    "subscription_status": sub_status,
                    "mrr":                 mrr,
                    "stripe_enriched_at":  datetime.utcnow().isoformat(),
                }).eq("email", email).execute()
                enriched += 1
        except Exception:
            continue

    return {"success": True, "enriched_stripe": enriched}


def run_full_pipeline():
    log("=" * 60)
    log("CUSTOMER SUCCESS PIPELINE")
    log("=" * 60)

    scraped = scrape_all_tabs()
    if scraped.get("error"):
        log(f"Scrape error: {scraped['error']}")
        return scraped

    result = upsert_to_supabase(scraped)
    log(f"Upsert: {result}")

    enr = enrich_customers()
    log(f"Enrichment: {enr}")

    stripe_enr = enrich_stripe_live()
    log(f"Stripe live: {stripe_enr}")

    log("=" * 60)
    log("PIPELINE COMPLETE")
    log("=" * 60)
    return {"scrape": scraped, "upsert": result, "enrich": enr, "stripe": stripe_enr}


if __name__ == "__main__":
    run_full_pipeline()
