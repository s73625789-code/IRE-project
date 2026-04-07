import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Save Google News login session storage state for a user"
    )
    parser.add_argument(
        "--user",
        type=str,
        required=True,
        help="User email or account name",
    )
    parser.add_argument(
        "--storage",
        type=str,
        default=None,
        help="Output path for storage state JSON",
    )
    return parser.parse_args()


def save_session(user_email, storage_state_path):
    storage_file = Path(storage_state_path)
    storage_file.parent.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 70)
    print("🔐 GOOGLE NEWS LOGIN SESSION SAVER")
    print("=" * 70)
    print(f"User: {user_email}")
    print(f"Storage state: {storage_file}")
    print("=" * 70 + "\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context()
        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        print("🌐 Opening a browsing session...")
        page.goto("https://www.wikipedia.org")
        page.wait_for_timeout(2000)
        page.goto("https://accounts.google.com/ServiceLogin?hl=en")

        print("\n✅ Please log in manually in the opened browser window.")
        print("   1. Enter your Google email")
        print("   2. Solve CAPTCHA if shown")
        print("   3. Complete any 2FA prompts")
        print("   4. Wait until login is finished")
        print("   5. Keep the browser open until you press ENTER")
        input("\nPress ENTER after login is complete and you are on the Google account page...")

        try:
            context.storage_state(path=str(storage_file))
            print(f"\n✅ Saved storage state to: {storage_file}")
        except Exception as exc:
            print(f"\n❌ Failed to save storage state: {exc}")
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    args = parse_arguments()
    storage_path = args.storage or f"sessions/{args.user.split('@')[0]}.json"
    save_session(args.user, storage_path)
