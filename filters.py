"""
filters.py — Hard pass/fail filters applied before scoring.
If a job fails ANY of these, it's excluded entirely.
"""

import re
from typing import Optional

from models import JobListing
from config import (
    LOCATION_ALIASES,
    EXPERIENCE_MAX_YEARS,
    SALARY_MIN,
    EXCLUDED_INDUSTRIES,
)
from monitoring import get_logger

logger = get_logger("filters")


def apply_hard_filters(listings: list[JobListing]) -> list[JobListing]:
    """
    Apply all hard filters sequentially.
    Returns only listings that pass ALL filters.
    """
    initial_count = len(listings)
    
    results = []
    filter_stats = {
        "location": 0,
        "experience": 0,
        "salary": 0,
        "industry": 0,
    }
    
    for listing in listings:
        if not _check_location(listing):
            filter_stats["location"] += 1
            continue
        if not _check_experience(listing):
            filter_stats["experience"] += 1
            continue
        if not _check_salary(listing):
            filter_stats["salary"] += 1
            continue
        if not _check_industry_exclusion(listing):
            filter_stats["industry"] += 1
            continue
        results.append(listing)
    
    passed = len(results)
    logger.info(
        f"Hard filters: {initial_count} → {passed} "
        f"(location: -{filter_stats['location']}, "
        f"experience: -{filter_stats['experience']}, "
        f"salary: -{filter_stats['salary']}, "
        f"industry: -{filter_stats['industry']})"
    )
    
    return results


def _check_location(listing: JobListing) -> bool:
    """
    Check if the job is in an accepted location.
    Must mention at least one location alias. Remote is always accepted:
    if location, description, or title contains "remote", return True.
    """
    location = (listing.location or "").lower()
    description = (listing.description or "").lower()
    title = (listing.title or "").lower()
    if "remote" in location or "remote" in description or "remote" in title:
        return True
    text = location + " " + description
    for alias in LOCATION_ALIASES:
        if alias in text:
            return True
    return False


def _check_experience(listing: JobListing) -> bool:
    """
    Check if the experience requirement is within range (0-3 years).
    If no experience is specified, pass (don't penalize).
    """
    # Check the explicit experience field
    exp_text = listing.experience_required or ""
    
    # Also scan the description for experience mentions
    desc = listing.description or ""
    full_text = f"{exp_text} {desc}".lower()
    
    # Parse years of experience requirements
    years = _extract_years(full_text)
    
    if years is None:
        # No experience requirement found — pass
        return True
    
    return years <= EXPERIENCE_MAX_YEARS


def _extract_years(text: str) -> Optional[int]:
    """
    Extract the minimum years of experience required from text.
    Returns None if no requirement is found.
    """
    # Patterns like "5+ years", "5-7 years", "minimum 5 years", "at least 5 years"
    patterns = [
        r'(\d+)\+?\s*(?:years?|yrs?)\s*(?:of\s+)?(?:experience|exp)',
        r'(\d+)\s*-\s*\d+\s*(?:years?|yrs?)\s*(?:of\s+)?(?:experience|exp)',
        r'(?:minimum|min|at least)\s*(\d+)\s*(?:years?|yrs?)',
        r'(\d+)\+?\s*(?:years?|yrs?)\s*(?:in|of|working)',
        r'(?:requires?|requiring)\s*(\d+)\+?\s*(?:years?|yrs?)',
    ]
    
    min_years = None
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            years = int(match)
            # Sanity check — ignore numbers that are clearly not years (e.g., salary figures)
            if 0 <= years <= 20:
                if min_years is None or years < min_years:
                    min_years = years
    
    return min_years


def _check_salary(listing: JobListing) -> bool:
    """
    Check if the salary meets the minimum threshold.
    If no salary is listed, pass (don't penalize).
    """
    if listing.salary_min is None and listing.salary_max is None:
        return True
    
    # If we have a max salary, use it as the reference
    # (a range of $60K-$80K should pass because the role COULD pay $80K)
    if listing.salary_max is not None:
        return listing.salary_max >= SALARY_MIN
    
    # If only min is available
    if listing.salary_min is not None:
        return listing.salary_min >= SALARY_MIN
    
    return True


# Tiered industry exclusion: different keyword sets per field to avoid false positives.
INDUSTRY_TITLE_KEYWORDS = [
    "healthcare", "healthtech", "biotech", "biotechnology",
    "pharmaceutical", "pharma", "clinical", "hospital", "nursing",
]
INDUSTRY_COMPANY_KEYWORDS = [
    "hospital", "pharmaceutical", "pharma", "biotech", "biotechnology",
    "clinic ", "clinical ",
]
INDUSTRY_DESCRIPTION_PHRASES = [
    "healthcare industry", "healthtech", "health tech", "biotech company",
    "biotechnology", "pharmaceutical", "hospital system", "clinical trials",
    "clinical research", "hipaa", "patient care", "patient outcomes",
]


def _check_industry_exclusion(listing: JobListing) -> bool:
    """
    Reject if healthcare/healthtech/biotech signals appear, using a tiered approach:
    - Industry field: all excluded keywords (most reliable).
    - Title: only strong keywords.
    - Company name: only very strong keywords.
    - Description: only multi-word phrases (avoids "patient", "health" in generic contexts).
    """
    industry = (listing.company_industry or "").lower()
    title = (listing.title or "").lower()
    company = (listing.company or "").lower()
    description = (listing.description or "").lower()

    for keyword in EXCLUDED_INDUSTRIES:
        if keyword in industry:
            return False
    for keyword in INDUSTRY_TITLE_KEYWORDS:
        if keyword in title:
            return False
    for keyword in INDUSTRY_COMPANY_KEYWORDS:
        if keyword in company:
            return False
    for phrase in INDUSTRY_DESCRIPTION_PHRASES:
        if phrase in description:
            return False
    return True
