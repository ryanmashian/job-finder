"""
pre_filter.py — Lightweight keyword pre-filter applied BEFORE sending to Claude API.
Eliminates obviously irrelevant jobs to save API cost.

Must match at least 1 of 3 keyword categories to proceed to scoring.
(Loosened from 2-of-3 to catch more relevant listings.)
"""

from models import JobListing
from config import SIGNAL_TOOLS, SIGNAL_THEMES, SIGNAL_RESPONSIBILITIES
from monitoring import get_logger

logger = get_logger("pre_filter")

# Title-specific keywords (Category A)
TITLE_KEYWORDS = [
    "operations", "ops", "strategy", "chief of staff",
    "business associate", "gtm", "growth", "revenue",
    "biz ops", "revops", "finance & operations",
    "finance and operations", "startup operations",
    "associate", "analyst", "coordinator",
]

# Minimum categories required to pass (1 = loose, 2 = strict)
MIN_CATEGORIES = 1


def apply_keyword_pre_filter(listings: list[JobListing]) -> list[JobListing]:
    """
    Filter listings by keyword relevance.
    Must match at least MIN_CATEGORIES of 3 categories (title, skills/tools, themes).
    """
    initial_count = len(listings)
    results = []
    
    for listing in listings:
        categories_matched = _count_category_matches(listing)
        if categories_matched >= MIN_CATEGORIES:
            results.append(listing)
    
    filtered = initial_count - len(results)
    logger.info(
        f"Keyword pre-filter: {initial_count} → {len(results)} "
        f"({filtered} below relevance threshold)"
    )
    
    return results


def _count_category_matches(listing: JobListing) -> int:
    """Count how many keyword categories this listing matches (0-3)."""
    title = (listing.title or "").lower()
    description = (listing.description or "").lower()
    full_text = f"{title} {description}"
    
    categories = 0
    
    # Category A: Title relevance
    if _has_any_keyword(title, TITLE_KEYWORDS):
        categories += 1
    
    # Category B: Skills/Tools
    if _has_any_keyword(full_text, SIGNAL_TOOLS):
        categories += 1
    
    # Category C: Themes + Responsibilities
    theme_and_resp = SIGNAL_THEMES + SIGNAL_RESPONSIBILITIES
    if _has_any_keyword(full_text, theme_and_resp):
        categories += 1
    
    return categories


def _has_any_keyword(text: str, keywords: list[str]) -> bool:
    """Check if any keyword appears in the text."""
    for keyword in keywords:
        if keyword in text:
            return True
    return False
