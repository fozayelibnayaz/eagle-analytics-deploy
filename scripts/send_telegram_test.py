import json, os, urllib.request

token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
if not token or not chat_id:
    raise SystemExit("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")

payload = json.dumps({
    "chat_id": chat_id,
    "text": "✅ GitHub manual workflow heartbeat reached Telegram.",
    "parse_mode": "Markdown",
}).encode("utf-8")

req = urllib.request.Request(
    f"https://api.telegram.org/bot{token}/sendMessage",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)

with urllib.request.urlopen(req, timeout=15) as resp:
    body = json.loads(resp.read().decode())
    print(body)
    if not body.get("ok"):
        raise SystemExit("Telegram send failed")
