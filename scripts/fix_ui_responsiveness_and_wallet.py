from pathlib import Path
from datetime import datetime

ROOT = Path.cwd()
BACKUPS = ROOT / "backups"
BACKUPS.mkdir(exist_ok=True)

def backup(path: Path):
    if path.exists():
        b = BACKUPS / f"{path.name}.ui_responsive_wallet_fix.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
        b.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        print(f"BACKUP: {path} -> {b}")

# ------------------------------------------------------------
# 1) Patch app.py: full email in wallet, activity feed filter by period
# ------------------------------------------------------------
app = ROOT / "app.py"
backup(app)
text = app.read_text(encoding="utf-8", errors="ignore")

# Full email in wallet card (remove hard slice)
text = text.replace(
    'holder=(user_email.upper()[:24] if user_email else "EAGLE 3D STREAMING"),',
    'holder=(user_email.upper() if user_email else "EAGLE 3D STREAMING"),'
)

# If a slightly different variant exists, also normalize it
text = text.replace(
    'holder=(user_email.upper() if user_email else "EAGLE 3D STREAMING"),',
    'holder=(user_email.upper() if user_email else "EAGLE 3D STREAMING"),'
)

# Activity feed should be filtered to selected period
text = text.replace(
    '''recent_sign = find_all("signups",
                                        filters={"final_status": "ACCEPTED"},
                                        sort=[("signup_date", -1)], limit=6)''',
    '''recent_sign = find_all("signups",
                                        filters={"final_status": "ACCEPTED",
                                                 "signup_date": {"$gte": period.start_iso()[:10], "$lte": period.end_iso()[:10]}},
                                        sort=[("signup_date", -1)], limit=6)'''
)

text = text.replace(
    '''recent_up = find_all("uploads",
                                      filters={"final_status": "ACCEPTED"},
                                      sort=[("upload_date", -1)], limit=5)''',
    '''recent_up = find_all("uploads",
                                      filters={"final_status": "ACCEPTED",
                                               "upload_date": {"$gte": period.start_iso()[:10], "$lte": period.end_iso()[:10]}},
                                      sort=[("upload_date", -1)], limit=5)'''
)

text = text.replace(
    '''recent_pay = find_all("payments",
                                       filters={"final_status": "ACCEPTED"},
                                       sort=[("first_payment_date", -1)], limit=5)''',
    '''recent_pay = find_all("payments",
                                       filters={"final_status": "ACCEPTED",
                                                "first_payment_date": {"$gte": period.start_iso()[:10], "$lte": period.end_iso()[:10]}},
                                       sort=[("first_payment_date", -1)], limit=5)'''
)

# Label cleanup
text = text.replace("New New Paying Customers", "New Paying Customers")

app.write_text(text, encoding="utf-8")
print("✅ app.py patched")

# ------------------------------------------------------------
# 2) Patch static/monetra.css: nav responsiveness + metric label wrap + wallet holder
# ------------------------------------------------------------
css = ROOT / "static" / "monetra.css"
backup(css)
css_text = css.read_text(encoding="utf-8", errors="ignore") if css.exists() else ""

override = """

/* ===== UI responsiveness hotfix ===== */

/* Top nav should not wrap ugly */
.e3-nav-tabs {
  display: flex !important;
  flex-wrap: nowrap !important;
  overflow-x: auto !important;
  overflow-y: hidden !important;
  max-width: calc(100vw - 340px);
  scrollbar-width: none;
}
.e3-nav-tabs::-webkit-scrollbar {
  display: none;
}
.e3-nav-tab {
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  flex: 0 0 auto !important;
  min-width: 84px !important;
  white-space: nowrap !important;
  line-height: 1.1 !important;
  word-break: keep-all !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
}

/* Metric labels should not show broken truncation */
[data-testid="stMetricLabel"] {
  white-space: normal !important;
  overflow: visible !important;
  text-overflow: clip !important;
  line-height: 1.2 !important;
  font-size: 11px !important;
}

/* Wallet / holder text should show full email better */
.e3-wallet-card,
.e3-wallet-card-v2 {
  overflow: hidden !important;
}
.e3-wallet-card *,
.e3-wallet-card-v2 * {
  overflow-wrap: anywhere !important;
  word-break: break-word !important;
}

/* Slightly tighter nav on medium screens */
@media (max-width: 1400px) {
  .e3-nav-tabs {
    max-width: calc(100vw - 260px);
  }
  .e3-nav-tab {
    min-width: 72px !important;
    padding: 8px 14px !important;
    font-size: 12px !important;
  }
}

@media (max-width: 1100px) {
  .e3-nav-tabs {
    max-width: calc(100vw - 180px);
  }
  .e3-logo-name {
    font-size: 14px !important;
  }
}
"""

if "UI responsiveness hotfix" not in css_text:
    css_text += "\n" + override + "\n"
    css.write_text(css_text, encoding="utf-8")
    print("✅ static/monetra.css patched with responsiveness + wallet fixes")
else:
    print("ℹ️ responsiveness hotfix already present in static/monetra.css")

print("✅ UI responsiveness + wallet fix bundle complete")
