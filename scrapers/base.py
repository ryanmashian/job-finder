"""
base.py — Base scraper with Playwright browser support for JS-heavy sites.
"""

import random
import time
from abc import ABC, abstractmethod

import httpx

from models import JobListing
from monitoring import get_logger

logger = get_logger("scrapers.base")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/120.0.0.0",
]


class BaseScraper(ABC):
    def __init__(self, name, delay_min=2.0, delay_max=4.0, max_pages=30, max_retries=3):
        self.name = name
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.max_pages = max_pages
        self.max_retries = max_retries

    def _rate_limit(self):
        time.sleep(random.uniform(self.delay_min, self.delay_max))

    def _fetch_with_browser(self, url: str, wait_selector: str = None, wait_seconds: float = 3.0) -> str:
        """Fetch a page using Playwright headless Chrome. Returns page HTML."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={"width": 1920, "height": 1080},
            )
            page = context.new_page()
            try:
                page.goto(url, timeout=30000, wait_until="networkidle")
                if wait_selector:
                    try:
                        page.wait_for_selector(wait_selector, timeout=10000)
                    except Exception:
                        pass
                time.sleep(wait_seconds)
                html = page.content()
                return html
            finally:
                browser.close()

    def _scroll_and_fetch(self, url: str, scroll_count: int = 3, wait_seconds: float = 2.0) -> str:
        """Fetch a page with scrolling to load lazy content."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={"width": 1920, "height": 1080},
            )
            page = context.new_page()
            try:
                page.goto(url, timeout=30000, wait_until="networkidle")
                time.sleep(wait_seconds)

                for _ in range(scroll_count):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(wait_seconds)

                return page.content()
            finally:
                browser.close()

    @abstractmethod
    def scrape(self) -> list[JobListing]:
        pass

    def health_check(self) -> bool:
        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.head(self._get_base_url(), headers={"User-Agent": random.choice(USER_AGENTS)})
                return r.status_code < 400
        except Exception:
            return False

    def _get_base_url(self) -> str:
        return ""

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
