"""
vc_enrichment.py — Enriches job listings with VC backing data.
Uses a cache-first approach with multiple fallback sources.
"""

from typing import Optional

from models import JobListing, VCInfo
from config import ALL_NOTABLE_VCS, NOTABLE_VCS
from database import get_cached_vc, cache_vc_data
from monitoring import get_logger

logger = get_logger("vc_enrichment")


def enrich_vc_data(listings: list[JobListing]) -> list[tuple[JobListing, VCInfo]]:
    """
    Enrich listings with VC backing data.
    Returns list of (listing, vc_info) tuples.
    
    Priority order:
    1. SQLite cache (instant, free)
    2. Crunchbase API (limited free tier)
    3. Web search fallback (uses SerpAPI)
    4. Claude API fallback (bundled with scoring — handled in scorer.py)
    """
    results = []
    cache_hits = 0
    lookups_needed = 0
    
    for listing in listings:
        company = listing.company.strip()
        
        # 1. Check cache first
        cached = get_cached_vc(company)
        if cached:
            vc_info = VCInfo(
                backed_by_notable_vc=cached["backed_by_notable"],
                investors=cached["investors"],
                funding_stage=cached["funding_stage"],
                source="cache"
            )
            cache_hits += 1
            results.append((listing, vc_info))
            continue
        
        # 2. Try external sources (Crunchbase, web search)
        vc_info = _lookup_vc(company)
        
        if vc_info and vc_info.source != "unknown":
            # Cache the result for future lookups
            cache_vc_data(
                company_name=company,
                investors=vc_info.investors,
                funding_stage=vc_info.funding_stage,
                backed_by_notable=vc_info.backed_by_notable_vc or False
            )
            lookups_needed += 1
        else:
            # No data found — will try Claude fallback during scoring
            vc_info = VCInfo(backed_by_notable_vc=None, source="unknown")
        
        results.append((listing, vc_info))
    
    logger.info(
        f"VC enrichment: {len(listings)} companies — "
        f"{cache_hits} cache hits, {lookups_needed} new lookups, "
        f"{len(listings) - cache_hits - lookups_needed} unknown"
    )
    
    return results


def _lookup_vc(company: str) -> Optional[VCInfo]:
    """
    Look up VC backing for a company using external sources.
    Currently a placeholder — implement Crunchbase and web search as needed.
    """
    # Placeholder: Try to match from description or known data
    # In production, this would call:
    # 1. Crunchbase API
    # 2. SerpAPI web search for "{company} funding round investors"
    
    # For now, return unknown — Claude fallback in scorer.py will handle it
    return VCInfo(backed_by_notable_vc=None, source="unknown")


def check_investors_notable(investors: list[str]) -> bool:
    """Check if any investors in the list are on the notable VC list."""
    for investor in investors:
        investor_lower = investor.lower()
        for notable in ALL_NOTABLE_VCS:
            if notable in investor_lower or investor_lower in notable:
                return True
    return False


def format_vc_display(vc_info: VCInfo) -> str:
    """Format VC info for display in Google Sheets."""
    if vc_info.backed_by_notable_vc is None:
        return "Unknown"
    
    if not vc_info.investors:
        if vc_info.backed_by_notable_vc:
            return "VC-backed (details unknown)"
        return "No notable VC"
    
    return ", ".join(vc_info.investors[:3])  # Show top 3


# --- Crunchbase API Integration (placeholder) ---

def _crunchbase_lookup(company: str) -> Optional[VCInfo]:
    """
    Look up a company on Crunchbase.
    Requires CRUNCHBASE_API_KEY to be set.
    Free tier: ~200 calls/month.
    """
    from config import CRUNCHBASE_API_KEY
    
    if not CRUNCHBASE_API_KEY:
        return None
    
    # TODO: Implement Crunchbase API integration
    # Endpoint: https://api.crunchbase.com/api/v4/entities/organizations/{company}
    # Parse: funding_rounds, investors
    
    return None


# --- Web Search Fallback (placeholder) ---

def _web_search_lookup(company: str) -> Optional[VCInfo]:
    """
    Search the web for VC backing info.
    Uses SerpAPI to search "{company} funding round investors".
    """
    from config import SERPAPI_KEY
    
    if not SERPAPI_KEY:
        return None
    
    # TODO: Implement SerpAPI web search for funding info
    # Search: f"{company} funding round investors"
    # Parse results for VC names against our notable list
    
    return None
