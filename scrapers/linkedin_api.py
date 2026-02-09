"""
linkedin_api.py — LinkedIn job search via SerpAPI.
No direct scraping — uses SerpAPI's Google Jobs endpoint which includes LinkedIn results.
"""

from typing import Optional

from models import JobListing
from scrapers.base import BaseScraper
from config import SERPAPI_KEY, TARGET_ROLES
from monitoring import get_logger

logger = get_logger("scrapers.linkedin_api")

SERPAPI_URL = "https://serpapi.com/search.json"

# Batched search queries to minimize API calls
# Combine multiple roles and locations with OR operators
SEARCH_QUERIES = [
    '"business operations" OR "biz ops" OR "operations associate" startup',
    '"chief of staff" OR "strategy operations" OR "strategy & operations" startup',
    '"growth operations" OR "revenue operations" OR "GTM operations" startup',
    '"operations analyst" OR "operations manager" startup entry level',
]

LOCATIONS = [
    "Los Angeles, California",
    "San Francisco Bay Area, California",
    "New York, New York",
]


class LinkedInAPIScraper(BaseScraper):
    """LinkedIn job search via SerpAPI's Google Jobs endpoint."""

    def __init__(self):
        super().__init__(
            name="LinkedIn (via SerpAPI)",
            delay_min=0.5,
            delay_max=1.0,
            max_pages=10,
            max_retries=2,
        )

    def _get_base_url(self) -> str:
        return "https://serpapi.com"

    def scrape(self) -> list[JobListing]:
        """Search for jobs via SerpAPI."""
        if not SERPAPI_KEY:
            logger.warning("SERPAPI_KEY not set — skipping LinkedIn scraper")
            return []

        logger.info("Starting LinkedIn (SerpAPI) scrape")
        all_listings = []

        for query in SEARCH_QUERIES:
            for location in LOCATIONS:
                try:
                    listings = self._search(query, location)
                    all_listings.extend(listings)
                    self._rate_limit()
                except Exception as e:
                    logger.warning(f"SerpAPI search failed for '{query}' in {location}: {e}")
                    continue

        logger.info(f"LinkedIn (SerpAPI) scrape complete: {len(all_listings)} listings found")
        return all_listings

    def _search(self, query: str, location: str) -> list[JobListing]:
        """Execute a single SerpAPI search."""
        import httpx

        params = {
            "engine": "google_jobs",
            "q": query,
            "location": location,
            "api_key": SERPAPI_KEY,
            "hl": "en",
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(SERPAPI_URL, params=params)
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            logger.error(f"SerpAPI request failed: {e}")
            return []

        jobs_results = data.get("jobs_results", [])
        listings = []

        for job in jobs_results:
            listing = self._parse_result(job, location)
            if listing:
                listings.append(listing)

        logger.info(f"SerpAPI '{query[:40]}...' in {location}: {len(listings)} results")
        return listings

    def _parse_result(self, job: dict, search_location: str) -> Optional[JobListing]:
        """Parse a SerpAPI Google Jobs result into a JobListing."""
        title = job.get("title", "")
        company = job.get("company_name", "")
        location = job.get("location", search_location)

        if not title or not company:
            return None

        # Description
        description = job.get("description", "")

        # URL — SerpAPI provides apply links
        apply_options = job.get("apply_options", [])
        url = ""
        for option in apply_options:
            link = option.get("link", "")
            # Prefer LinkedIn links
            if "linkedin.com" in link:
                url = link
                break
            if not url:
                url = link

        if not url:
            url = job.get("share_link", job.get("job_id", ""))

        # Salary
        salary_info = job.get("detected_extensions", {})
        salary_min = None
        salary_max = None
        
        salary_text = salary_info.get("salary", "")
        if salary_text:
            salary_min, salary_max = self._parse_salary(salary_text)

        # Experience / qualifications
        qualifications = salary_info.get("qualifications", "")
        schedule = salary_info.get("schedule_type", "")

        # Date posted
        date_posted = salary_info.get("posted_at", job.get("detected_extensions", {}).get("posted_at", ""))

        return JobListing(
            title=title,
            company=company,
            location=location,
            description=description,
            salary_min=salary_min,
            salary_max=salary_max,
            experience_required=qualifications if qualifications else None,
            url=url,
            source="LinkedIn (SerpAPI)",
            date_posted=date_posted,
        )

    def _parse_salary(self, salary_text: str) -> tuple[Optional[float], Optional[float]]:
        """Parse salary text from SerpAPI results."""
        import re

        if not salary_text:
            return None, None

        # Extract dollar amounts
        amounts = re.findall(r'\$?([\d,]+(?:\.\d+)?)\s*[kK]?', salary_text)

        parsed = []
        for amount in amounts:
            num = float(amount.replace(",", ""))
            if num < 1000:
                num *= 1000
            if 20000 <= num <= 500000:
                parsed.append(num)

        # Check if it's hourly (skip if so)
        if "hour" in salary_text.lower() or "/hr" in salary_text.lower():
            return None, None

        if len(parsed) >= 2:
            return min(parsed), max(parsed)
        elif len(parsed) == 1:
            return parsed[0], None

        return None, None
