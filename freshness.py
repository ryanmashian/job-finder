"""
freshness.py — Assigns freshness indicators to job listings based on posting date.

🟢 Fresh (0-7 days): High priority
🟡 Aging (8-14 days): Still worth applying
🔴 Stale (15-21 days): Apply immediately or skip
⚫ Expired risk (21+ days): Likely filled
"""

from datetime import datetime, timedelta
from typing import Optional

from models import ScoredJob
from config import FRESHNESS_THRESHOLDS
from monitoring import get_logger

logger = get_logger("freshness")


def assign_freshness(scored_jobs: list[ScoredJob]) -> list[ScoredJob]:
    """Assign freshness indicators to all scored jobs."""
    for job in scored_jobs:
        job.freshness = _calculate_freshness(job.listing.date_posted)
    
    # Log distribution
    dist = {}
    for job in scored_jobs:
        dist[job.freshness] = dist.get(job.freshness, 0) + 1
    logger.info(f"Freshness distribution: {dist}")
    
    return scored_jobs


def _calculate_freshness(date_posted: Optional[str]) -> str:
    """
    Calculate freshness based on days since posting.
    Returns: "green", "yellow", "red", "black", or "unknown"
    """
    if not date_posted:
        return "unknown"
    
    try:
        # Try parsing common date formats
        posted_date = _parse_date(date_posted)
        if posted_date is None:
            return "unknown"
        
        days_old = (datetime.now() - posted_date).days
        
        if days_old < 0:
            # Future date — likely a parsing error
            return "unknown"
        elif days_old <= FRESHNESS_THRESHOLDS["green_days"]:
            return "green"
        elif days_old <= FRESHNESS_THRESHOLDS["yellow_days"]:
            return "yellow"
        elif days_old <= FRESHNESS_THRESHOLDS["red_days"]:
            return "red"
        else:
            return "black"
    except Exception:
        return "unknown"


def _parse_date(date_str: str) -> Optional[datetime]:
    """Try to parse a date string in various formats."""
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%Y-%m-%d %H:%M:%S",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    
    # Handle relative dates like "3 days ago", "1 week ago"
    return _parse_relative_date(date_str)


def _parse_relative_date(date_str: str) -> Optional[datetime]:
    """Parse relative date strings like '3 days ago', '1 week ago'."""
    import re
    
    date_str = date_str.lower().strip()
    now = datetime.now()
    
    # "X days ago"
    match = re.search(r'(\d+)\s*days?\s*ago', date_str)
    if match:
        return now - timedelta(days=int(match.group(1)))
    
    # "X weeks ago"
    match = re.search(r'(\d+)\s*weeks?\s*ago', date_str)
    if match:
        return now - timedelta(weeks=int(match.group(1)))
    
    # "X hours ago"
    match = re.search(r'(\d+)\s*hours?\s*ago', date_str)
    if match:
        return now - timedelta(hours=int(match.group(1)))
    
    # "today"
    if "today" in date_str or "just posted" in date_str:
        return now
    
    # "yesterday"
    if "yesterday" in date_str:
        return now - timedelta(days=1)
    
    # "X months ago"
    match = re.search(r'(\d+)\s*months?\s*ago', date_str)
    if match:
        return now - timedelta(days=int(match.group(1)) * 30)
    
    return None


def freshness_to_emoji(freshness: str) -> str:
    """Convert freshness string to emoji for Google Sheets display."""
    mapping = {
        "green": "🟢",
        "yellow": "🟡",
        "red": "🔴",
        "black": "⚫",
        "unknown": "❓",
    }
    return mapping.get(freshness, "❓")
