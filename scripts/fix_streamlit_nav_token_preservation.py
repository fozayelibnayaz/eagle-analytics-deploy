from pathlib import Path
from datetime import datetime

p = Path("app.py")
if not p.exists():
    raise SystemExit("❌ app.py not found")

backup = Path("backups") / f"app.py.nav_token_fix.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
backup.write_text(p.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")

text = p.read_text(encoding="utf-8", errors="ignore")

helper = '''
def _page_href(page_key: str, keep_token: bool = True) -> str:
    qp = st.query_params
    extras = []

    def _one(v):
        if isinstance(v, list):
            return v[0] if v else ""
        return str(v or "")

    if keep_token:
        for key in ("t", "prd", "cmp"):
            val = _one(qp.get(key, ""))
            if val:
                extras.append(f"{key}={val}")

    query = "&".join([f"page={page_key}"] + extras)
    return "?" + query

'''

if "_page_href(page_key" not in text:
    anchor = "def get_current_page() -> str:"
    if anchor in text:
        text = text.replace(anchor, helper + "\n" + anchor, 1)
    else:
        text = helper + "\n" + text

# top nav
text = text.replace(
    'f\'href="?page={k}" target="_top">',
    'f\'href="{_page_href(k)}" target="_self">'
)

# logo/dashboard link
text = text.replace(
    'href="?page=dashboard" target="_top"',
    'href="{_page_href(\'dashboard\')}" target="_self"'
)

# sidebar buttons
text = text.replace(
    'f\'<a class="{cls}" href="?page={k}" \'',
    'f\'<a class="{cls}" href="{_page_href(k, keep_token=(k != "_logout"))}" \''
)
text = text.replace(
    'f\'target="top" title="{lbl}">{ic}</a>\'',
    'f\'target="_self" title="{lbl}">{ic}</a>\''
)

# settings icon
text = text.replace(
    'href="?page=settings" target="_top"',
    'href="{_page_href(\'settings\')}" target="_self"'
)

p.write_text(text, encoding="utf-8")
print(f"✅ app.py patched for token-preserving internal navigation (backup -> {backup})")
