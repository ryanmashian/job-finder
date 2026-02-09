"""
indeed_api.py — Indeed job search via SerpAPI.
Uses the same Google Jobs endpoint which aggregates Indeed listings.
"""

from typing import Optional

from models import JobListing
from scrapers.base import BaseScraper
from config import SERPAPI_KEY
from monitoring import get_logger

logger = get_logger("scrapers.indeed_api")

SERPAPI_URL = "https://serpapi.com/search.json"

# Indeed-specific queries (SerpAPI Google Jobs captures Indeed listings)
# These are separate from LinkedIn to avoid duplicate API calls
SEARCH_QUERIES = [
    '"operations associate" OR "operations analyst" startup entry level',
    '"business operations" startup junior',
    '"chief of staff" startup early stage',
    '"finance and operations" OR "finance & operations" startup',
]

LOCATIONS = [
    "Los Angeles, California",
    "San Francisco, California",
    "New York, New York",
]


class IndeedAPIScraper(BaseScraper):
    """Indeed job search via SerpAPI's Google Jobs endpoint."""

    def __init__(self):
        super().__init__(
            name="Indeed (via SerpAPI)",
            delay_min=0.5,
            delay_max=1.0,
            max_pages=10,
            max_retries=2,
        )

    def _get_base_url(self) -> str:
        return "https://serpapi.com"

    def scrape(self) -> list[JobListing]:
        """Search for jobs via SerpAPI targeting Indeed listings."""
        if not SERPAPI_KEY:
            logger.warning("SERPAPI_KEY not set — skipping Indeed scraper")
            return []

        logger.info("Starting Indeed (SerpAPI) scrape")
        all_listings = []

        for query in SEARCH_QUERIES:
            for location in LOCATIONS:
                try:
                    listings = self._search(query, location)
                    all_listings.extend(listings)
                    self._rate_limit()
                except Exception as e:
                    logger.warning(f"SerpAPI (Indeed) search failed for '{query}' in {location}: {e}")
                    continue

        logger.info(f"Indeed (SerpAPI) scrape complete: {len(all_listings)} listings found")
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
            "chips": "date_posted:week",  # Focus on recent postings
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(SERPAPI_URL, params=params)
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            logger.error(f"SerpAPI (Indeed) request failed: {e}")
            return []

        jobs_results = data.get("jobs_results", [])
        listings = []

        for job in jobs_results:
            listing = self._parse_result(job, location)
            if listing:
                listings.append(listing)

        logger.info(f"SerpAPI (Indeed) '{query[:40]}...' in {location}: {len(listings)} results")
        return listings

    def _parse_result(self, job: dict, search_location: str) -> Optional[JobListing]:
        """Parse a SerpAPI result, prioritizing Indeed apply links."""
        title = job.get("title", "")
        company = job.get("company_name", "")
        location = job.get("location", search_location)

        if not title or not company:
            return None

        description = job.get("description", "")

        # URL — prefer Indeed links
        apply_options = job.get("apply_options", [])
        url = ""
        for option in apply_options:
            link = option.get("link", "")
            if "indeed.com" in link:
                url = link
                break
            if not url:
                url = link

        if not url:
            url = job.get("share_link", "")

        # Salary
        salary_info = job.get("detected_extensions", {})
        salary_min, salary_max = None, None
        salary_text = salary_info.get("salary", "")
        if salary_text:
            salary_min, salary_max = self._parse_salary(salary_text)

        # Date posted
        date_posted = salary_info.get("posted_at", "")

        return JobListing(
            title=title,
            company=company,
            location=location,
            description=description,
            salary_min=salary_min,
            salary_max=salary_max,
            experience_required=salary_info.get("qualifications", None),
            url=url,
            source="Indeed (SerpAPI)",
            date_posted=date_posted,
        )

    def _parse_salary(self, salary_text: str) -> tuple[Optional[float], Optional[float]]:
        """Parse salary text."""
        import re

        if not salary_text or "hour" in salary_text.lower():
            return None, None

        amounts = re.findall(r'\$?([\d,]+(?:\.\d+)?)\s*[kK]?', salary_text)
        parsed = []
        for amount in amounts:
            num = float(amount.replace(",", ""))
            if num < 1000:
                num *= 1000
            if 20000 <= num <= 500000:
                parsed.append(num)

        if len(parsed) >= 2:
            return min(parsed), max(parsed)
        elif len(parsed) == 1:
            return parsed[0], None
        return None, None
