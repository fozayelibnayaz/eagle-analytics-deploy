from pathlib import Path
from urllib.parse import urlparse
import json
import re
import html

COOKIE_PATHS = [
    Path("data/linkedin_cookies.json"),
    Path("data_output/linkedin_cookies.json"),
]

LOGIN_BAD_MARKERS = (
    "/login",
    "/uas/",
    "/checkpoint",
    "/challenge",
    "flagship-web/login",
    "authwall",
)

RUNTIME_COOKIE_PATHS = [
    Path("data/linkedin_cookies_runtime.json"),
    Path("data_output/linkedin_cookies_runtime.json"),
]

RUNTIME_STATE_PATHS = [
    Path("data/linkedin_storage_state_runtime.json"),
    Path("data_output/linkedin_storage_state_runtime.json"),
]


def bad_login_url(url: str) -> bool:
    u = (url or "").lower()
    return any(x in u for x in LOGIN_BAD_MARKERS)


def _unescape(v):
    return html.unescape(str(v or "").strip())


def _extract_host(raw: str) -> str:
    s = _unescape(raw).strip().strip('"').strip("'")
    m = re.search(r'((?:www\.)?linkedin\.com)\b', s, re.I)
    if m:
        return m.group(1).lower()
    if s.startswith("http://") or s.startswith("https://"):
        try:
            parsed = urlparse(s)
            if parsed.netloc:
                return parsed.netloc.lower()
        except Exception:
            pass
    return s.strip("/").lstrip(".").lower()


def _normalize_same_site(v):
    s = _unescape(v).lower()
    if s in ("none", "no_restriction", "no restriction"):
        return "None"
    if s == "lax":
        return "Lax"
    if s == "strict":
        return "Strict"
    return None


def load_cookie_json():
    last_err = None
    for path in COOKIE_PATHS:
        if not path.exists():
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
            data = json.loads(raw)
            if isinstance(data, str):
                data = json.loads(data)
            if isinstance(data, list):
                return data, str(path)
        except Exception as e:
            last_err = e
    if last_err:
        raise RuntimeError(f"Could not parse LinkedIn cookies JSON: {last_err}")
    raise RuntimeError("No LinkedIn cookies JSON found in data/ or data_output/")


def normalize_cookie(c):
    name = _unescape(c.get("name"))
    value = _unescape(c.get("value"))

    if not name or value == "":
        return None

    path = _unescape(c.get("path") or "/") or "/"
    secure = bool(c.get("secure", True))
    http_only = bool(c.get("httpOnly", False))
    same_site = _normalize_same_site(c.get("sameSite"))
    host_only = bool(c.get("hostOnly", False))

    item = {
        "name": name,
        "value": value,
        "secure": secure,
        "httpOnly": http_only,
    }

    if same_site:
        item["sameSite"] = same_site

    exp = c.get("expirationDate", c.get("expires"))
    if exp not in (None, "", 0, "0"):
        try:
            item["expires"] = int(float(exp))
        except Exception:
            pass

    raw_url = _unescape(c.get("url"))
    if raw_url.startswith("http://") or raw_url.startswith("https://"):
        try:
            parsed = urlparse(raw_url)
            if parsed.scheme and parsed.netloc:
                item["url"] = f"{parsed.scheme}://{parsed.netloc}/"
                return item
        except Exception:
            pass

    host = _extract_host(c.get("domain") or c.get("url") or "")
    if not host:
        return None

    if host_only:
        item["url"] = f"https://{host}/"
    else:
        item["domain"] = "." + host.lstrip(".")
        item["path"] = path

    return item


def apply_cookie_editor_cookies(context):
    raw, source = load_cookie_json()

    normalized = []
    skipped = 0

    for c in raw:
        item = normalize_cookie(c)
        if not item:
            skipped += 1
            continue
        if item.get("url") or (item.get("domain") and item.get("path")):
            normalized.append(item)
        else:
            skipped += 1

    if not normalized:
        raise RuntimeError("No valid LinkedIn cookies after normalization")

    added = 0
    failed = 0

    for ck in normalized:
        try:
            context.add_cookies([ck])
            added += 1
        except Exception:
            failed += 1

    if added == 0:
        raise RuntimeError("All normalized cookies failed to add to Playwright context")

    print(f"[linkedin_cookie_bootstrap] source={source} raw={len(raw)} normalized={len(normalized)} added={added} skipped={skipped} failed={failed}")
    return added, source


def _get_live_page(page):
    try:
        if not page.is_closed():
            return page
    except Exception:
        pass

    try:
        pages = page.context.pages
        for p in reversed(pages):
            try:
                if not p.is_closed():
                    return p
            except Exception:
                continue
    except Exception:
        pass

    return page


def prime_linkedin_auth(page, company_id=None):
    admin_url = f"https://www.linkedin.com/company/{company_id}/admin/analytics/updates/" if company_id else None

    urls = []
    if admin_url:
        urls.append(admin_url)
    urls.extend([
        "https://www.linkedin.com/feed/",
        "https://www.linkedin.com/",
    ])

    last_url = ""
    for url in urls:
        try:
            page = _get_live_page(page)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            page = _get_live_page(page)
            try:
                page.wait_for_timeout(2500)
            except Exception:
                page = _get_live_page(page)
            last_url = getattr(page, "url", "")
        except Exception as e:
            return False, f"navigation_error::{url}::{e}"

        if bad_login_url(last_url):
            return False, last_url

        # If exact admin page is reached, auth is good enough for scraper
        if admin_url and "linkedin.com/company/" in last_url and "/admin/analytics/" in last_url:
            return True, last_url

    return True, last_url


def save_runtime_auth(context):
    try:
        cookies = context.cookies()
        for p in RUNTIME_COOKIE_PATHS:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
    except Exception:
        pass

    try:
        state = context.storage_state()
        for p in RUNTIME_STATE_PATHS:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass
