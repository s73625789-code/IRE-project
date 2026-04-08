import argparse
import base64
import json
import os
import random
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib import error, parse, request
from playwright.sync_api import sync_playwright

USER_CONFIG = [
    {
        "email": "followsky45@gmail.com",
        "key": "followsky45",
        "account_name": "Sankar",
    },
    {
        "email": "s73625789@gmail.com",
        "key": "s73625789",
        "account_name": "Sudheshna",
    },
    {
        "email": "malothrajashekar85@gmail.com",
        "key": "malothrajashekar85",
        "account_name": "Rajashekar",
    },
    {
        "email": "pchaitu2005@gmail.com",
        "key": "pchaitu2005",
        "account_name": "Chaitanya",
    },
    {
        "email": "rushikeshhatti@gmail.com",
        "key": "rushikeshhatti",
        "account_name": "Rushikesh",
    },
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
    parser.add_argument(
        "--max-topics",
        type=int,
        default=4,
        help="Maximum number of Google News topic blocks to scan per user.",
    )
    parser.add_argument(
        "--articles-per-topic",
        type=int,
        default=4,
        help="Maximum number of articles to keep from each topic block.",
    )
    parser.add_argument(
        "--min-hours-between-runs",
        type=float,
        default=6,
        help="Skip a user if their latest scrape is newer than this many hours.",
    )
    return parser.parse_args()


def email_to_key(email: str) -> str:
    return email.lower().split("@")[0].replace(".", "_").replace("-", "_")


def resolve_user(email: str) -> dict:
    for user in USER_CONFIG:
        if user["email"].lower() == email.lower():
            return user

    return {
        "email": email,
        "key": email_to_key(email),
        "account_name": email,
    }


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


def get_supabase_config() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", DEFAULT_SUPABASE_URL)
    key = os.getenv("SUPABASE_KEY", DEFAULT_SUPABASE_KEY)

    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY must be set as environment variables or defaults provided."
        )

    return url.rstrip("/"), key


def supabase_request(
    supabase_url: str,
    supabase_key: str,
    method: str,
    path: str,
    query: Optional[dict] = None,
    payload: Optional[object] = None,
    extra_headers: Optional[dict] = None,
):
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
    }
    if extra_headers:
        headers.update(extra_headers)

    url = f"{supabase_url}{path}"
    if query:
        url = f"{url}?{parse.urlencode(query)}"

    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=60) as response:
            raw = response.read().decode("utf-8")
            if not raw:
                return None
            return json.loads(raw)
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase REST {exc.code}: {body}") from exc


def parse_scraped_at(value: str) -> Optional[datetime]:
    if not value:
        return None

    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def should_skip_recent_scrape(
    account_name: str,
    min_hours_between_runs: float,
    supabase_url: str,
    supabase_key: str,
) -> bool:
    if min_hours_between_runs <= 0:
        return False

    try:
        rows = supabase_request(
            supabase_url,
            supabase_key,
            "GET",
            "/rest/v1/news_articles",
            query={
                "select": "scraped_at",
                "account_name": f"eq.{account_name}",
                "order": "scraped_at.desc",
                "limit": "1",
            },
            extra_headers={"Accept": "application/json"},
        )
    except Exception as exc:
        print(f"    Warning: could not check previous scrape time for {account_name}: {exc}")
        return False

    rows = rows or []
    if not rows:
        return False

    last_scraped_at = parse_scraped_at(rows[0].get("scraped_at"))
    if not last_scraped_at:
        return False

    next_allowed_at = last_scraped_at + timedelta(hours=min_hours_between_runs)
    now_utc = datetime.now(timezone.utc)
    if now_utc < next_allowed_at:
        remaining = next_allowed_at - now_utc
        remaining_hours = round(remaining.total_seconds() / 3600, 2)
        print(
            f"    Skipping {account_name}: last scrape was at {last_scraped_at.isoformat()}, "
            f"next allowed run in about {remaining_hours} hour(s)."
        )
        return True

    return False


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

    # Wait for page to fully load
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(5000)

    anchors = page.query_selector_all('a[href*="/articles/"], a[href*="/read/"]')
    print(f"    🔎 Found {len(anchors)} potential article links")

    for a in anchors:
        try:
            href = a.get_attribute("href")
            if not href:
                continue

            # Build full URL
            full_link = href if href.startswith("http") else f"https://news.google.com{href[1:]}"
            if full_link in seen_links:
                continue

            title = a.inner_text().strip()
            if len(title) < 5:
                continue

            source = "Unknown"
            published_time = "Unknown"

            try:
                # 🔥 Get article container
                container = a.evaluate_handle(
                    "el => el.closest('article') || el.parentElement.parentElement"
                )
                container_el = container.as_element()

                if container_el:
                    # ✅ Extract published time
                    time_elem = container_el.query_selector("time")
                    if time_elem:
                        published_time = (
                            time_elem.get_attribute("datetime")
                            or time_elem.inner_text()
                        )

                    # ✅ Extract source (multiple fallback selectors)
                    source_elem = container_el.query_selector(
                        "div[data-n-tid], .vr7PYb, .W8yrY"
                    )
                    if source_elem:
                        source = source_elem.inner_text().split("\n")[0]

            except Exception:
                pass

            seen_links.add(full_link)

            articles.append({
                "title": title,
                "source": source,
                "link": full_link,
                "published_time": published_time,
            })

            # Limit articles
            if len(articles) >= max_topics * articles_per_topic:
                break

        except Exception:
            continue
    return articles
def scrape_user(
    account_name: str,
    storage_state_path: str,
    max_articles: int,
    max_topics: int,
    articles_per_topic: int,
    min_hours_between_runs: float,
    supabase_url: str,
    supabase_key: str,
):
    if should_skip_recent_scrape(
        account_name, min_hours_between_runs, supabase_url, supabase_key
    ):
        return 0

    scraped_at = datetime.now(timezone.utc).isoformat()

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

        articles = extract_topic_blocks(
            page,
            max_topics=max_topics,
            articles_per_topic=articles_per_topic,
        )
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
                supabase_request(
                    supabase_url,
                    supabase_key,
                    "POST",
                    "/rest/v1/news_articles",
                    payload=row,
                    extra_headers={
                        "Accept": "application/json",
                        "Prefer": "return=minimal",
                    },
                )
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
    supabase_url, supabase_key = get_supabase_config()
    total_saved = 0
    users_to_run = []

    if args.user:
        users_to_run.append(resolve_user(args.user))
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
            user["account_name"],
            storage_state_path,
            args.max_articles,
            args.max_topics,
            args.articles_per_topic,
            args.min_hours_between_runs,
            supabase_url,
            supabase_key,
        )

    print("\n" + "=" * 70)
    print(f"✅ Completed. Total saved articles: {total_saved}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
