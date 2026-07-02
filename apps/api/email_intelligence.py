"""
email_intelligence.py
Complete multi-layer email verification system.

LAYERS:
  L1: Syntax + Internal/test patterns
  L2: Multi-source disposable list (35k+ domains, weekly auto-update)
  L3: Domain intelligence (MX, SPF, DMARC, A-record, age)  [cached 30d]
  L4: SMTP RCPT verification                                [cached 7d]
  L5: Heuristic scoring (entropy, patterns)
  L6: ML classifier (if model exists)
  L7: Combined verdict

Returns: dict with verdict, score, signals, reasons
"""
import json
import os
import re
import socket
import smtplib
import urllib.request
import math
from datetime import datetime, timedelta
from pathlib import Path
from functools import lru_cache

DATA_DIR = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)

DISPOSABLE_FILE       = DATA_DIR / "disposable_domains.txt"
DOMAIN_CACHE_FILE     = DATA_DIR / "domain_cache.json"
SMTP_CACHE_FILE       = DATA_DIR / "smtp_cache.json"
ML_MODEL_FILE         = DATA_DIR / "email_classifier.pkl"

# Multi-source disposable lists
DISPOSABLE_SOURCES = [
    "https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/master/disposable_email_blocklist.conf",
    "https://raw.githubusercontent.com/disposable/disposable-email-domains/master/domains.txt",
    "https://raw.githubusercontent.com/7c/fakefilter/main/txt/data.txt",
    "https://raw.githubusercontent.com/wesbos/burner-email-providers/master/emails.txt",
    "https://raw.githubusercontent.com/martenson/disposable-email-domains/master/disposable_email_blocklist.conf",
]

DOMAIN_CACHE_DAYS = 30
SMTP_CACHE_DAYS   = 7

MAJOR_PROVIDERS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.fr",
    "outlook.com", "hotmail.com", "live.com", "msn.com",
    "icloud.com", "me.com", "mac.com",
    "protonmail.com", "proton.me", "pm.me",
    "aol.com", "ymail.com", "rocketmail.com",
    "zoho.com", "yandex.com", "yandex.ru", "mail.ru",
    "gmx.com", "gmx.de", "web.de", "t-online.de",
    "fastmail.com", "tutanota.com", "hushmail.com",
}

INTERNAL_DOMAINS = {"eagle3dstreaming.com", "eagle3d.com"}
INTERNAL_KEYWORDS = ["eagle3d", "e3ds_", "_e3ds", "internal-test"]

SUSPICIOUS_PATTERNS = [
    r'^test\d*@', r'^demo\d*@', r'^fake\d*@', r'^sample\d*@',
    r'^noreply@', r'^no-reply@', r'^donotreply@',
    r'^a{3,}@', r'^x{3,}@', r'^q{3,}@', r'^z{3,}@',
    r'^bob\d+@', r'^alice\d+@', r'^maria\d+@', r'^john\d+@',
    r'^user\d+@', r'^abc\d+@', r'^123\d*@',
]


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [EmailIntel] {msg}", flush=True)


# ──────────────────────────────────────────────────────────────
# LAYER 1: Disposable list (multi-source, auto-refreshed weekly)
# ──────────────────────────────────────────────────────────────

def _needs_refresh(file_path, days):
    if not file_path.exists():
        return True
    age = (datetime.now().timestamp() - file_path.stat().st_mtime) / 86400
    return age > days


def fetch_disposable_lists(force=False):
    """Combine all sources into one file."""
    if not force and not _needs_refresh(DISPOSABLE_FILE, 7):
        return

    log("Refreshing disposable lists from all sources...")
    all_domains = set()

    for url in DISPOSABLE_SOURCES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                content = r.read().decode("utf-8", errors="ignore")
                count_before = len(all_domains)
                for line in content.splitlines():
                    line = line.strip().lower()
                    if line and not line.startswith("#"):
                        # Some lists have email@domain format
                        if "@" in line:
                            line = line.split("@", 1)[1]
                        all_domains.add(line)
                log(f"  {url.split('/')[-2]}: +{len(all_domains)-count_before} new domains")
        except Exception as e:
            log(f"  FAILED {url}: {e}")

    # Add our manually-known bad domains as safety net
    manual_extras = {
        "heywhatsoup.com", "deapad.com", "deadpad.com", "mkzaso.com",
        "ryzid.com", "pertok.com", "minitts.net", "soppat.com",
        "fengnu.com", "algarr.com", "flownue.com", "4heats.com",
        "agoalz.com", "hlkes.com", "devlug.com", "dolofan.com",
        "bultoc.com", "lnovic.com", "denipl.com", "muncloud.com",
        "helesco.com", "bigonla.com", "opemails.com", "yopmail.com",
        "2insp.com", "okexbit.com", "bwmyga.com", "webxios.pro",
    }
    all_domains.update(manual_extras)

    DISPOSABLE_FILE.write_text("\n".join(sorted(all_domains)))
    log(f"Total disposable domains: {len(all_domains)}")


_DISP_CACHE = None

def get_disposable_set():
    global _DISP_CACHE
    if _DISP_CACHE is None:
        fetch_disposable_lists()
        if DISPOSABLE_FILE.exists():
            _DISP_CACHE = set(DISPOSABLE_FILE.read_text().splitlines())
        else:
            _DISP_CACHE = set()
    return _DISP_CACHE


# ──────────────────────────────────────────────────────────────
# LAYER 2: Domain intelligence (cached)
# ──────────────────────────────────────────────────────────────

def load_domain_cache():
    if DOMAIN_CACHE_FILE.exists():
        try:
            return json.loads(DOMAIN_CACHE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_domain_cache(cache):
    DOMAIN_CACHE_FILE.write_text(json.dumps(cache, indent=2, sort_keys=True))


_DOMAIN_CACHE = None

def _get_cache():
    global _DOMAIN_CACHE
    if _DOMAIN_CACHE is None:
        _DOMAIN_CACHE = load_domain_cache()
    return _DOMAIN_CACHE


def check_mx(domain):
    """Check if domain has MX record."""
    try:
        import dns.resolver
        resolver = dns.resolver.Resolver()
        resolver.timeout = 5
        resolver.lifetime = 10
        answers = resolver.resolve(domain, "MX")
        mx_records = sorted([(r.preference, str(r.exchange).rstrip(".")) for r in answers])
        return True, mx_records
    except ImportError:
        try:
            socket.gethostbyname(domain)
            return True, [(10, domain)]
        except Exception:
            return False, []
    except Exception:
        return False, []


def check_dns_record(domain, record_type):
    """Generic DNS query (TXT, A, etc.)"""
    try:
        import dns.resolver
        answers = dns.resolver.resolve(domain, record_type)
        return [str(r) for r in answers]
    except Exception:
        return []


def check_domain_age(domain):
    """Use python-whois if available; returns days since registration or None."""
    try:
        import whois
        w = whois.whois(domain)
        cd = w.creation_date
        if isinstance(cd, list):
            cd = cd[0]
        if cd:
            return (datetime.now() - cd).days
    except Exception:
        pass
    return None


def get_domain_intelligence(domain):
    """Return cached or freshly-computed domain info."""
    cache = _get_cache()

    cached = cache.get(domain)
    if cached:
        try:
            checked = datetime.fromisoformat(cached.get("checked_at", ""))
            if (datetime.now() - checked).days < DOMAIN_CACHE_DAYS:
                return cached
        except Exception:
            pass

    # Fresh check
    info = {
        "domain": domain,
        "is_major_provider": domain in MAJOR_PROVIDERS,
        "is_disposable": domain in get_disposable_set(),
        "checked_at": datetime.now().isoformat(),
    }

    # MX
    mx_ok, mx_records = check_mx(domain)
    info["mx_ok"] = mx_ok
    info["mx_records"] = mx_records[:3]

    # SPF
    txt = check_dns_record(domain, "TXT")
    info["has_spf"] = any("v=spf1" in t.lower() for t in txt)

    # DMARC
    dmarc_txt = check_dns_record(f"_dmarc.{domain}", "TXT")
    info["has_dmarc"] = any("v=dmarc1" in t.lower() for t in dmarc_txt)

    # A record
    info["has_a_record"] = len(check_dns_record(domain, "A")) > 0

    # Domain age (slow, only for non-major)
    if not info["is_major_provider"]:
        age = check_domain_age(domain)
        info["domain_age_days"] = age
    else:
        info["domain_age_days"] = 9999

    # Reputation score
    score = 0.0
    if info["is_major_provider"]:                score += 0.5
    if info["mx_ok"]:                            score += 0.2
    if info["has_spf"]:                          score += 0.1
    if info["has_dmarc"]:                        score += 0.1
    if info["has_a_record"]:                     score += 0.05
    if info["domain_age_days"] and info["domain_age_days"] > 365: score += 0.05
    if info["is_disposable"]:                    score = 0.0
    info["reputation_score"] = round(score, 2)

    cache[domain] = info
    save_domain_cache(cache)
    return info


# ──────────────────────────────────────────────────────────────
# LAYER 3: SMTP RCPT verification (cached)
# ──────────────────────────────────────────────────────────────

def load_smtp_cache():
    if SMTP_CACHE_FILE.exists():
        try: return json.loads(SMTP_CACHE_FILE.read_text())
        except Exception: return {}
    return {}


def save_smtp_cache(cache):
    SMTP_CACHE_FILE.write_text(json.dumps(cache, indent=2, sort_keys=True))


_SMTP_CACHE = None

def _smtp_cache():
    global _SMTP_CACHE
    if _SMTP_CACHE is None:
        _SMTP_CACHE = load_smtp_cache()
    return _SMTP_CACHE


def smtp_verify(email, mx_records):
    """
    Direct SMTP RCPT TO check.
    Returns: ("ok"|"reject"|"unknown"|"error", detail)
    Uses DOMAIN-LEVEL caching — checks once per domain, reuses for all emails on same domain.
    """
    _domain = email.split("@", 1)[-1].lower() if "@" in email else email
    # Skip SMTP for well-known accepting domains — saves 90%+ of checks
    _known_ok = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com",
                  "icloud.com", "me.com", "protonmail.com", "proton.me", "aol.com",
                  "mail.com", "zoho.com", "yandex.com", "gmx.com", "fastmail.com",
                  "rediffmail.com", "qq.com", "163.com", "126.com", "sina.com",
                  "eagle3d.com", "eagle3d.ai", "eagle3d.io", "eagle3d.stream"}
    if _domain in _known_ok:
        return ("ok", "known_domain_cache")
    cache = _smtp_cache()
    # Check domain-level cache first
    _domain_key = f"@domain:{_domain}"
    _domain_cached = cache.get(_domain_key)
    if _domain_cached:
        try:
            _dc = datetime.fromisoformat(_domain_cached["checked_at"])
            if (datetime.now() - _dc).days < SMTP_CACHE_DAYS:
                return _domain_cached["status"], _domain_cached.get("detail", "domain_cached")
        except Exception:
            pass
    # Also check email-level cache (backward compat)
    cached = cache.get(email)
    if cached:
        try:
            checked = datetime.fromisoformat(cached["checked_at"])
            if (datetime.now() - checked).days < SMTP_CACHE_DAYS:
                return cached["status"], cached.get("detail", "email_cached")
        except Exception:
            pass

    if not mx_records:
        result = ("error", "no_mx")
    else:
        result = ("unknown", "no_attempt")
        for pref, mx_host in mx_records[:2]:
            try:
                with smtplib.SMTP(mx_host, 25, timeout=4) as smtp:
                    smtp.helo("verifier.eagle3d.local")
                    smtp.mail("verify@eagle3d.local")
                    code, msg = smtp.rcpt(email)
                    msg_str = msg.decode() if isinstance(msg, bytes) else str(msg)
                    if code in (250, 251):
                        result = ("ok", f"smtp_accepted_{code}")
                        break
                    elif code in (550, 551, 553, 554):
                        result = ("reject", f"smtp_rejected_{code}_{msg_str[:50]}")
                        break
                    else:
                        result = ("unknown", f"smtp_code_{code}_{msg_str[:50]}")
            except smtplib.SMTPServerDisconnected:
                result = ("unknown", "smtp_disconnected")
            except smtplib.SMTPConnectError:
                result = ("unknown", "smtp_connect_failed")
            except (socket.timeout, TimeoutError):
                result = ("unknown", "smtp_timeout")
            except Exception as e:
                result = ("unknown", f"smtp_error_{type(e).__name__}")

    cache[email] = {
        "status":     result[0],
        "detail":     result[1],
        "checked_at": datetime.now().isoformat(),
    }
    # Also cache at domain level
    cache[_domain_key] = {
        "status":     result[0],
        "detail":     result[1],
        "checked_at": datetime.now().isoformat(),
    }
    save_smtp_cache(cache)
    return result


# ──────────────────────────────────────────────────────────────
# LAYER 4: Heuristic scoring
# ──────────────────────────────────────────────────────────────

def shannon_entropy(s):
    """Higher entropy = more random/gibberish."""
    if not s:
        return 0.0
    freq = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    length = len(s)
    return -sum((c/length) * math.log2(c/length) for c in freq.values())


def localpart_signals(email):
    """Compute heuristic signals from local part."""
    local = email.split("@")[0] if "@" in email else email
    signals = {
        "length": len(local),
        "digit_count": sum(c.isdigit() for c in local),
        "letter_count": sum(c.isalpha() for c in local),
        "entropy": round(shannon_entropy(local), 3),
        "has_underscore": "_" in local,
        "has_plus": "+" in local,
        "has_dot": "." in local,
        "is_random_pattern": bool(re.match(r'^[a-z0-9]{10,}$', local)) and shannon_entropy(local) > 3.0,
        "is_numeric_heavy": (sum(c.isdigit() for c in local) / max(len(local),1)) > 0.5,
        "is_suspicious": any(re.match(p, email) for p in SUSPICIOUS_PATTERNS),
    }
    return signals


# ──────────────────────────────────────────────────────────────
# LAYER 5: ML classifier (optional)
# ──────────────────────────────────────────────────────────────

_ML_MODEL = None


def load_ml_model():
    global _ML_MODEL
    if _ML_MODEL is not None or not ML_MODEL_FILE.exists():
        return _ML_MODEL
    try:
        import pickle
        with open(ML_MODEL_FILE, "rb") as f:
            _ML_MODEL = pickle.load(f)
        log(f"Loaded ML classifier from {ML_MODEL_FILE}")
    except Exception as e:
        log(f"ML load failed: {e}")
    return _ML_MODEL


def ml_score(email, domain_info, local_signals):
    model = load_ml_model()
    if model is None:
        return None
    try:
        features = [
            int(domain_info.get("is_major_provider", False)),
            int(domain_info.get("is_disposable", False)),
            int(domain_info.get("mx_ok", False)),
            int(domain_info.get("has_spf", False)),
            int(domain_info.get("has_dmarc", False)),
            int(domain_info.get("has_a_record", False)),
            domain_info.get("domain_age_days") or 0,
            domain_info.get("reputation_score", 0.0),
            local_signals["length"],
            local_signals["digit_count"],
            local_signals["entropy"],
            int(local_signals["is_random_pattern"]),
            int(local_signals["is_numeric_heavy"]),
            int(local_signals["is_suspicious"]),
        ]
        prob = model.predict_proba([features])[0]
        return float(prob[1])  # probability of "real"
    except Exception as e:
        log(f"ML score error: {e}")
        return None


# ──────────────────────────────────────────────────────────────
# LAYER 6: Combined verdict
# ──────────────────────────────────────────────────────────────

def check_syntax(email):
    if not email or "@" not in email:
        return False, "no_at"
    e = email.strip().lower()
    parts = e.split("@")
    if len(parts) != 2:
        return False, "malformed"
    local, domain = parts
    if not local or not domain or "." not in domain:
        return False, "missing_parts"
    if len(e) > 254 or len(local) > 64:
        return False, "too_long"
    if not re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', e):
        return False, "invalid_format"
    return True, "ok"


def is_internal(email):
    e = email.strip().lower()
    domain = e.split("@")[-1] if "@" in e else ""
    local  = e.split("@")[0] if "@" in e else ""
    if domain in INTERNAL_DOMAINS:
        return True, "internal_domain"
    for kw in INTERNAL_KEYWORDS:
        if kw in local:
            return True, f"internal_keyword_{kw}"
    return False, ""


def verify_email(email, use_smtp=True):
    """
    Full email verification.
    Returns: dict with:
      verdict: VALID | NOT_DETERMINED | INVALID
      category: ACCEPTED | DISPOSABLE | INTERNAL | INVALID_FORMAT | NO_MX | SUSPICIOUS | NOT_DETERMINED
      reason: human-readable
      signals: all collected signals
      score: 0.0 to 1.0
    """
    e = (email or "").strip().lower()

    result = {
        "email": e,
        "verdict": "INVALID",
        "category": "INVALID_FORMAT",
        "reason": "",
        "score": 0.0,
        "signals": {},
    }

    # L1: Syntax
    ok, why = check_syntax(e)
    if not ok:
        result["reason"] = f"syntax:{why}"
        return result

    # L1b: Internal
    is_int, why = is_internal(e)
    if is_int:
        result["verdict"] = "INVALID"
        result["category"] = "INTERNAL"
        result["reason"] = why
        return result

    domain = e.split("@")[1]

    # L2: Disposable list
    if domain in get_disposable_set():
        result["verdict"] = "INVALID"
        result["category"] = "DISPOSABLE"
        result["reason"] = f"in_multi_source_disposable_list:{domain}"
        result["score"] = 0.0
        return result

    # L3: Domain intelligence
    dom_info = get_domain_intelligence(domain)
    result["signals"]["domain"] = dom_info

    if dom_info.get("is_disposable"):
        result["verdict"] = "INVALID"
        result["category"] = "DISPOSABLE"
        result["reason"] = f"domain_marked_disposable:{domain}"
        return result

    if not dom_info.get("mx_ok"):
        result["verdict"] = "INVALID"
        result["category"] = "NO_MX"
        result["reason"] = f"no_mx_record:{domain}"
        return result

    # L4: Local part heuristics
    local_sig = localpart_signals(e)
    result["signals"]["local"] = local_sig

    if local_sig["is_suspicious"]:
        result["verdict"] = "INVALID"
        result["category"] = "SUSPICIOUS"
        result["reason"] = "matches_suspicious_pattern"
        return result

    if local_sig["is_random_pattern"]:
        result["verdict"] = "NOT_DETERMINED"
        result["category"] = "NOT_DETERMINED"
        result["reason"] = f"high_entropy_random_localpart_{local_sig['entropy']}"
        result["score"] = 0.3
        # don't return - let SMTP confirm

    # L5: SMTP verification (slow)
    if use_smtp:
        smtp_status, smtp_detail = smtp_verify(e, dom_info.get("mx_records", []))
        result["signals"]["smtp"] = {"status": smtp_status, "detail": smtp_detail}
        if smtp_status == "reject":
            result["verdict"] = "INVALID"
            result["category"] = "SMTP_REJECTED"
            result["reason"] = f"smtp_rejected:{smtp_detail}"
            result["score"] = 0.0
            return result

    # L6: ML score
    ml = ml_score(e, dom_info, local_sig)
    if ml is not None:
        result["signals"]["ml_score"] = ml

    # L7: Final scoring
    score = dom_info.get("reputation_score", 0.5)
    if use_smtp and result["signals"].get("smtp", {}).get("status") == "ok":
        score += 0.2
    if ml is not None:
        score = (score + ml) / 2

    result["score"] = round(min(score, 1.0), 2)

    # Final verdict
    if score >= 0.7:
        result["verdict"] = "VALID"
        result["category"] = "ACCEPTED"
        result["reason"] = f"all_checks_passed_score_{score}"
    elif score >= 0.4:
        result["verdict"] = "NOT_DETERMINED"
        result["category"] = "NOT_DETERMINED"
        result["reason"] = f"mixed_signals_score_{score}"
    else:
        result["verdict"] = "INVALID"
        result["category"] = "LOW_SCORE"
        result["reason"] = f"score_too_low_{score}"

    return result


# ──────────────────────────────────────────────────────────────
# Backward compatibility
# ──────────────────────────────────────────────────────────────

DISPOSABLE_DOMAINS = None  # populated on first use

def _ensure_disp_compat():
    global DISPOSABLE_DOMAINS
    if DISPOSABLE_DOMAINS is None:
        DISPOSABLE_DOMAINS = get_disposable_set()
    return DISPOSABLE_DOMAINS


if __name__ == "__main__":
    log("Initializing email intelligence system...")
    fetch_disposable_lists(force=True)
    log(f"Disposable list size: {len(get_disposable_set())}")

    test = [
        "djcm16@gmail.com",
        "isak@adapt.se",
        "jara@libelium.com",
        "crankytorvalds0@heywhatsoup.com",
        "test123@mailinator.com",
        "fake@asdjkflwer.xyz",
    ]
    for em in test:
        result = verify_email(em, use_smtp=False)
        print(f"\n{em}")
        print(f"  verdict:  {result['verdict']}")
        print(f"  category: {result['category']}")
        print(f"  reason:   {result['reason']}")
        print(f"  score:    {result['score']}")
