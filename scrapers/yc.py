"""
yc.py — Scraper for YC Work at a Startup.
Uses Playwright to render the JS-heavy job listing pages.
Finds all job links (ycombinator.com/companies/xxx/jobs/xxx), parses company
info from /companies/xxx links, and location/job type from nearby text.
"""

import re
from typing import Optional

from bs4 import BeautifulSoup

from models import JobListing
from scrapers.base import BaseScraper
from config import RATE_LIMITS
from monitoring import get_logger

logger = get_logger("scrapers.yc")

# YC uses role-based URLs like /jobs/l/operations
ROLE_URLS = [
    "https://www.workatastartup.com/jobs/l/operations",
    "https://www.workatastartup.com/jobs/l/finance",
    "https://www.workatastartup.com/jobs/l/sales",
    "https://www.workatastartup.com/jobs/l/marketing",
    "https://www.workatastartup.com/jobs",  # All jobs page
]

# Match job detail links: ycombinator.com/companies/xxx/jobs/xxx
JOB_LINK_RE = re.compile(r"ycombinator\.com/companies/.+/jobs/")
# Match company links: /companies/xxx with text like "SnapMagic (S15) • description (about 1 month ago)"
COMPANY_LINK_RE = re.compile(r"/companies/[^/]+")
# Parse company link text: "CompanyName (S15) • description (about X ago)" or "CompanyName (S15) • description"
COMPANY_TEXT_RE = re.compile(
    r"^\s*(.+?)\s*\(([A-Z]\d+)\)\s*[•·]\s*(.+?)(?:\s*\(about\s+.+\))?\s*$",
    re.DOTALL,
)
# Location/job type near job link: "fulltimeSan Francisco, CA, US" or "parttime Remote"
LOCATION_JOBTYPE_RE = re.compile(
    r"(?:fulltime|parttime|contract|internship)\s*([^·\n]*)",
    re.IGNORECASE,
)


class YCScraper(BaseScraper):
    def __init__(self):
        limits = RATE_LIMITS.get("yc", {})
        super().__init__(
            name="YC Work at a Startup",
            delay_min=limits.get("delay_min", 1.0),
            delay_max=limits.get("delay_max", 2.0),
            max_pages=limits.get("max_pages", 30),
            max_retries=limits.get("max_retries", 3),
        )

    def _get_base_url(self) -> str:
        return "https://www.workatastartup.com"

    def scrape(self) -> list[JobListing]:
        logger.info("Starting YC Work at a Startup scrape")
        all_listings = []
        seen_urls = set()

        for url in ROLE_URLS:
            try:
                logger.info(f"Fetching {url}")
                html = self._scroll_and_fetch(url, scroll_count=10, wait_seconds=2.0)
                listings = self._parse_page(html, seen_urls)
                for L in listings:
                    all_listings.append(L)
                logger.info(f"YC {url.split('/')[-1]}: found {len(listings)} listings")
                self._rate_limit()
            except Exception as e:
                logger.warning(f"YC scrape failed for {url}: {e}")
                continue

        logger.info(f"YC scrape complete: {len(all_listings)} listings found")
        return all_listings

    def _parse_page(self, html: str, seen_urls: set[str]) -> list[JobListing]:
        soup = BeautifulSoup(html, "html.parser")
        listings = []

        # Find ALL job links: ycombinator.com/companies/xxx/jobs/xxx
        job_links = soup.find_all("a", href=re.compile(r"ycombinator\.com/companies/.+/jobs/"))

        for link in job_links:
            href = link.get("href", "")
            if not href or JOB_LINK_RE.search(href) is None:
                continue
            job_url = href if href.startswith("http") else f"https://www.{href.lstrip('/')}"
            if job_url in seen_urls:
                continue
            seen_urls.add(job_url)

            title = link.get_text(strip=True)
            if not title or len(title) < 2:
                continue

            # Find container (card/row) that holds this job link
            container = link
            for _ in range(12):
                container = container.parent
                if container is None:
                    break
                container_text = container.get_text(" ", strip=True)
                if len(container_text) > 80:
                    break

            if container is None:
                container = link

            block_text = container.get_text(" ", strip=True)

            # Company: from link to /companies/xxx with text "Name (BATCH) • description"
            company_display = ""
            company_links = container.find_all("a", href=COMPANY_LINK_RE)
            for cl in company_links:
                text = cl.get_text(" ", strip=True)
                if not text or len(text) < 3:
                    continue
                match = COMPANY_TEXT_RE.match(text)
                if match:
                    name, batch, desc = match.group(1).strip(), match.group(2), match.group(3).strip()
                    company_display = f"{name} ({batch})"
                    break
                # Fallback: "Name (BATCH)" only
                simple = re.match(r"^\s*(.+?)\s*\(([A-Z]\d+)\)\s*$", text)
                if simple:
                    company_display = f"{simple.group(1).strip()} ({simple.group(2)})"
                    break
            if not company_display and company_links:
                first = company_links[0].get_text(strip=True)
                if first:
                    company_display = first[:80]

            # Location and job type: e.g. "fulltimeSan Francisco, CA, US"
            location = ""
            loc_match = LOCATION_JOBTYPE_RE.search(block_text)
            if loc_match:
                location = loc_match.group(1).strip().strip(",")
            if not location and ("remote" in block_text.lower() or "Remote" in block_text):
                location = "Remote"

            listings.append(
                JobListing(
                    title=title,
                    company=company_display or "Unknown",
                    location=location,
                    description=block_text[:500],
                    url=job_url,
                    source="YC Work at a Startup",
                    raw_html=str(container)[:1000],
                )
            )

        return listings
