"""
startups_gallery.py — Scraper for startups.gallery/jobs using Playwright.
The site loads jobs dynamically via JavaScript. We scroll extensively
and interact with search/filter elements on the page.
"""

import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from models import JobListing
from scrapers.base import BaseScraper
from config import RATE_LIMITS
from monitoring import get_logger

logger = get_logger("scrapers.startups_gallery")

BASE_URL = "https://startups.gallery"
JOBS_URL = f"{BASE_URL}/jobs"

# Location pages to check
LOCATION_URLS = [
    "https://startups.gallery/categories/locations/cities/los-angeles",
    "https://startups.gallery/categories/locations/cities/san-francisco",
    "https://startups.gallery/categories/locations/cities/new-york",
]


class StartupsGalleryScraper(BaseScraper):
    def __init__(self):
        limits = RATE_LIMITS.get("startups_gallery", {})
        super().__init__(
            name="startups.gallery",
            delay_min=limits.get("delay_min", 2.0),
            delay_max=limits.get("delay_max", 3.0),
            max_pages=limits.get("max_pages", 20),
            max_retries=limits.get("max_retries", 3),
        )

    def _get_base_url(self) -> str:
        return BASE_URL

    def scrape(self) -> list[JobListing]:
        logger.info("Starting startups.gallery scrape")
        all_listings = []
        seen_urls = set()

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = context.new_page()

                # Scrape main jobs page with extensive scrolling
                logger.info(f"Fetching {JOBS_URL}")
                page.goto(JOBS_URL, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)

                # Try to interact with search/filter if available
                self._try_search(page, "operations")
                html = self._scroll_page(page, scroll_count=15)
                listings = self._parse_page(html)
                for listing in listings:
                    if listing.url not in seen_urls:
                        seen_urls.add(listing.url)
                        all_listings.append(listing)
                logger.info(f"startups.gallery 'operations' search: found {len(all_listings)} listings")

                self._rate_limit()

                # Try "chief of staff" search
                page.goto(JOBS_URL, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)
                self._try_search(page, "chief of staff")
                html = self._scroll_page(page, scroll_count=10)
                listings = self._parse_page(html)
                new = 0
                for listing in listings:
                    if listing.url not in seen_urls:
                        seen_urls.add(listing.url)
                        all_listings.append(listing)
                        new += 1
                logger.info(f"startups.gallery 'chief of staff' search: found {new} new listings")

                self._rate_limit()

                # Try "strategy" search
                page.goto(JOBS_URL, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)
                self._try_search(page, "strategy")
                html = self._scroll_page(page, scroll_count=10)
                listings = self._parse_page(html)
                new = 0
                for listing in listings:
                    if listing.url not in seen_urls:
                        seen_urls.add(listing.url)
                        all_listings.append(listing)
                        new += 1
                logger.info(f"startups.gallery 'strategy' search: found {new} new listings")

                self._rate_limit()

                # Try location-specific pages
                for loc_url in LOCATION_URLS:
                    try:
                        logger.info(f"Fetching {loc_url}")
                        page.goto(loc_url, timeout=30000)
                        page.wait_for_load_state("networkidle", timeout=15000)
                        html = self._scroll_page(page, scroll_count=10)
                        listings = self._parse_page(html)
                        new = 0
                        for listing in listings:
                            if listing.url not in seen_urls:
                                seen_urls.add(listing.url)
                                all_listings.append(listing)
                                new += 1
                        logger.info(f"startups.gallery {loc_url}: found {new} new listings")
                        self._rate_limit()
                    except Exception as e:
                        logger.warning(f"startups.gallery location page failed for {loc_url}: {e}")
                        continue

                browser.close()

        except Exception as e:
            logger.warning(f"startups.gallery scrape failed: {e}")

        logger.info(f"startups.gallery scrape complete: {len(all_listings)} listings found")
        return all_listings

    def _try_search(self, page, query: str):
        """Try to find and use a search box on the page."""
        try:
            search_selectors = [
                "input[type='search']",
                "input[placeholder*='earch']",
                "input[placeholder*='ilter']",
                "input[placeholder*='ind']",
                "input[type='text']",
            ]
            for selector in search_selectors:
                el = page.query_selector(selector)
                if el:
                    el.click()
                    el.fill(query)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(3000)
                    logger.info(f"Searched for '{query}' using {selector}")
                    return True
        except Exception as e:
            logger.debug(f"Search attempt failed: {e}")
        return False

    def _scroll_page(self, page, scroll_count: int = 10) -> str:
        """Scroll down the page to load more content."""
        for i in range(scroll_count):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)
            # Check if "load more" button exists
            try:
                load_more = page.query_selector(
                    "button:has-text('Load'), button:has-text('More'), "
                    "button:has-text('Show'), a:has-text('Load more')"
                )
                if load_more and load_more.is_visible():
                    load_more.click()
                    page.wait_for_timeout(2000)
            except:
                pass
        return page.content()

    def _parse_page(self, html: str) -> list[JobListing]:
        soup = BeautifulSoup(html, "html.parser")
        listings = []
        job_cards_found = set()
        all_links = soup.find_all("a", href=True)

        for link in all_links:
            href = link.get("href", "")
            text = link.get_text(strip=True)

            if not text or len(text) < 3:
                continue
            if href in ("#", "/", "./", "./jobs", "./investors", "./news", "./subscribe"):
                continue

            if self._looks_like_job_link(href, text):
                url = href if href.startswith("http") else urljoin(BASE_URL, href)
                if url not in job_cards_found:
                    job_cards_found.add(url)
                    
                    # Parse title and company from the link text
                    # startups.gallery often concatenates: "Job TitleCompany Name · Location · Date"
                    title, company, location = self._parse_link_text(text)
                    
                    # If we couldn't parse company from text, try parent
                    if not company:
                        company, loc_parent, description = self._get_context_from_parent(link)
                        if not location:
                            location = loc_parent
                    else:
                        _, _, description = self._get_context_from_parent(link)
                    
                    listings.append(JobListing(
                        title=title,
                        company=company,
                        location=location,
                        description=description,
                        url=url,
                        source="startups.gallery",
                    ))

        # Fallback: structured cards
        if len(listings) < 5:
            card_listings = self._parse_structured_cards(soup)
            for listing in card_listings:
                if listing.url not in job_cards_found:
                    job_cards_found.add(listing.url)
                    listings.append(listing)

        # Last fallback: text pattern matching
        if len(listings) < 5:
            text_listings = self._parse_text_blocks(soup)
            for listing in text_listings:
                if listing.url not in job_cards_found:
                    job_cards_found.add(listing.url)
                    listings.append(listing)

        return listings

    def _parse_link_text(self, text: str) -> tuple[str, str, str]:
        """Parse job title, company, and location from concatenated link text.
        
        startups.gallery often has text like:
        "Operations AssociateCocoon · Remote, Arizona · Posted on Feb 7, 2026"
        "Chief of StaffHedra · San Francisco · Posted on Jan 30, 2026"
        "Revenue Strategy & Operations ManagerDecagon · New York City · Posted on Feb 6, 2026"
        """
        title = text
        company = ""
        location = ""
        
        # Split on · (middle dot) separator
        parts = re.split(r'\s*·\s*', text)
        
        if len(parts) >= 2:
            # First part is "Job TitleCompanyName"
            title_company = parts[0].strip()
            
            # Location is typically the second part
            if len(parts) >= 2:
                loc_candidate = parts[1].strip()
                if not loc_candidate.startswith("Posted"):
                    location = loc_candidate
            
            # Try to split title from company name
            # Company names typically start with a capital letter after lowercase
            # e.g. "Operations AssociateCocoon" -> title="Operations Associate", company="Cocoon"
            # e.g. "Chief of StaffHedra" -> title="Chief of Staff", company="Hedra"
            # Look for a capital letter that follows a lowercase letter (camelCase boundary)
            match = re.search(r'([a-z\))])([A-Z][a-zA-Z])', title_company)
            if match:
                split_pos = match.start() + 1
                title = title_company[:split_pos].strip()
                company = title_company[split_pos:].strip()
            else:
                title = title_company
        
        # Clean up "Posted on..." from location
        location = re.sub(r'\s*Posted on.*$', '', location).strip()
        
        return title, company, location

    def _looks_like_job_link(self, href: str, text: str) -> bool:
        """Check if a link looks like it leads to a job listing."""
        text_lower = text.lower()
        href_lower = href.lower()

        # Reject startup company description cards (from location/city pages)
        # These look like "Next-gen ops platform for the AI era.Productivity"
        # or "Business banking for internet entrepreneurs.Fintech"
        industry_tags = [
            ".productivity", ".fintech", ".ai", ".devtools", ".analytics",
            ".web3", ".healthcare", ".cybersecurity", ".hr & recruiting",
            ".construction", ".education", ".real estate",
        ]
        if any(tag in text_lower for tag in industry_tags):
            return False

        # Also reject if text contains no spaces (likely a mangled company name)
        if " " not in text.strip():
            return False

        # External job platform links
        job_platforms = [
            "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
            "jobs.lever", "boards.greenhouse", "apply.workable",
            "careers.", "jobs.", "/careers", "/jobs", "/job/",
        ]
        if any(platform in href_lower for platform in job_platforms):
            return True

        # Internal job detail pages
        if re.search(r'/jobs?/', href_lower) and len(href) > 10:
            return True

        # Text contains job title keywords
        job_keywords = [
            "operations", "ops", "strategy", "chief of staff",
            "analyst", "associate", "coordinator", "manager",
            "business", "finance", "growth", "revenue",
            "head of", "director", "lead",
        ]
        if any(kw in text_lower for kw in job_keywords):
            return True

        return False

    def _get_context_from_parent(self, element) -> tuple[str, str, str]:
        """Walk up the DOM to find company name, location, and description."""
        company = ""
        location = ""
        description = ""

        parent = element
        for _ in range(6):
            if parent.parent:
                parent = parent.parent
                text = parent.get_text(" ", strip=True)
                if len(text) > 50:
                    break

        if parent:
            full_text = parent.get_text(" ", strip=True)

            # Company name
            company_match = re.search(r'^([A-Z][A-Za-z0-9\s&.-]+?)(?:\s*[·•|—\-])', full_text)
            if company_match:
                company = company_match.group(1).strip()

            # Location
            loc_patterns = [
                r'((?:Los Angeles|San Francisco|New York|Brooklyn|Manhattan|LA|SF|NYC|Bay Area)[^·•|]*)',
                r'(?:Based in|Located in|HQ:?)\s*([^·•|\n]+)',
                r'(Remote|Onsite|Hybrid)',
            ]
            for pattern in loc_patterns:
                match = re.search(pattern, full_text, re.IGNORECASE)
                if match:
                    location = match.group(1).strip()
                    break

            description = full_text[:500]

        return company, location, description

    def _parse_structured_cards(self, soup) -> list[JobListing]:
        """Try to parse structured card elements."""
        listings = []
        selectors = [
            "[class*='job']", "[class*='listing']", "[class*='card']",
            "[class*='post']", "[class*='item']", "article", "li",
        ]

        for selector in selectors:
            cards = soup.select(selector)
            for card in cards:
                text = card.get_text(" ", strip=True)
                if len(text) < 20 or len(text) > 2000:
                    continue

                text_lower = text.lower()
                if not any(kw in text_lower for kw in ["apply", "role", "hiring", "operations", "ops", "strategy", "analyst"]):
                    continue

                link = card.find("a", href=True)
                if not link:
                    continue

                href = link.get("href", "")
                url = href if href.startswith("http") else urljoin(BASE_URL, href)
                title = link.get_text(strip=True)

                if title and len(title) > 3:
                    company, location, description = self._get_context_from_parent(link)
                    listings.append(JobListing(
                        title=title,
                        company=company,
                        location=location,
                        description=description or text[:500],
                        url=url,
                        source="startups.gallery",
                    ))

            if listings:
                break

        return listings

    def _parse_text_blocks(self, soup) -> list[JobListing]:
        """Last resort: parse visible text for job-like content."""
        listings = []
        body = soup.find("body")
        if not body:
            return listings

        for link in body.find_all("a", href=True):
            text = link.get_text(strip=True)
            href = link.get("href", "")

            if len(text) < 5 or not href:
                continue

            title_patterns = [
                r'(?:head|director|vp|chief|lead|senior|junior|associate|manager|coordinator|analyst)\s+(?:of\s+)?(?:operations|strategy|growth|finance|business|revenue)',
                r'(?:operations|strategy|growth|business|revenue)\s+(?:lead|manager|associate|analyst|coordinator|director)',
                r'chief\s+of\s+staff',
            ]

            for pattern in title_patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    url = href if href.startswith("http") else urljoin(BASE_URL, href)
                    company, location, desc = self._get_context_from_parent(link)
                    listings.append(JobListing(
                        title=text,
                        company=company,
                        location=location,
                        description=desc,
                        url=url,
                        source="startups.gallery",
                    ))
                    break

        return listings
