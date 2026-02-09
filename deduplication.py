"""
deduplication.py — Fuzzy deduplication across sources and repost detection.
Uses rapidfuzz for intelligent string matching.
"""

import re
from rapidfuzz import fuzz

from models import JobListing
from database import get_existing_fuzzy_keys, get_recent_fuzzy_keys, url_exists
from monitoring import get_logger

logger = get_logger("deduplication")

# Suffixes to strip when normalizing company names
COMPANY_SUFFIXES = [
    "inc", "inc.", "llc", "llc.", "corp", "corp.", "corporation",
    "ltd", "ltd.", "limited", "co", "co.", "company",
    "technologies", "technology", "tech", "labs", "lab",
    "group", "holdings", "solutions", "services",
]

FUZZY_THRESHOLD = 85  # Similarity percentage to consider a duplicate


def normalize_company(name: str) -> str:
    """Normalize a company name for comparison."""
    name = name.lower().strip()
    # Remove punctuation
    name = re.sub(r'[^\w\s]', '', name)
    # Remove common suffixes
    words = name.split()
    words = [w for w in words if w not in COMPANY_SUFFIXES]
    return " ".join(words).strip()


def normalize_title(title: str) -> str:
    """Normalize a job title for comparison."""
    title = title.lower().strip()
    # Remove punctuation
    title = re.sub(r'[^\w\s]', '', title)
    # Normalize common variations
    title = title.replace("&", "and")
    return title.strip()


def normalize_location(location: str) -> str:
    """Normalize location to a city-level key."""
    location = location.lower().strip()
    
    # Map to canonical city names
    la_keywords = ["los angeles", "la", "beverly hills", "santa monica", "culver city", "playa vista", "venice", "el segundo"]
    sf_keywords = ["san francisco", "sf", "bay area", "palo alto", "mountain view", "menlo park", "sunnyvale", "oakland", "san jose"]
    nyc_keywords = ["new york", "nyc", "manhattan", "brooklyn"]
    
    for kw in la_keywords:
        if kw in location:
            return "los_angeles"
    for kw in sf_keywords:
        if kw in location:
            return "san_francisco"
    for kw in nyc_keywords:
        if kw in location:
            return "new_york"
    
    return location


def generate_fuzzy_key(listing: JobListing) -> str:
    """Generate a normalized key for fuzzy matching."""
    company = normalize_company(listing.company)
    title = normalize_title(listing.title)
    location = normalize_location(listing.location or "")
    return f"{company}|{title}|{location}"


def deduplicate_batch(listings: list[JobListing]) -> list[JobListing]:
    """
    Deduplicate a batch of listings from the current scrape run.
    Keeps the listing with the most complete data when duplicates are found.
    """
    if not listings:
        return []
    
    # Assign fuzzy keys
    for listing in listings:
        listing.fuzzy_key = generate_fuzzy_key(listing)
    
    # Group by fuzzy key similarity
    unique: list[JobListing] = []
    seen_keys: list[str] = []
    
    for listing in listings:
        is_dup = False
        for seen_key in seen_keys:
            similarity = fuzz.ratio(listing.fuzzy_key, seen_key)
            if similarity >= FUZZY_THRESHOLD:
                is_dup = True
                # Check if this listing has more data than the existing one
                existing_idx = None
                for i, u in enumerate(unique):
                    if u.fuzzy_key == seen_key:
                        existing_idx = i
                        break
                if existing_idx is not None and _completeness_score(listing) > _completeness_score(unique[existing_idx]):
                    unique[existing_idx] = listing
                break
        
        if not is_dup:
            unique.append(listing)
            seen_keys.append(listing.fuzzy_key)
    
    dupes_removed = len(listings) - len(unique)
    if dupes_removed > 0:
        logger.info(f"Deduplication: {len(listings)} → {len(unique)} ({dupes_removed} duplicates removed)")
    
    return unique


def filter_already_seen(listings: list[JobListing]) -> list[JobListing]:
    """
    Filter out listings that are already in the database.
    Checks both URL and fuzzy key similarity.
    """
    existing_keys = get_existing_fuzzy_keys()
    new_listings = []
    
    for listing in listings:
        # Check exact URL match
        if url_exists(listing.url):
            continue
        
        # Check fuzzy key similarity against DB
        is_seen = False
        for existing_key in existing_keys:
            similarity = fuzz.ratio(listing.fuzzy_key or "", existing_key)
            if similarity >= FUZZY_THRESHOLD:
                is_seen = True
                break
        
        if not is_seen:
            new_listings.append(listing)
    
    filtered = len(listings) - len(new_listings)
    logger.info(f"Already-seen filter: {len(listings)} → {len(new_listings)} ({filtered} already in DB)")
    
    return new_listings


def detect_reposts(listings: list[JobListing]) -> list[JobListing]:
    """
    Check if any new listings are reposts of recently seen roles.
    A repost = same company + same title within the last 30 days, but different URL.
    Reposts are flagged (is_repost=True) but NOT removed — they're a positive signal.
    """
    recent_keys = get_recent_fuzzy_keys(days=30)
    reposts_found = 0
    
    for listing in listings:
        key = listing.fuzzy_key or generate_fuzzy_key(listing)
        for recent_key, original_id in recent_keys.items():
            # Check company + title match (ignore location in repost detection)
            listing_parts = key.split("|")
            recent_parts = recent_key.split("|")
            
            if len(listing_parts) >= 2 and len(recent_parts) >= 2:
                company_sim = fuzz.ratio(listing_parts[0], recent_parts[0])
                title_sim = fuzz.ratio(listing_parts[1], recent_parts[1])
                
                if company_sim >= 90 and title_sim >= 85:
                    listing.is_repost = True
                    listing.original_listing_id = original_id
                    reposts_found += 1
                    logger.info(
                        f"Repost detected: {listing.company} - {listing.title} "
                        f"(original ID: {original_id})"
                    )
                    break
    
    if reposts_found > 0:
        logger.info(f"Repost detection: {reposts_found} reposts found (kept as positive signal)")
    
    return listings


def _completeness_score(listing: JobListing) -> int:
    """Score how complete a listing's data is. Higher = more complete."""
    score = 0
    if listing.description and len(listing.description) > 100:
        score += 3
    if listing.salary_min is not None:
        score += 2
    if listing.salary_max is not None:
        score += 2
    if listing.experience_required:
        score += 1
    if listing.date_posted:
        score += 1
    if listing.company_industry:
        score += 1
    return score
