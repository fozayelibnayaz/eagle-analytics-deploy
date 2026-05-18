"""
reporting_engine.py
LAYER 6 - REPORTING / NOTIFICATIONS
- Email summary (Gmail SMTP)
- Slack webhook
- Console summary
"""
import os
import json
import urllib.request
from datetime import datetime
from pathlib import Path

DATA_DIR = Path("data_output")


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [Report] {msg}", flush=True)


def get_summary_text() -> str:
    """Build summary text from latest pipeline data."""
    from sheets_writer import read_tab_data
    from ml_intelligence import predict_monthly_metrics
    
    lines = []
    lines.append(f"Eagle3D KPI Pipeline Report")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 50)
    lines.append("")
    
    # Counts
    lines.append("DATA COUNTS:")
    for tab in ["Raw_FREE","Raw_FIRST_UPLOAD","Raw_STRIPE",
                "Verified_FREE","Verified_FIRST_UPLOAD","Verified_STRIPE"]:
        try:
            rows = read_tab_data(tab)
            lines.append(f"  {tab:30s}: {len(rows):>5} rows")
        except Exception:
            lines.append(f"  {tab:30s}: ERROR")
    
    # Today's new entries
    today = datetime.now().strftime("%Y-%m-%d")
    lines.append("")
    lines.append(f"NEW TODAY ({today}):")
    for tab in ["Verified_FREE","Verified_FIRST_UPLOAD","Verified_STRIPE"]:
        try:
            rows = read_tab_data(tab)
            today_rows = [
                r for r in rows
                if str(r.get("__first_processed_at__","")).startswith(today)
                or str(r.get("__processed_at__","")).startswith(today)
            ]
            lines.append(f"  {tab:30s}: {len(today_rows)} new")
        except Exception:
            pass
    
    # Top recent entries
    lines.append("")
    lines.append("TOP NEW SIGNUPS (recent):")
    try:
        rows = read_tab_data("Verified_FREE")
        # Sort by ML score
        scored_rows = [r for r in rows if "__ml_combined_score__" in r]
        scored_rows.sort(key=lambda r: float(r.get("__ml_combined_score__", 0)), reverse=True)
        for r in scored_rows[:5]:
            email = r.get("Email","")
            score = r.get("__ml_combined_score__","")
            source = r.get("Lead Source","")
            lines.append(f"  {score} | {email:35s} | {source}")
    except Exception as e:
        lines.append(f"  (error: {e})")
    
    # Goals & Predictions for current month
    try:
        goals = {}
        if os.path.exists('monthly_goals.json'):
            with open('monthly_goals.json','r') as f:
                goals = json.load(f)
        # current month string
        now_month = datetime.now().strftime('%Y-%m')
        pred = predict_monthly_metrics(now_month)
        if pred:
            lines.append("")
            lines.append(f"GOALS & PREDICTIONS ({now_month}):")
            g = goals.get(now_month, {})
            for metric in ('SignUps','FirstUploads','Paid'):
                cur = pred.get(metric, {}).get('current', 0)
                best = pred.get(metric, {}).get('best', 0)
                likely = pred.get(metric, {}).get('likely', 0)
                worst = pred.get(metric, {}).get('worst', 0)
                goal = g.get(metric, '') if g else ''
                lines.append(f"  {metric:12s} | current={cur:>3} | likely={likely:>3} | best={best:>3} | worst={worst:>3} | goal={goal}")
    except Exception as e:
        lines.append(f"(Prediction error: {e})")

    return "\n".join(lines)


def send_email_report(text: str):
    """Send email via SMTP. Requires NOTIFY_EMAIL_FROM/PASSWORD/TO env vars."""
    sender   = os.environ.get("NOTIFY_EMAIL_FROM","")
    password = os.environ.get("NOTIFY_EMAIL_APP_PASSWORD","")
    receiver = os.environ.get("NOTIFY_EMAIL_TO","")
    
    if not sender or not password or not receiver:
        log("Email notification skipped (env vars not set)")
        return False
    
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        msg = MIMEMultipart()
        msg["From"]    = sender
        msg["To"]      = receiver
        msg["Subject"] = f"Eagle3D KPI Report - {datetime.now().strftime('%Y-%m-%d')}"
        msg.attach(MIMEText(text, "plain"))
        
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.send_message(msg)
        
        log(f"Email sent to {receiver}")
        return True
    except Exception as e:
        log(f"Email send failed: {e}")
        return False


def send_slack_report(text: str):
    """Send to Slack webhook."""
    webhook = os.environ.get("SLACK_WEBHOOK_URL","")
    if not webhook:
        log("Slack notification skipped (SLACK_WEBHOOK_URL not set)")
        return False
    
    try:
        payload = json.dumps({"text": f"```\n{text}\n```"}).encode()
        req = urllib.request.Request(
            webhook, data=payload,
            headers={"Content-Type":"application/json"},
            method="POST"
        )
        urllib.request.urlopen(req)
        log("Slack message sent")
        return True
    except Exception as e:
        log(f"Slack send failed: {e}")
        return False


def main():
    log("=" * 60)
    log("REPORTING ENGINE")
    log("=" * 60)
    
    text = get_summary_text()
    print()
    print(text)
    print()
    
    # Save to file
    report_file = DATA_DIR / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    report_file.write_text(text)
    log(f"Saved: {report_file}")
    
    # Send notifications
    send_email_report(text)
    send_slack_report(text)


if __name__ == "__main__":
    main()
