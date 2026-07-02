"""
email_validator_engine.py
LAYER 3 - EMAIL VALIDATION ENGINE
  a) Syntax check (regex + RFC via email-validator library)
  b) Disposable domain blocklist (auto-updated from 10k+ list)
  c) MX record DNS lookup
  d) SMTP handshake (optional)
  e) ML classifier confidence
"""
import re
import os
import json
import socket
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta
from functools import lru_cache

DATA_DIR = Path("data_output")
DATA_DIR.mkdir(exist_ok=True)

DISPOSABLE_LIST_FILE = DATA_DIR / "disposable_domains.txt"
DISPOSABLE_LIST_URL  = (
    "https://raw.githubusercontent.com/disposable-email-domains/"
    "disposable-email-domains/master/disposable_email_blocklist.conf"
)

# ─── Disposable domain list (auto-updated weekly) ──────
def load_disposable_domains() -> set:
    """Load disposable domain list. Auto-update if older than 7 days."""
    needs_update = True
    if DISPOSABLE_LIST_FILE.exists():
        age_hours = (datetime.now().timestamp() - DISPOSABLE_LIST_FILE.stat().st_mtime) / 3600
        if age_hours < 24 * 7:
            needs_update = False

    if needs_update:
        try:
            print(f"[Validator] Updating disposable domain list...", flush=True)
            req = urllib.request.Request(
                DISPOSABLE_LIST_URL,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                content = r.read().decode("utf-8")
            DISPOSABLE_LIST_FILE.write_text(content)
            print(f"[Validator] Updated: {len(content.splitlines())} domains", flush=True)
        except Exception as e:
            print(f"[Validator] Update failed: {e}", flush=True)

    if DISPOSABLE_LIST_FILE.exists():
        domains = set()
        for line in DISPOSABLE_LIST_FILE.read_text().splitlines():
            line = line.strip().lower()
            if line and not line.startswith("#"):
                domains.add(line)
        return domains
    
    # Fallback minimal list
    return {
        "mailinator.com","guerrillamail.com","tempmail.com","yopmail.com",
        "sharklasers.com","grr.la","spam4.me","trashmail.com","maildrop.cc",
        "dispostable.com","fakeinbox.com","minitts.net","deapad.com",
        "ryzid.com","soppat.com","fengnu.com","algarr.com","heywhatsoup.com",
        "4heats.com","pertok.com","agoalz.com","flownue.com","throwaway.email",
    }

DISPOSABLE_DOMAINS = load_disposable_domains()
print(f"[Validator] Loaded {len(DISPOSABLE_DOMAINS)} disposable domains", flush=True)


# ─── Internal/skip lists ────────────────────────────────
INTERNAL_DOMAINS = {"eagle3dstreaming.com", "eagle3d.com"}
INTERNAL_KEYWORDS = ["eagle3d", "e3ds_", "_e3ds", "internal-test"]

SUSPICIOUS_PATTERNS = [
    r'^test\d*@', r'^demo\d*@', r'^fake\d*@', r'^sample\d*@',
    r'^noreply@', r'^no-reply@', r'^donotreply@',
    r'^a{3,}@', r'^x{3,}@', r'^q{3,}@', r'^z{3,}@',
    r'^bob\d+@', r'^alice\d+@', r'^maria\d+@', r'^john\d+@',
    r'^user\d+@', r'^abc\d+@', r'^123\d*@',
]

PROFESSIONAL_DOMAINS = {
    "gmail.com","yahoo.com","hotmail.com","outlook.com",
    "icloud.com","protonmail.com","me.com","live.com",
    "aol.com","zoho.com","mail.com","yandex.com","gmx.com",
}


# ─── Layer 3a: Syntax check ──────────────────────────────
def check_syntax(email: str) -> tuple:
    """Returns (is_valid, reason)"""
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
    
    # Library validation
    try:
        from email_validator import validate_email as lib_val
        lib_val(e, check_deliverability=False)
    except ImportError:
        pass
    except Exception as ex:
        return False, f"lib_invalid"
    
    return True, "ok"


# ─── Layer 3b: Disposable check ─────────────────────────
def check_disposable(email: str) -> tuple:
    """Returns (is_clean, reason)"""
    domain = email.split("@")[-1].lower() if "@" in email else ""
    if domain in DISPOSABLE_DOMAINS:
        return False, "disposable"
    return True, "ok"


# ─── Layer 3c: MX record DNS lookup ─────────────────────
@lru_cache(maxsize=2000)
def check_mx(domain: str) -> tuple:
    """Returns (has_mx, reason). Cached for speed."""
    try:
        import dns.resolver
        resolver = dns.resolver.Resolver()
        resolver.timeout = 5
        resolver.lifetime = 10
        answers = resolver.resolve(domain, 'MX')
        if len(list(answers)) > 0:
            return True, "ok"
        return False, "no_mx"
    except ImportError:
        # dnspython not installed - fallback to socket check
        try:
            socket.gethostbyname(domain)
            return True, "ok_socket_fallback"
        except Exception:
            return False, "dns_fail"
    except Exception as e:
        err = type(e).__name__
        if "NoAnswer" in err or "NXDOMAIN" in err:
            return False, f"no_mx:{err}"
        return False, f"mx_error:{err}"


# ─── Layer 3d: SMTP handshake (optional, slow) ──────────
def check_smtp(email: str) -> tuple:
    """Optional SMTP RCPT TO check. Slow - only run when needed."""
    if os.environ.get("ENABLE_SMTP_CHECK","0") != "1":
        return True, "skipped"
    
    try:
        import smtplib
        domain = email.split("@")[-1]
        import dns.resolver
        mx_records = dns.resolver.resolve(domain, 'MX')
        mx = sorted([(r.preference, r.exchange.to_text()) for r in mx_records])[0][1]
        
        with smtplib.SMTP(mx, 25, timeout=10) as smtp:
            smtp.helo("verifier.local")
            smtp.mail("test@verifier.local")
            code, _ = smtp.rcpt(email)
            if code in (250, 251):
                return True, "smtp_ok"
            elif code in (550, 551, 553):
                return False, f"smtp_reject:{code}"
            else:
                return True, f"smtp_unknown:{code}"  # benefit of doubt
    except Exception as e:
        return True, f"smtp_skip:{type(e).__name__}"


# ─── Layer 3e: Skip checks (internal, suspicious) ──────
def check_skip(email: str) -> tuple:
    """Check if email should be skipped (internal/test/suspicious)."""
    e = email.strip().lower()
    domain = e.split("@")[-1] if "@" in e else ""
    local  = e.split("@")[0] if "@" in e else ""
    
    if domain in INTERNAL_DOMAINS:
        return False, "internal_domain"
    
    for kw in INTERNAL_KEYWORDS:
        if kw in local:
            return False, f"internal_keyword:{kw}"
    
    for pat in SUSPICIOUS_PATTERNS:
        if re.match(pat, e):
            return False, "suspicious_pattern"
    
    return True, "ok"


# ─── MAIN VALIDATION ────────────────────────────────────
def validate_batch(rows: list, check_dns: bool = True) -> tuple:
    """
    Run all validation layers on a batch of rows.
    Returns (verified_rows, skipped_rows).
    """
    verified = []
    skipped  = []
    
    for row in rows:
        email = ""
        for k in ("Email","email","EMAIL","__email_normalized__"):
            if k in row and row[k] and "@" in str(row[k]):
                email = str(row[k]).strip().lower()
                break
        
        if not email:
            skipped.append({**row, "__skip_reason__":"no_email"})
            continue
        
        # Layer a: Syntax
        ok, reason = check_syntax(email)
        if not ok:
            skipped.append({**row, "__skip_reason__":f"syntax:{reason}"})
            continue
        
        # Skip checks (internal/test)
        ok, reason = check_skip(email)
        if not ok:
            skipped.append({**row, "__skip_reason__":reason})
            continue
        
        # Layer b: Disposable
        ok, reason = check_disposable(email)
        if not ok:
            skipped.append({**row, "__skip_reason__":reason})
            continue
        
        # Layer c: MX (optional)
        mx_status = "skipped"
        if check_dns:
            domain = email.split("@")[-1]
            ok, reason = check_mx(domain)
            mx_status = reason
            if not ok:
                skipped.append({**row, "__skip_reason__":f"mx:{reason}"})
                continue
        
        # Layer d: SMTP (optional, off by default)
        smtp_status = "skipped"
        ok, reason = check_smtp(email)
        smtp_status = reason
        if not ok:
            skipped.append({**row, "__skip_reason__":f"smtp:{reason}"})
            continue
        
        # All checks passed
        verified.append({
            **row,
            "__email_normalized__": email,
            "__mx_status__": mx_status,
            "__smtp_status__": smtp_status,
            "__validation_status__": "verified",
        })
    
    return verified, skipped


def normalize_email(email: str) -> str:
    """
    Normalize email for dedup:
    - lowercase
    - strip +aliases (e.g., user+tag@gmail.com → user@gmail.com)
    - remove dots in gmail local part
    """
    e = email.strip().lower()
    if "@" not in e:
        return e
    
    local, domain = e.split("@", 1)
    
    # Strip +aliases
    if "+" in local:
        local = local.split("+")[0]
    
    # Gmail/Googlemail: remove dots
    if domain in ("gmail.com", "googlemail.com"):
        local = local.replace(".", "")
    
    return f"{local}@{domain}"


if __name__ == "__main__":
    # Test
    test_emails = [
        "good@gmail.com",
        "bad@mailinator.com",
        "test@example.com",
        "user@eagle3dstreaming.com",
        "invalid-email",
        "alice123@yopmail.com",
    ]
    for em in test_emails:
        ok1, r1 = check_syntax(em)
        ok2, r2 = check_skip(em)
        ok3, r3 = check_disposable(em)
        print(f"{em:35s} syntax={ok1}({r1}) skip={ok2}({r2}) disp={ok3}({r3})")
