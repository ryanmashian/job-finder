"""
listing_health.py — Checks whether job listing URLs are still live.
Marks expired/removed listings so you don't waste time applying to dead jobs.
"""

import time
import random

import httpx

from database import get_urls_to_health_check, mark_url_dead
from config import LISTING_HEALTH
from monitoring import get_logger

logger = get_logger("listing_health")

# Patterns that indicate a job has been removed
EXPIRED_PATTERNS = [
    "this job is no longer available",
    "position has been filled",
    "this listing has expired",
    "job not found",
    "page not found",
    "no longer accepting applications",
    "this position is closed",
    "job has been removed",
    "this role has been filled",
]


def check_listing_health() -> int:
    """
    Check URLs of open jobs to see if they're still live.
    Returns count of newly expired listings.
    """
    max_checks = LISTING_HEALTH["max_checks_per_run"]
    delay = LISTING_HEALTH["request_delay"]
    
    jobs_to_check = get_urls_to_health_check(max_checks=max_checks)
    
    if not jobs_to_check:
        logger.info("No listings to health-check")
        return 0
    
    logger.info(f"Checking {len(jobs_to_check)} listing URLs for expiry")
    
    expired_count = 0
    
    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        for job in jobs_to_check:
            url = job["url"]
            try:
                is_alive = _check_url(client, url)
                if not is_alive:
                    mark_url_dead(url)
                    expired_count += 1
                    logger.info(f"Expired: {url}")
            except Exception as e:
                logger.warning(f"Health check error for {url}: {e}")
            
            # Rate limit
            time.sleep(delay + random.uniform(0, 0.5))
    
    logger.info(
        f"Health check complete: {expired_count} expired out of "
        f"{len(jobs_to_check)} checked"
    )
    
    return expired_count


def _check_url(client: httpx.Client, url: str) -> bool:
    """
    Check if a URL is still live.
    Returns True if the job appears to still be available.
    """
    try:
        # First try a HEAD request (lightweight)
        response = client.head(url)
        
        if response.status_code in (404, 410, 451):
            return False
        
        if response.status_code in (301, 302, 303, 307, 308):
            # Redirect — check if it goes to a generic "jobs" page
            redirect_url = str(response.headers.get("location", ""))
            if _is_generic_redirect(redirect_url):
                return False
        
        if response.status_code == 200:
            # Do a full GET to check content for "expired" patterns
            full_response = client.get(url)
            body = full_response.text.lower()
            
            for pattern in EXPIRED_PATTERNS:
                if pattern in body:
                    return False
            
            return True
        
        # For other status codes, assume still alive (don't falsely expire)
        return True
        
    except httpx.TimeoutException:
        # Timeout doesn't mean expired — could be temporary
        logger.warning(f"Timeout checking {url}")
        return True
    except Exception as e:
        logger.warning(f"Error checking {url}: {e}")
        return True


def _is_generic_redirect(redirect_url: str) -> bool:
    """Check if a redirect goes to a generic jobs/careers page (indicating the specific job is gone)."""
    generic_paths = [
        "/careers",
        "/jobs",
        "/open-positions",
        "/job-openings",
        "/404",
    ]
    redirect_lower = redirect_url.lower()
    
    for path in generic_paths:
        if redirect_lower.endswith(path) or redirect_lower.endswith(path + "/"):
            return True
    
    return False
