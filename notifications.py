"""
notifications.py
Sends alerts via Telegram bot + email.
Reads credentials from environment variables only.
Silent if credentials not set.
"""
import os
import json
import smtplib
import urllib.request
import urllib.parse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [Notify] {msg}", flush=True)


def send_telegram(message, parse_mode="Markdown"):
    """Send message to Telegram. Silent if not configured."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    
    if not bot_token or not chat_id:
        log("Telegram skipped (no credentials)")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": message[:4000],
            "parse_mode": parse_mode,
            "disable_web_page_preview": "true",
        }).encode()
        
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.status == 200:
                log("Telegram sent")
                return True
            log(f"Telegram failed: HTTP {r.status}")
            return False
    except Exception as e:
        log(f"Telegram error: {e}")
        return False


def send_email(subject, body, html_body=None):
    """Send email via Gmail SMTP. Silent if not configured."""
    sender = os.environ.get("EMAIL_FROM", "").strip()
    password = os.environ.get("EMAIL_APP_PASSWORD", "").strip()
    receiver = os.environ.get("EMAIL_TO", "").strip()
    
    if not sender or not password or not receiver:
        log("Email skipped (no credentials)")
        return False
    
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = receiver
        
        msg.attach(MIMEText(body, "plain"))
        if html_body:
            msg.attach(MIMEText(html_body, "html"))
        
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(sender, password)
            server.send_message(msg)
        
        log(f"Email sent to {receiver}")
        return True
    except Exception as e:
        log(f"Email error: {e}")
        return False


def alert_stripe_cookies_expired():
    """Send alert when Stripe cookies stop working."""
    from pipeline_health import should_send_alert, mark_alert_sent
    
    alert_key = "stripe_cookies_expired"
    if not should_send_alert(alert_key, cooldown_hours=24):
        log(f"Alert {alert_key} on cooldown - skipping")
        return
    
    title = "ALERT: Eagle3D KPI - Stripe Cookies Expired"
    
    telegram_msg = """*ALERT: Stripe cookies expired*

The KPI pipeline cannot fetch Stripe paid customer data because the session cookies have expired.

*To fix (takes ~60 seconds):*

1. Open Chrome -> https://dashboard.stripe.com/customers
2. Log in if needed
3. Click Cookie-Editor extension icon
4. Click Export -> Export as JSON
5. Open dashboard: https://eagle3d-kpi-automation.streamlit.app/
6. Click "Update Stripe Cookies" in sidebar
7. Paste the JSON, click Save

Or update GitHub Secret directly:
- https://github.com/fozayelibnayaz/eagle3d-kpi-automation/settings/secrets/actions
- Edit STRIPE_COOKIES_JSON

The pipeline will resume on next scheduled run (04:00 UTC daily)."""
    
    email_body = f"""Eagle3D KPI Pipeline Alert

{title}

The KPI pipeline cannot fetch Stripe paid customer data because the session cookies have expired.

This is a routine maintenance task that needs to be done every 2-4 weeks.

To fix (takes about 60 seconds):

Step 1: Get fresh cookies
- Open Chrome
- Go to: https://dashboard.stripe.com/customers
- Log in if needed (you should already be logged in)
- Click the Cookie-Editor browser extension icon
- Click "Export" then "Export as JSON"
- The JSON is now in your clipboard

Step 2: Update the pipeline
Option A (easier): Use the dashboard
- Open: https://eagle3d-kpi-automation.streamlit.app/
- In the sidebar, click "Update Stripe Cookies"
- Paste the JSON
- Click Save

Option B: Update GitHub Secret
- Go to: https://github.com/fozayelibnayaz/eagle3d-kpi-automation/settings/secrets/actions
- Find STRIPE_COOKIES_JSON
- Click Update
- Paste the new JSON
- Click "Update secret"

Once updated, the pipeline will resume on the next scheduled run (04:00 UTC daily).

Until you update, sign-up and first-upload data will continue to flow normally - only Stripe paid customer data is affected.

---
This is an automated message from your Eagle3D KPI monitoring system.
Time: {datetime.now().isoformat()}
"""
    
    sent_telegram = send_telegram(telegram_msg)
    sent_email = send_email(title, email_body)
    
    if sent_telegram or sent_email:
        mark_alert_sent(alert_key)


def alert_pipeline_failure(stage, error_msg, consecutive_failures=1):
    """Send alert when a pipeline stage fails."""
    from pipeline_health import should_send_alert, mark_alert_sent
    
    alert_key = f"pipeline_failure_{stage}"
    
    # Higher cooldown for repeated failures - don't spam
    cooldown = 6 if consecutive_failures < 3 else 24
    
    if not should_send_alert(alert_key, cooldown_hours=cooldown):
        return
    
    title = f"Pipeline Failure: {stage} ({consecutive_failures}x)"
    
    telegram_msg = f"""*Eagle3D KPI Pipeline Failure*

*Stage:* {stage}
*Consecutive failures:* {consecutive_failures}
*Last error:* `{str(error_msg)[:200]}`

Check GitHub Actions:
https://github.com/fozayelibnayaz/eagle3d-kpi-automation/actions"""
    
    email_body = f"""Eagle3D KPI Pipeline Failure

Stage: {stage}
Consecutive failures: {consecutive_failures}
Time: {datetime.now().isoformat()}

Error message:
{error_msg}

Check GitHub Actions for full logs:
https://github.com/fozayelibnayaz/eagle3d-kpi-automation/actions

If this stage continues to fail:
1. Check GitHub Actions logs for the specific error
2. Verify GitHub Secrets are set correctly
3. For Stripe failures: cookies likely expired
4. For KPI failures: check KPI_EMAIL and KPI_PASSWORD secrets
"""
    
    sent_t = send_telegram(telegram_msg)
    sent_e = send_email(title, email_body)
    
    if sent_t or sent_e:
        mark_alert_sent(alert_key)


def daily_summary(stats):
    """Send daily summary report."""
    from pipeline_health import should_send_alert, mark_alert_sent
    
    alert_key = f"daily_summary_{datetime.now().strftime('%Y-%m-%d')}"
    if not should_send_alert(alert_key, cooldown_hours=20):
        return
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    telegram_msg = f"""*Eagle3D KPI Daily Report - {today}*

*Sign-ups today:* {stats.get('signups_today', 0)}
*First uploads today:* {stats.get('uploads_today', 0)}
*Paid customers today:* {stats.get('paid_today', 0)}

*This month total:*
- Sign-ups: {stats.get('signups_month', 0)}
- Uploads: {stats.get('uploads_month', 0)}
- Paid: {stats.get('paid_month', 0)}

[Open Dashboard](https://eagle3d-kpi-automation.streamlit.app/)"""
    
    email_body = f"""Eagle3D KPI Daily Report - {today}

TODAY'S NEW DATA:
- New sign-ups: {stats.get('signups_today', 0)}
- New first uploads: {stats.get('uploads_today', 0)}
- New paid customers: {stats.get('paid_today', 0)}

THIS MONTH ({datetime.now().strftime('%B %Y')}):
- Total sign-ups: {stats.get('signups_month', 0)}
- Total first uploads: {stats.get('uploads_month', 0)}
- Total paid customers: {stats.get('paid_month', 0)}

ALL TIME:
- Total sign-ups: {stats.get('signups_alltime', 0)}
- Total first uploads: {stats.get('uploads_alltime', 0)}
- Total paid customers: {stats.get('paid_alltime', 0)}

View dashboard: https://eagle3d-kpi-automation.streamlit.app/

---
Auto-generated daily at 04:00 UTC.
"""
    
    send_telegram(telegram_msg)
    send_email(f"Eagle3D KPI Daily Report - {today}", email_body)
    mark_alert_sent(alert_key)


if __name__ == "__main__":
    log("Test mode: sending test message to all configured channels")
    
    test_msg = "Test message from Eagle3D KPI pipeline. If you see this, notifications are working."
    
    sent_t = send_telegram(f"*Test Notification*\n\n{test_msg}")
    sent_e = send_email("Test - Eagle3D KPI Notifications", test_msg)
    
    log(f"Telegram: {'OK' if sent_t else 'NOT CONFIGURED'}")
    log(f"Email:    {'OK' if sent_e else 'NOT CONFIGURED'}")
