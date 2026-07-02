from playwright.sync_api import sync_playwright
from config import BROWSER_SESSION_DIR, KPI_URL

def main():
    print("=" * 60, flush=True)
    print("  ONE-TIME LOGIN - Eagle 3D KPI Dashboard", flush=True)
    print("=" * 60, flush=True)
    print("", flush=True)
    print("A Chromium window will open.", flush=True)
    print("Log in to the KPI Dashboard.", flush=True)
    print("Once you SEE the dashboard, CLOSE the window.", flush=True)
    print("", flush=True)
    input("Press ENTER to launch the browser... ")

    print("Launching Chromium...", flush=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_SESSION_DIR),
            headless=False,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()
        print("Going to:", KPI_URL, flush=True)
        page.goto(KPI_URL)

        print("", flush=True)
        print(">>> Browser is open. Log in now.", flush=True)
        print(">>> When done, close the browser window.", flush=True)
        print("", flush=True)

        try:
            page.wait_for_event("close", timeout=0)
        except Exception as e:
            print("Browser closed:", e, flush=True)

        try:
            context.close()
        except Exception:
            pass

    print("", flush=True)
    print("Session saved to:", BROWSER_SESSION_DIR, flush=True)
    print("Now run: python scrape_kpi.py", flush=True)

if __name__ == "__main__":
    main()
