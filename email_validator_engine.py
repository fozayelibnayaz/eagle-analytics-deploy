"""
email_validator_engine.py — Eagle 3D Streaming Analytics Hub
==============================================================
Email validation pipeline:
  1. Syntax check (RFC-5322 via email-validator library)
  2. MX record check (optional, controlled by CHECK_MX_RECORDS)
  3. Disposable domain check (downloaded list + custom list)
  4. Suspicious local-part patterns (test123, asdf, qwerty…)
  5. Internal (Eagle 3D Streaming) filter

Uses MongoDB caches: domain_cache, smtp_cache
"""

from __future__ import annotations

import re
import os
from typing import Any, Dict, List, Set, Tuple

try:
    from email_validator import validate_email, EmailNotValidError
    _HAS_EMAIL_VALIDATOR = True
except ImportError:
    _HAS_EMAIL_VALIDATOR = False

try:
    import dns.resolver
    _HAS_DNS = True
except ImportError:
    _HAS_DNS = False

import requests

from config import (
    CHECK_MX_RECORDS,
    CUSTOM_DISPOSABLE_DOMAINS,
    DISPOSABLE_DOMAINS_URL,
    INTERNAL_EMAIL_DOMAINS,
    INTERNAL_EMAIL_KEYWORDS,
    MX_TIMEOUT_SECONDS,
    SUSPICIOUS_LOCAL_PATTERNS,
)
from mongo_client import find_one, upsert_one


# ─────────────────────────────────────────────────────────────────
# DISPOSABLE DOMAIN LIST (cached)
# ─────────────────────────────────────────────────────────────────
_DISPOSABLE_CACHE: Set[str] = set()


def _load_disposable_domains() -> Set[str]:
    global _DISPOSABLE_CACHE
    if _DISPOSABLE_CACHE:
        return _DISPOSABLE_CACHE

    domains: Set[str] = set(d.lower().strip() for d in CUSTOM_DISPOSABLE_DOMAINS)

    try:
        r = requests.get(DISPOSABLE_DOMAINS_URL, timeout=10)
        if r.status_code == 200:
            for line in r.text.splitlines():
                d = line.strip().lower()
                if d and not d.startswith("#"):
                    domains.add(d)
    except Exception as e:
        print(f"[email_validator] Could not fetch disposable list: {e}")

    _DISPOSABLE_CACHE = domains
    return domains


# ─────────────────────────────────────────────────────────────────
# CACHES (MongoDB-backed)
# ─────────────────────────────────────────────────────────────────
def _domain_cache_get(domain: str) -> Dict[str, Any] | None:
    return find_one("domain_cache", {"domain": domain})


def _domain_cache_set(domain: str, result: Dict[str, Any]) -> None:
    doc = {"domain": domain, **result}
    upsert_one("domain_cache", doc, ["domain"])


# ─────────────────────────────────────────────────────────────────
# CHECKS
# ─────────────────────────────────────────────────────────────────
def _syntax_ok(email: str) -> Tuple[bool, str]:
    if not email or "@" not in email:
        return False, "no @"
    if _HAS_EMAIL_VALIDATOR:
        try:
            validate_email(email, check_deliverability=False)
            return True, ""
        except EmailNotValidError as e:
            return False, str(e)
    # Simple fallback
    if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return True, ""
    return False, "regex fail"


def _mx_ok(domain: str) -> bool:
    if not CHECK_MX_RECORDS or not _HAS_DNS:
        return True

    cached = _domain_cache_get(domain)
    if cached and "mx_ok" in cached:
        return bool(cached["mx_ok"])

    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = MX_TIMEOUT_SECONDS
        answers = resolver.resolve(domain, "MX")
        ok = len(list(answers)) > 0
    except Exception:
        ok = False

    _domain_cache_set(domain, {"mx_ok": ok})
    return ok


def _is_disposable(domain: str) -> bool:
    return domain.lower() in _load_disposable_domains()


def _is_suspicious_local(local: str) -> bool:
    for pat in SUSPICIOUS_LOCAL_PATTERNS:
        try:
            if re.match(pat, local, re.IGNORECASE):
                return True
        except re.error:
            continue
    return False


def _is_internal(email: str, domain: str) -> bool:
    if domain.lower() in [d.lower() for d in INTERNAL_EMAIL_DOMAINS]:
        return True
    email_lower = email.lower()
    for kw in INTERNAL_EMAIL_KEYWORDS:
        if kw.lower() in email_lower:
            # 'eagle' keyword only counts as internal if it's in the domain OR the local part starts with it
            local = email_lower.split("@")[0]
            if kw.lower() in domain.lower() or local.startswith(kw.lower()):
                return True
    return False


# ─────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────
def validate(email: str) -> Dict[str, Any]:
    """
    Returns:
      {
        "email":           str,
        "email_normalized":str,
        "valid":           bool,
        "reason":          str,       # rejection reason if not valid
        "checks": {
          "syntax":       bool,
          "mx":           bool,
          "disposable":   bool,
          "suspicious":   bool,
          "internal":     bool,
        }
      }
    """
    email = str(email or "").strip()
    if not email:
        return _rejected(email, "empty")

    email_norm = email.lower()

    ok, err = _syntax_ok(email_norm)
    if not ok:
        return _rejected(email_norm, f"syntax: {err}", syntax=False)

    local, domain = email_norm.split("@", 1)

    if _is_internal(email_norm, domain):
        return _rejected(email_norm, "internal email", internal=True, syntax=True)

    if _is_disposable(domain):
        return _rejected(email_norm, "disposable domain",
                         syntax=True, disposable=True)

    if _is_suspicious_local(local):
        return _rejected(email_norm, "suspicious local part",
                         syntax=True, suspicious=True)

    if not _mx_ok(domain):
        return _rejected(email_norm, "no MX record",
                         syntax=True, mx=False)

    return {
        "email":            email,
        "email_normalized": email_norm,
        "valid":            True,
        "reason":           "",
        "checks": {
            "syntax":     True,
            "mx":         True,
            "disposable": False,
            "suspicious": False,
            "internal":   False,
        },
    }


def _rejected(email: str, reason: str, syntax=True, mx=True,
              disposable=False, suspicious=False, internal=False) -> Dict[str, Any]:
    return {
        "email":            email,
        "email_normalized": email.lower(),
        "valid":            False,
        "reason":           reason,
        "checks": {
            "syntax":     syntax,
            "mx":         mx,
            "disposable": disposable,
            "suspicious": suspicious,
            "internal":   internal,
        },
    }


def validate_many(emails: List[str]) -> List[Dict[str, Any]]:
    return [validate(e) for e in emails or []]


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        "ayaz@eagle3dstreaming.com",     # internal
        "user@gmail.com",                # good
        "test123@example.com",           # suspicious
        "user@mailinator.com",           # disposable
        "not-an-email",                  # syntax fail
        "user@nonexistentdomain12345.co",# MX fail
    ]
    for e in tests:
        r = validate(e)
        status = "✅ VALID" if r["valid"] else f"❌ {r['reason']}"
        print(f"  {e:45s} → {status}")
