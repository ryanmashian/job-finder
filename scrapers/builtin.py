"""
builtin.py — Scraper for Built In using Playwright.
Parses the actual page structure: company name from link text, job title from h2 a,
salary, experience level, and location from structured elements.
"""

import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from models import JobListing
from scrapers.base import BaseScraper
from config import RATE_LIMITS
from monitoring import get_logger

logger = get_logger("scrapers.builtin")

# More search terms to cast a wider net
SEARCH_URLS = [
    # Operations searches per city
    "https://builtin.com/jobs?search=operations&location=los-angeles",
    "https://builtin.com/jobs?search=operations&location=san-francisco",
    "https://builtin.com/jobs?search=operations&location=new-york",
    # Chief of staff
    "https://builtin.com/jobs?search=chief+of+staff&location=los-angeles",
    "https://builtin.com/jobs?search=chief+of+staff&location=san-francisco",
    "https://builtin.com/jobs?search=chief+of+staff&location=new-york",
    # Strategy
    "https://builtin.com/jobs?search=strategy+operations&location=los-angeles",
    "https://builtin.com/jobs?search=strategy+operations&location=san-francisco",
    "https://builtin.com/jobs?search=strategy+operations&location=new-york",
    # Biz ops / business operations
    "https://builtin.com/jobs?search=business+operations&location=los-angeles",
    "https://builtin.com/jobs?search=business+operations&location=san-francisco",
    "https://builtin.com/jobs?search=business+operations&location=new-york",
    # Revenue operations
    "https://builtin.com/jobs?search=revenue+operations&location=los-angeles",
    "https://builtin.com/jobs?search=revenue+operations&location=san-francisco",
    "https://builtin.com/jobs?search=revenue+operations&location=new-york",
]


class BuiltInScraper(BaseScraper):
    def __init__(self):
        limits = RATE_LIMITS.get("builtin", {})
        super().__init__(
            name="Built In",
            delay_min=limits.get("delay_min", 2.0),
            delay_max=limits.get("delay_max", 4.0),
            max_pages=limits.get("max_pages", 30),
            max_retries=limits.get("max_retries", 3),
        )

    def _get_base_url(self) -> str:
        return "https://builtin.com"

    def scrape(self) -> list[JobListing]:
        logger.info("Starting Built In scrape")
        all_listings = []
        seen_urls = set()
        max_pages_per_search = 4  # 25 per page × 4 = up to 100 per search

        for base_url in SEARCH_URLS:
            consecutive_zero = 0
            for page_num in range(1, max_pages_per_search + 1):
                try:
                    # Built In uses &page=N for pagination
                    if page_num == 1:
                        url = base_url
                    else:
                        separator = "&" if "?" in base_url else "?"
                        url = f"{base_url}{separator}page={page_num}"

                    logger.info(f"Fetching {url}")
                    html = self._scroll_and_fetch(url, scroll_count=3, wait_seconds=2.0)
                    listings = self._parse_page(html)

                    # Deduplicate across search terms
                    new = 0
                    for listing in listings:
                        if listing.url not in seen_urls:
                            seen_urls.add(listing.url)
                            all_listings.append(listing)
                            new += 1

                    if new == 0:
                        consecutive_zero += 1
                        if page_num == 1:
                            logger.info(f"Built In: page 1 had 0 new results for {base_url}, skipping remaining pages for this search")
                            break
                        if consecutive_zero >= 2:
                            logger.info(f"Built In: {consecutive_zero} consecutive pages with 0 new results, skipping remaining pages for this search")
                            break
                    else:
                        consecutive_zero = 0

                    logger.info(f"Built In: found {len(listings)} listings ({new} new) from {url}")
                    self._rate_limit()

                    # If we got fewer than 20 listings, no more pages to scrape
                    if len(listings) < 20:
                        break

                except Exception as e:
                    logger.warning(f"Built In scrape failed for {url}: {e}")
                    break  # Move to next search term if a page fails

        logger.info(f"Built In scrape complete: {len(all_listings)} unique listings found")
        return all_listings

    def _parse_page(self, html: str) -> list[JobListing]:
        """Parse Built In job listings from HTML.
        
        Structure from actual site:
        - Company name: <a> link to /company/xxx with text like "Wells Fargo"
        - Job title: <h2><a href="/job/xxx">Title</a></h2>
        - Location: text like "Hybrid", "Long Beach, CA, USA"
        - Salary: text like "23-30 Hourly" or "92K-164K Annually"
        - Experience: text like "Junior", "Mid level", "Senior level", "Entry level"
        - Industry: text like "Fintech • Financial Services"
        - Description: summary paragraph
        """
        soup = BeautifulSoup(html, "html.parser")
        listings = []

        # Find all job links — they follow pattern /job/slug/id
        job_links = soup.find_all("a", href=re.compile(r"^/job/"))

        seen_hrefs = set()
        for link in job_links:
            href = link.get("href", "")
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            title = link.get_text(strip=True)
            if not title or len(title) < 3:
                continue

            url = urljoin("https://builtin.com", href)

            # Walk up to find the containing card
            card = link
            for _ in range(8):  # Walk up to 8 levels
                if card.parent:
                    card = card.parent
                    # Stop when we find a large enough container
                    card_text = card.get_text(" ", strip=True)
                    if len(card_text) > 100:
                        break

            # Extract company name — look for /company/ link with text (not image)
            company = ""
            company_links = card.find_all("a", href=re.compile(r"^/company/"))
            for cl in company_links:
                # Skip links that only contain images
                if cl.find("img"):
                    continue
                text = cl.get_text(strip=True)
                if text and len(text) > 1:
                    company = text
                    # Remove "Logo" suffix if present
                    company = re.sub(r'\s*Logo\s*$', '', company)
                    break
            
            # Fallback: if no text-only link, try any company link
            if not company and company_links:
                for cl in company_links:
                    text = cl.get_text(strip=True)
                    if text and len(text) > 1:
                        company = re.sub(r'\s*Logo\s*$', '', text)
                        break

            # Extract location
            location = self._extract_location(card)

            # Extract salary
            salary_min, salary_max = self._extract_salary(card)

            # Extract experience level
            experience = self._extract_experience(card)

            # Extract description
            description = self._extract_description(card)

            # Extract industry
            industry = self._extract_industry(card)

            listings.append(JobListing(
                title=title,
                company=company,
                location=location,
                description=description,
                salary_min=salary_min,
                salary_max=salary_max,
                experience_required=experience,
                company_industry=industry,
                url=url,
                source="Built In",
            ))

        return listings

    def _extract_location(self, card) -> str:
        """Extract location from card text."""
        text = card.get_text(" ", strip=True)
        
        # Look for city, state patterns
        loc_patterns = [
            r'((?:Los Angeles|Long Beach|Santa Monica|Beverly Hills|Culver City|Playa Vista|El Segundo|Venice|Marina del Rey)[,\s]*(?:CA|California)?[,\s]*(?:USA)?)',
            r'((?:San Francisco|Palo Alto|Mountain View|Menlo Park|Sunnyvale|Oakland|San Jose|Redwood City|Berkeley)[,\s]*(?:CA|California)?[,\s]*(?:USA)?)',
            r'((?:New York|Brooklyn|Manhattan)[,\s]*(?:NY|New York)?[,\s]*(?:USA)?)',
        ]
        
        for pattern in loc_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip().rstrip(",")
        
        # Check for Remote/Hybrid
        if "Remote" in text:
            return "Remote"
        if "Hybrid" in text:
            return "Hybrid"
            
        return ""

    def _extract_salary(self, card) -> tuple[Optional[float], Optional[float]]:
        """Extract salary from card text like '92K-164K Annually' or '23-30 Hourly'."""
        text = card.get_text(" ", strip=True)
        
        # Annual salary: "92K-164K Annually"
        annual_match = re.search(r'(\d+)[kK]\s*[-–]\s*(\d+)[kK]\s*(?:Annually|Annual|/yr)', text)
        if annual_match:
            return float(annual_match.group(1)) * 1000, float(annual_match.group(2)) * 1000
        
        # Single annual: "200K-200K Annually" or "150K Annually"
        single_annual = re.search(r'(\d+)[kK]\s*(?:Annually|Annual|/yr)', text)
        if single_annual:
            val = float(single_annual.group(1)) * 1000
            return val, val
        
        # Hourly — skip (not relevant for our salary filter)
        if "Hourly" in text:
            hourly_match = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*Hourly', text)
            if hourly_match:
                low = float(hourly_match.group(1)) * 2080  # Convert to annual
                high = float(hourly_match.group(2)) * 2080
                return low, high
        
        return None, None

    def _extract_experience(self, card) -> Optional[str]:
        """Extract experience level."""
        text = card.get_text(" ", strip=True)
        levels = ["Entry level", "Junior", "Mid level", "Senior level", "Expert/Leader"]
        for level in levels:
            if level in text:
                return level
        return None

    def _extract_description(self, card) -> str:
        """Extract the job description summary."""
        # Look for longer text blocks that aren't titles or metadata
        paragraphs = card.find_all(["p", "div"])
        for p in paragraphs:
            text = p.get_text(strip=True)
            if len(text) > 80 and not text.startswith("Top Skills"):
                return text[:500]
        return card.get_text(" ", strip=True)[:500]

    def _extract_industry(self, card) -> Optional[str]:
        """Extract industry tags like 'Fintech • Financial Services'."""
        text = card.get_text(" ", strip=True)
        # Look for bullet-separated industry strings
        industry_match = re.search(r'((?:\w[\w\s]+•\s*)+\w[\w\s]+)', text)
        if industry_match:
            return industry_match.group(1).strip()
        return None
