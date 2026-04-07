import argparse
import base64
import os
import tempfile
import time
import random
from datetime import datetime
from pathlib import Path
from typing import Optional
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

USER_CONFIG = [
    {"email": "followsky45@gmail.com", "key": "followsky45"},
    {"email": "s73625789@gmail.com", "key": "s73625789"},
    {"email": "malothrajashekar85@gmail.com", "key": "malothrajashekar85"},
    {"email": "pchaitu2005@gmail.com", "key": "pchaitu2005"},
    {"email": "rushikeshhatti@gmail.com", "key": "rushikeshhatti"},
]
DEFAULT_SESSION_DIR = os.getenv("SESSION_DIR", "sessions")


def parse_arguments():
    parser = argparse.ArgumentParser(description="Google News scraper for one or all users")
    parser.add_argument(
        "--user",
        type=str,
        help="Email address of the user to scrape. Omit to scrape all configured users.",
    )
    parser.add_argument(
        "--session",
        type=str,
        help="Path to a single Playwright storage state JSON file.",
    )
    parser.add_argument(
        "--session-dir",
        type=str,
        default=DEFAULT_SESSION_DIR,
        help="Directory containing Playwright storage state JSON files.",
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=16,
        help="Maximum number of articles to scrape per user.",
    )
    return parser.parse_args()


def email_to_key(email: str) -> str:
    return email.lower().split("@")[0].replace(".", "_").replace("-", "_")


def load_session_path_for_user(user_key: str, session_dir: str) -> Optional[str]:
    session_file = Path(session_dir) / f"{user_key}.json"
    if session_file.exists():
        return str(session_file)

    env_secret = os.getenv(f"SESSION_{user_key.upper()}")
    if env_secret:
        temp_folder = Path(tempfile.mkdtemp(prefix=f"session_{user_key}_"))
        temp_folder.mkdir(parents=True, exist_ok=True)
        out_path = temp_folder / f"{user_key}.json"
        try:
            decoded = base64.b64decode(env_secret)
            out_path.write_bytes(decoded)
        except Exception:
            out_path.write_text(env_secret)
        return str(out_path)

    return None


DEFAULT_SUPABASE_URL = "https://otexqhduccxpprkzkuvm.supabase.co"
DEFAULT_SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im90ZXhxaGR1Y2N4cHBya3prdXZtIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ0MzY4NjcsImV4cCI6MjA5MDAxMjg2N30.YjSj95euIBqZyKifgC51xZSyP3a0IFHhJz0uvh3RSq4"


def get_supabase_client() -> Client:
    url = os.getenv("SUPABASE_URL", DEFAULT_SUPABASE_URL)
    key = os.getenv("SUPABASE_KEY", DEFAULT_SUPABASE_KEY)

    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY must be set as environment variables or defaults provided."
        )

    return create_client(url, key)


def get_full_content(article_url: str, browser_context):
    temp_page = browser_context.new_page()
    try:
        temp_page.goto(article_url, wait_until="domcontentloaded", timeout=45000)
        time.sleep(3)
        content = temp_page.evaluate(
            """() => {
                const paras = Array.from(document.querySelectorAll('p'));
                return paras.map(p => p.innerText).filter(t => t.length > 60).join('\\n\\n');
            }"""
        )
        temp_page.close()
        return content or "Content extraction failed"
    except Exception as exc:
        if not temp_page.is_closed():
            temp_page.close()
        return f"Error: {str(exc)[:120]}"


def extract_topic_blocks(page, max_topics=4, articles_per_topic=4):
    articles = []
    seen_links = set()

    try:
        topic_containers = page.query_selector_all('[data-n-tid], article, .JtKRv')
        for container in topic_containers:
            if len(articles) >= max_topics * articles_per_topic:
                break

            try:
                title_elem = container.query_selector('h3, h2, [role="heading"]')
                title = title_elem.inner_text().strip() if title_elem else "Unknown Title"
                if len(title) < 10:
                    continue

                source_elem = container.query_selector('[data-n-tid], .vr7PYb, .W8yrY, .mHwtf')
                source = source_elem.inner_text().split('\n')[0] if source_elem else "Unknown"

                link_elem = container.query_selector('a[href^="./articles"]')
                href = link_elem.get_attribute('href') if link_elem else None
                full_link = f"https://news.google.com{href[1:]}" if href else None

                time_elem = container.query_selector('time')
                published_time = (
                    time_elem.get_attribute('datetime')
                    or time_elem.inner_text()
                    if time_elem
                    else "Recently"
                )

                if full_link and full_link not in seen_links:
                    seen_links.add(full_link)
                    articles.append(
                        {
                            "title": title,
                            "source": source,
                            "link": full_link,
                            "published_time": published_time,
                        }
                    )
            except Exception:
                continue

        return articles[: max_topics * articles_per_topic]
    except Exception as exc:
        print(f"Error extracting topic blocks: {exc}")
        return []


def scrape_user(account_name: str, storage_state_path: str, max_articles: int, supabase):
    scraped_at = datetime.now().isoformat()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(storage_state=storage_state_path)
        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        print(f"\n--- Scraping user: {account_name} ---")
        page.goto("https://news.google.com/foryou", wait_until="networkidle", timeout=60000)
        time.sleep(5)

        articles = extract_topic_blocks(page, max_topics=4, articles_per_topic=4)
        if not articles:
            print("    ❌ No articles found for this user.")
            context.close()
            browser.close()
            return 0

        print(f"    ✅ Found {len(articles)} articles")
        total_saved = 0
        for idx, item in enumerate(articles[:max_articles], start=1):
            print(f"    [{idx}] {item['title'][:60]}...")
            full_text = get_full_content(item["link"], context)
            row = {
                "account_name": account_name,
                "source": item["source"],
                "title": item["title"],
                "full_text": full_text,
                "published_time": item["published_time"],
                "link": item["link"],
                "scraped_at": scraped_at,
            }
            try:
                supabase.table("news_articles").insert(row).execute()
                total_saved += 1
            except Exception as exc:
                print(f"      ⚠️ Insert failed: {exc}")
            time.sleep(random.uniform(1.5, 3.0))

        context.close()
        browser.close()
        print(f"    ✅ Saved {total_saved} articles for {account_name}")
        return total_saved


def main():
    args = parse_arguments()
    supabase = get_supabase_client()
    total_saved = 0
    users_to_run = []

    if args.user:
        users_to_run.append({"email": args.user, "key": email_to_key(args.user)})
    else:
        users_to_run = USER_CONFIG

    print("\n" + "=" * 70)
    print("🚀 GOOGLE NEWS SCRAPER")
    print(f"Loaded {len(users_to_run)} user(s)")
    print(f"Session directory: {args.session_dir}")
    print("=" * 70 + "\n")

    for user in users_to_run:
        storage_state_path = args.session or load_session_path_for_user(
            user["key"], args.session_dir
        )
        if not storage_state_path:
            print(
                f"⚠️  Skipping {user['email']}: no storage state found in {args.session_dir} and no SESSION_{user['key'].upper()} secret."
            )
            continue

        total_saved += scrape_user(
            user["email"], storage_state_path, args.max_articles, supabase
        )

    print("\n" + "=" * 70)
    print(f"✅ Completed. Total saved articles: {total_saved}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
