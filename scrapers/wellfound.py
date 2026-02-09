"""
wellfound.py — Scraper for Wellfound using Playwright (required — blocks simple HTTP).
"""

import re
from typing import Optional

from bs4 import BeautifulSoup

from models import JobListing
from scrapers.base import BaseScraper
from config import RATE_LIMITS
from monitoring import get_logger

logger = get_logger("scrapers.wellfound")

SEARCH_URLS = [
    "https://wellfound.com/role/operations",
    "https://wellfound.com/role/business-operations",
    "https://wellfound.com/role/strategy",
    "https://wellfound.com/role/finance",
]


class WellfoundScraper(BaseScraper):
    def __init__(self):
        limits = RATE_LIMITS.get("wellfound", {})
        super().__init__(
            name="Wellfound",
            delay_min=limits.get("delay_min", 2.0),
            delay_max=limits.get("delay_max", 4.0),
            max_pages=limits.get("max_pages", 50),
            max_retries=limits.get("max_retries", 3),
        )

    def _get_base_url(self) -> str:
        return "https://wellfound.com"

    def scrape(self) -> list[JobListing]:
        logger.info("Starting Wellfound scrape")
        all_listings = []

        for url in SEARCH_URLS:
            try:
                logger.info(f"Fetching {url}")
                html = self._scroll_and_fetch(url, scroll_count=5, wait_seconds=3.0)
                listings = self._parse_page(html)
                all_listings.extend(listings)
                logger.info(f"Wellfound {url.split('/')[-1]}: found {len(listings)} listings")
                self._rate_limit()
            except Exception as e:
                logger.warning(f"Wellfound scrape failed for {url}: {e}")
                continue

        logger.info(f"Wellfound scrape complete: {len(all_listings)} listings found")
        return all_listings

    def _parse_page(self, html: str) -> list[JobListing]:
        soup = BeautifulSoup(html, "html.parser")
        listings = []

        # Wellfound renders job cards with company info and roles
        # Try multiple selector strategies
        job_cards = (
            soup.select("[class*='styles_component']") or
            soup.select("[class*='job']") or
            soup.select("[class*='startup-']") or
            soup.select("[class*='result']")
        )

        for card in job_cards:
            card_listings = self._parse_card(card)
            listings.extend(card_listings)

        # Fallback: parse by finding all job-related links
        if not listings:
            listings = self._parse_by_links(soup)

        return listings

    def _parse_card(self, card) -> list[JobListing]:
        """Parse a Wellfound card — may contain multiple roles per company."""
        results = []
        
        # Get company name
        company = ""
        company_el = card.select_one("h2, [class*='company'], [class*='name']")
        if company_el:
            company = company_el.get_text(strip=True)

        # Get all role links within this card
        role_links = card.find_all("a", href=re.compile(r"/jobs/|/company/"))
        
        seen_titles = set()
        for link in role_links:
            title = link.get_text(strip=True)
            href = link.get("href", "")
            
            if not title or len(title) < 3 or title in seen_titles:
                continue
            if title == company:  # Skip company name links
                continue
                
            seen_titles.add(title)
            url = href if href.startswith("http") else f"https://wellfound.com{href}"

            # Location — look nearby
            location = ""
            parent = link.parent
            if parent:
                loc_el = parent.find(string=re.compile(r'San Francisco|Los Angeles|New York|Remote|NYC|SF|LA', re.IGNORECASE))
                if loc_el:
                    location = loc_el.strip()

            # Salary — look for dollar amounts nearby
            salary_min, salary_max = None, None
            card_text = card.get_text()
            salary_match = re.search(r'\$(\d+)[kK]\s*[-–]\s*\$(\d+)[kK]', card_text)
            if salary_match:
                salary_min = float(salary_match.group(1)) * 1000
                salary_max = float(salary_match.group(2)) * 1000

            results.append(JobListing(
                title=title,
                company=company,
                location=location,
                description=card.get_text(" ", strip=True)[:500],
                salary_min=salary_min,
                salary_max=salary_max,
                url=url,
                source="Wellfound",
            ))

        return results

    def _parse_by_links(self, soup) -> list[JobListing]:
        """Fallback: find all job-related links on the page."""
        listings = []
        seen = set()

        all_links = soup.find_all("a", href=True)
        for link in all_links:
            href = link.get("href", "")
            text = link.get_text(strip=True)

            # Look for job-related links
            if not text or len(text) < 5:
                continue
            if href in seen:
                continue

            # Check if it looks like a job title
            ops_keywords = ["operations", "ops", "strategy", "chief of staff", "associate", "analyst", "manager", "finance", "growth", "revenue"]
            if any(kw in text.lower() for kw in ops_keywords):
                seen.add(href)
                url = href if href.startswith("http") else f"https://wellfound.com{href}"

                # Try to find company from nearby elements
                company = ""
                parent = link.parent
                if parent and parent.parent:
                    h2 = parent.parent.find("h2")
                    if h2:
                        company = h2.get_text(strip=True)

                listings.append(JobListing(
                    title=text,
                    company=company,
                    location="",
                    description="",
                    url=url,
                    source="Wellfound",
                ))

        return listings
