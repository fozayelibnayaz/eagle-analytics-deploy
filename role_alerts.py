#!/usr/bin/env python3
"""Role-labeled alerts - all sent to same Telegram group."""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from collections import Counter, defaultdict


import os
import re
import json
from datetime import datetime, timedelta, date

from mongo_client import (
    get_db, find_all, find_one, count_docs, count_accepted,
    upsert_many, upsert_one, insert_many, delete_many,
    get_analytics_cache, set_analytics_cache, get_mongo_status
)
from mongo_data_loader import (
    load_daily_kpis, load_signups, load_uploads, load_payments,
    load_tab, read_tab_data, get_kpi_counts, get_earliest_upload_date,
    sync_daily_kpis, sync_signups, sync_uploads, sync_payments,
    load_linkedin_posts, load_linkedin_followers_daily,
    load_linkedin_posts_daily, load_linkedin_highlights,
    get_connection_status, load_all_ml_training_tabs
)





def _get_sb():
    return get_db()


def _esc(s):
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")


def _send_telegram(message, parse_mode="HTML"):
    try:
        from reporting_engine import send_telegram
        return send_telegram(message, parse_mode=parse_mode)
    except Exception as e:
        print("Telegram error:", e)
        return False


def daily_standup():
    try:
        from ai_assistant_engine import get_full_context, _call_groq
        ctx = get_full_context("all")
        prompt = "Based on this real data, give TOP 3 priorities for TODAY.\n\nDATA:\n" + json.dumps(ctx, indent=2, default=str)[:5000] + "\n\nFormat:\n1st priority: action\nWHY: reason\nWHO: role\n\n2nd, 3rd same. Use real numbers."
        ans, _ = _call_groq([{"role":"user","content":prompt}], max_tokens=800, temperature=0.2)
        if ans:
            return "<b>DAILY STANDUP - " + date.today().isoformat() + "</b>\n----------------------------------------\n<i>Top 3 priorities for team</i>\n\n" + ans
    except Exception as e:
        return "Standup error: " + str(e)
    return ""


def marketer_weekly():
    sb = _get_sb()
    if sb is None:
        return ""
    end = date.today()
    start = end - timedelta(days=7)
    prev_start = start - timedelta(days=7)

    def fetch(s, e):
        rows = []
        offset = 0
        while True:
            r = sb.table("signups").select("lead_source,signup_date").eq("final_status","ACCEPTED").gte("signup_date",s.isoformat()).lte("signup_date",e.isoformat()).range(offset,offset+999).execute()
            batch = r.data or []
            rows.extend(batch)
            if len(batch) < 1000:
                break
            offset += 1000
        return rows

    curr = fetch(start, end)
    prev = fetch(prev_start, start - timedelta(days=1))
    curr_by = Counter(r.get("lead_source","") or "(unspecified)" for r in curr)
    prev_by = Counter(r.get("lead_source","") or "(unspecified)" for r in prev)

    total_c = sum(curr_by.values())
    total_p = sum(prev_by.values())
    delta = total_c - total_p
    pct = (delta/total_p*100) if total_p else 0

    msg = "<b>MARKETER WEEKLY - " + end.isoformat() + "</b>\n"
    msg += "----------------------------------------\n"
    msg += "<i>For team: marketing performance</i>\n\n"
    msg += "<b>Last 7d: " + str(total_c) + " signups</b> (prev 7d: " + str(total_p) + ", " + ("+" if delta>=0 else "") + str(delta) + " / " + ("+" if pct>=0 else "") + str(round(pct)) + "%)\n\n"
    msg += "<b>By Source</b>\n"
    for src, count in curr_by.most_common(15):
        prev_count = prev_by.get(src, 0)
        d = count - prev_count
        emoji = "[+]" if d > 0 else "[-]" if d < 0 else "[=]"
        msg += emoji + " <code>" + _esc(src)[:30] + "</code>: <b>" + str(count) + "</b> (was " + str(prev_count) + ", " + ("+" if d>=0 else "") + str(d) + ")\n"
    if curr_by:
        top = curr_by.most_common(1)[0]
        msg += "\n<b>Top:</b> " + _esc(top[0]) + " (" + str(top[1]) + " signups)"
    return msg


def cs_lead_weekly():
    try:
        from customer_success_analytics import sheet1_analysis, subscription_lifecycle, recent_activity_analysis, churn_by_month
        s1 = sheet1_analysis()
        sub = subscription_lifecycle()
        recent = recent_activity_analysis()
        churn = churn_by_month()
    except Exception as e:
        return "CS error: " + str(e)

    end = date.today()
    msg = "<b>CS LEAD WEEKLY - " + end.isoformat() + "</b>\n"
    msg += "----------------------------------------\n"
    msg += "<i>For team: customer success risks</i>\n\n"
    msg += "<b>Summary</b>\n"
    msg += "- Churned: <code>" + str(churn['total_churned']) + "</code>\n"
    msg += "- Lost: <code>$" + "{:,.2f}".format(churn['monthly_revenue_lost']) + "/mo</code>\n"
    msg += "- Ending 30d: <code>" + str(sub['count_ending']) + "</code>\n"
    msg += "- Declining: <code>" + str(recent['count_declining']) + "</code>\n"
    msg += "- Dormant paying: <code>" + str(len(s1['dormant_paying'])) + "</code>\n\n"

    if sub.get("ending_in_30d"):
        msg += "<b>Top 10 ending soon</b>\n"
        for c in sub["ending_in_30d"][:10]:
            msg += "- <code>" + _esc(c['email'][:35]) + "</code> (" + str(c['days_left']) + "d)\n"
        msg += "\n"
    if recent.get("declining"):
        msg += "<b>Top 10 declining</b>\n"
        for c in recent["declining"][:10]:
            pct = c.get("growth_pct")
            pct_str = ("+" if pct >= 0 else "") + str(round(pct)) + "%" if pct is not None else "n/a"
            msg += "- <code>" + _esc(c['email'][:35]) + "</code>: " + pct_str + "\n"
    return msg


def founder_monthly():
    sb = _get_sb()
    if sb is None:
        return ""
    today = date.today()
    last_month_end = today.replace(day=1) - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    prev_month_end = last_month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)

    def cnt(table, col, s, e):
        return sb.table(table).select("count",count="exact").eq("final_status","ACCEPTED").gte(col,s.isoformat()).lte(col,e.isoformat()).execute().count or 0

    def rev(s, e):
        r = sb.table("payments").select("total_spend,first_payment_date").eq("final_status","ACCEPTED").gte("first_payment_date",s.isoformat()).lte("first_payment_date",e.isoformat()).execute().data or []
        return round(sum(float(x.get("total_spend") or 0) for x in r), 2)

    curr = {
        "signups": cnt("signups","signup_date",last_month_start,last_month_end),
        "uploads": cnt("uploads","upload_date",last_month_start,last_month_end),
        "paid":    cnt("payments","first_payment_date",last_month_start,last_month_end),
        "revenue": rev(last_month_start,last_month_end),
    }
    prev = {
        "signups": cnt("signups","signup_date",prev_month_start,prev_month_end),
        "uploads": cnt("uploads","upload_date",prev_month_start,prev_month_end),
        "paid":    cnt("payments","first_payment_date",prev_month_start,prev_month_end),
        "revenue": rev(prev_month_start,prev_month_end),
    }

    def d(c, p):
        diff = round(c - p, 2)
        pct = (diff/p*100) if p else 0
        emoji = "[++]" if pct > 50 else "[+]" if pct > 10 else "[up]" if pct > 0 else "[-]" if pct < -10 else "[=]"
        diff_str = ("+" if diff >= 0 else "") + ("{:,.2f}".format(diff) if isinstance(c, float) else str(int(diff)))
        return emoji + " " + diff_str + " (" + ("+" if pct >= 0 else "") + str(round(pct)) + "%)"

    msg = "<b>FOUNDER MONTHLY - " + last_month_end.strftime('%B %Y') + "</b>\n"
    msg += "----------------------------------------\n"
    msg += "<i>For team: MoM growth</i>\n\n"
    msg += "Signups: <b>" + str(curr['signups']) + "</b> " + d(curr['signups'],prev['signups']) + "\n"
    msg += "Uploads: <b>" + str(curr['uploads']) + "</b> " + d(curr['uploads'],prev['uploads']) + "\n"
    msg += "Paid:    <b>" + str(curr['paid']) + "</b> " + d(curr['paid'],prev['paid']) + "\n"
    msg += "Revenue: <b>$" + "{:,.2f}".format(curr['revenue']) + "</b> (prev $" + "{:,.2f}".format(prev['revenue']) + ", " + d(curr['revenue'], prev['revenue']) + ")\n\n"

    if curr["signups"] > 0:
        s2u = curr["uploads"]/curr["signups"]*100
        s2p = curr["paid"]/curr["signups"]*100
        msg += "<b>Conversion</b>\n"
        msg += "- Sign-to-Upload: <code>" + str(round(s2u,1)) + "%</code>\n"
        msg += "- Sign-to-Paid: <code>" + str(round(s2p,1)) + "%</code>"
    return msg


if __name__ == "__main__":
    import time
    for name, fn in [("Daily Standup", daily_standup),
                     ("Marketer Weekly", marketer_weekly),
                     ("CS Lead Weekly", cs_lead_weekly),
                     ("Founder Monthly", founder_monthly)]:
        msg = fn()
        if msg:
            ok = _send_telegram(msg)
            print(name, "SENT" if ok else "FAILED")
        time.sleep(3)
