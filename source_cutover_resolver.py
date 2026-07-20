from __future__ import annotations

from typing import Dict, List, Optional, Tuple
from mongo_client import find_all

TEST_SOURCES = {
    "test-postman",
    "cloud-test",
    "manual-test",
    "debug",
}

TEST_EMAIL_MARKERS = (
    "@example.com",
    "webhook-test",
    "cloud-test",
    "newuser@example.com",
)

def _norm(v):
    import re
    s = str(v or "").strip()
    m = re.search(r'([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})', s)
    return m.group(1).lower() if m else s.lower()

def _date(v):
    return str(v or "").strip()[:10]

def _is_test_email(email: str) -> bool:
    e = _norm(email)
    return any(x in e for x in TEST_EMAIL_MARKERS)

def _is_real_webhook_doc(doc: dict) -> bool:
    source = _norm(doc.get("source"))
    email = _norm(doc.get("email") or doc.get("email_normalized"))

    if not source or source in TEST_SOURCES:
        return False
    if _is_test_email(email):
        return False

    # explicit webhook-ish sources accepted
    # aninda-backend, prod-backend, app-backend etc. allowed
    return True

def get_cutover_date() -> Optional[str]:
    candidates: List[str] = []

    for col, date_field in [
        ("signups", "signup_date"),
        ("uploads", "upload_date"),
        ("payments", "first_payment_date"),
    ]:
        docs = find_all(col, {})
        for d in docs:
            if str(d.get("final_status", "")).upper() != "ACCEPTED":
                continue
            if not _is_real_webhook_doc(d):
                continue
            dt = _date(d.get(date_field))
            if dt:
                candidates.append(dt)

    return min(candidates) if candidates else None

def split_mode_for_date(day: str) -> str:
    cutover = get_cutover_date()
    if not cutover:
        return "legacy"
    return "legacy" if day < cutover else "webhook"

def is_countable_signup(doc: dict, day: str) -> bool:
    if str(doc.get("final_status", "")).upper() != "ACCEPTED":
        return False
    mode = split_mode_for_date(day)
    source = _norm(doc.get("source"))
    if mode == "legacy":
        return source != "webhook"
    return _is_real_webhook_doc(doc)

def is_countable_upload(doc: dict, day: str) -> bool:
    if str(doc.get("final_status", "")).upper() != "ACCEPTED":
        return False
    mode = split_mode_for_date(day)
    source = _norm(doc.get("source"))
    if mode == "legacy":
        return source != "webhook"
    return _is_real_webhook_doc(doc)

def is_countable_payment(doc: dict, day: str) -> bool:
    if str(doc.get("final_status", "")).upper() != "ACCEPTED":
        return False
    mode = split_mode_for_date(day)
    source = _norm(doc.get("source"))
    if mode == "legacy":
        return source != "webhook"
    return _is_real_webhook_doc(doc)
