from pathlib import Path
from datetime import datetime
import re

app = Path("app.py")
if not app.exists():
    raise SystemExit("❌ app.py not found")

text = app.read_text(encoding="utf-8", errors="ignore")
backup = Path("backups") / f"app.py.route_repair.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
backup.write_text(text, encoding="utf-8")

# First, remove any previously broken injected block if present
text = re.sub(
    r'\n[ \t]{8}try:\n[ \t]{12}from customer_kpi_breakdown_ui import render_customer_kpi_breakdown\n[ \t]{12}render_customer_kpi_breakdown\(\)\n[ \t]{8}except Exception as _e:\n[ \t]{12}st\.warning\(f"Customer KPI breakdown unavailable: \{_e\}"\)\n',
    '\n',
    text,
    flags=re.M
)

lines = text.splitlines()
out = []
inserted = False

for i, line in enumerate(lines):
    out.append(line)

    # Find the route() dashboard branch
    if re.match(r'^[ \t]*if[ \t]+page[ \t]*==[ \t]*["\']dashboard["\']\s*:\s*$', line):
        # look ahead for the render_dashboard(...) call
        j = i + 1
        while j < len(lines):
            candidate = lines[j]
            if re.match(r'^[ \t]*(elif|else)\b', candidate):
                break
            out.append(lines[j])
            if "render_dashboard(" in candidate or "render_dashboard_preview(" in candidate:
                indent = re.match(r'^([ \t]*)', candidate).group(1)
                out.append(f"{indent}try:")
                out.append(f"{indent}    from customer_kpi_breakdown_ui import render_customer_kpi_breakdown")
                out.append(f"{indent}    render_customer_kpi_breakdown()")
                out.append(f"{indent}except Exception as _e:")
                out.append(f'{indent}    st.warning(f"Customer KPI breakdown unavailable: {{_e}}")')
                inserted = True
                j += 1
                break
            j += 1

        # continue copying from where we stopped
        k = j
        while k < len(lines):
            # stop only when loop returns to outer normal flow
            if k > i + 1:
                break
            k += 1

# The above loop duplicated some lines only if branch found.
# Safer fallback: rebuild from original lines with targeted insertion.
if inserted:
    # Rebuild cleanly from original with exact insertion after dashboard render line
    rebuilt = []
    done = False
    for line in lines:
        rebuilt.append(line)
        if not done and ("render_dashboard(" in line or "render_dashboard_preview(" in line):
            # only inject if previous non-empty significant line was dashboard if
            idx = len(rebuilt) - 2
            prev_nonempty = ""
            while idx >= 0:
                if rebuilt[idx].strip():
                    prev_nonempty = rebuilt[idx]
                    break
                idx -= 1
            if re.match(r'^[ \t]*if[ \t]+page[ \t]*==[ \t]*["\']dashboard["\']\s*:\s*$', prev_nonempty):
                indent = re.match(r'^([ \t]*)', line).group(1)
                rebuilt.append(f"{indent}try:")
                rebuilt.append(f"{indent}    from customer_kpi_breakdown_ui import render_customer_kpi_breakdown")
                rebuilt.append(f"{indent}    render_customer_kpi_breakdown()")
                rebuilt.append(f"{indent}except Exception as _e:")
                rebuilt.append(f'{indent}    st.warning(f"Customer KPI breakdown unavailable: {{_e}}")')
                done = True
    final_text = "\n".join(rebuilt) + "\n"
else:
    # Simpler direct regex fallback
    pattern = re.compile(
        r'(^[ \t]*if[ \t]+page[ \t]*==[ \t]*["\']dashboard["\']\s*:\s*\n)(^[ \t]+.*render_dashboard[^\n]*\n)',
        re.M
    )
    m = pattern.search(text)
    if not m:
        pattern = re.compile(
            r'(^[ \t]*if[ \t]+page[ \t]*==[ \t]*["\']dashboard["\']\s*:\s*\n)(^[ \t]+.*render_dashboard_preview[^\n]*\n)',
            re.M
        )
        m = pattern.search(text)
    if not m:
        raise SystemExit("❌ Could not locate dashboard branch and render call in app.py")

    render_line = m.group(2)
    indent = re.match(r'^([ \t]*)', render_line).group(1)
    injection = (
        render_line +
        f"{indent}try:\n"
        f"{indent}    from customer_kpi_breakdown_ui import render_customer_kpi_breakdown\n"
        f"{indent}    render_customer_kpi_breakdown()\n"
        f"{indent}except Exception as _e:\n"
        f'{indent}    st.warning(f"Customer KPI breakdown unavailable: {{_e}}")\n'
    )
    final_text = text[:m.start(2)] + injection + text[m.end(2):]

app.write_text(final_text, encoding="utf-8")
print(f"✅ app.py repaired and patched successfully")
print(f"Backup -> {backup}")
