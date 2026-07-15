# Webhook Integration Guide

For: Aninda Sadman (Backend Developer)
Direction: Your backend POSTs data to Fozayel's API.
Purpose: Sync signups/uploads/payments to the analytics dashboard in real time.

--------------------------------------------------

TL;DR

POST to:
https://unsoiling-tendenciously-marge.ngrok-free.dev/webhook

Header:
X-API-Key: e3d_U4K1XjV1mn5TnH5X0hlIRtzQAxGgeACbLN-V0OKb0Vg

Body:
{
  "source": "your-backend-name",
  "data": [
    { "type": "signup",  "info": { ... } },
    { "type": "upload",  "info": { ... } },
    { "type": "payment", "info": { ... } }
  ]
}

--------------------------------------------------

Example curl

curl -X POST "https://unsoiling-tendenciously-marge.ngrok-free.dev/webhook" \
  -H "X-API-Key: e3d_U4K1XjV1mn5TnH5X0hlIRtzQAxGgeACbLN-V0OKb0Vg" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "aninda-backend",
    "data": [
      {"type": "signup", "info": {"id": "sig-abc123", "email": "newuser@example.com", "signup_date": "2026-07-14", "lead_source": "google"}},
      {"type": "upload", "info": {"id": "up-xyz789", "email": "newuser@example.com", "upload_date": "2026-07-14", "app_name": "MyApp"}},
      {"type": "payment", "info": {"id": "pay-def456", "email": "newuser@example.com", "first_payment_date": "2026-07-14", "amount": 29.00}}
    ]
  }'

--------------------------------------------------

Helper endpoints

Test:
https://unsoiling-tendenciously-marge.ngrok-free.dev/webhook/test

Log:
https://unsoiling-tendenciously-marge.ngrok-free.dev/webhook/log?limit=50

Docs:
https://unsoiling-tendenciously-marge.ngrok-free.dev/docs

--------------------------------------------------

Message to send Aninda

Bhai, webhook ready to receive data.

POST endpoint:
https://unsoiling-tendenciously-marge.ngrok-free.dev/webhook

Interactive docs:
https://unsoiling-tendenciously-marge.ngrok-free.dev/docs

Send POST from your backend whenever signup/upload/payment happens.

Body:
{"data": [{"type": "signup", "info": {...}}, ...]}

Full guide + curl + Postman setup in attached WEBHOOK_GUIDE.md.

Quick test:
GET /webhook/test

Data lands in Mongo instantly. Telegram alert fires per call.
Dedup by email — safe to re-send same item.

Ping after you POST once — I can confirm data landed on my side.
