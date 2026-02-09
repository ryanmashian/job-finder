"""
main.py — Main orchestrator for the Job Finder pipeline.
Coordinates scraping, filtering, scoring, and output.
"""

import time
from datetime import datetime

from config import validate_config
from database import init_db, store_listings_batch, store_scored_job, store_listing, log_run, get_listing_id_by_url
from models import RunLog
from monitoring import (
    setup_logging, get_logger, log_scraper_success, log_scraper_failure,
    log_pipeline_step, log_run_summary
)
from deduplication import deduplicate_batch, filter_already_seen, detect_reposts, generate_fuzzy_key
from filters import apply_hard_filters
from pre_filter import apply_keyword_pre_filter
from vc_enrichment import enrich_vc_data
from scorer import score_listings
from freshness import assign_freshness
from listing_health import check_listing_health
from sheets import sync_to_sheet
from email_digest import send_digest

# Import scrapers
from scrapers.yc import YCScraper
from scrapers.builtin import BuiltInScraper
from scrapers.wellfound import WellfoundScraper
from scrapers.startups_gallery import StartupsGalleryScraper
from scrapers.linkedin_api import LinkedInAPIScraper
from scrapers.indeed_api import IndeedAPIScraper


def get_active_scrapers():
    """Return list of all active scraper instances."""
    return [
        YCScraper(),
        BuiltInScraper(),
        # Disabled — Wellfound returns 403, needs auth/different approach
        # WellfoundScraper(),
        StartupsGalleryScraper(),
        LinkedInAPIScraper(),
        IndeedAPIScraper(),
    ]


def run():
    """Execute the full Job Finder pipeline."""
    # Setup
    root_logger = setup_logging()
    logger = get_logger("main")
    
    logger.info("=" * 60)
    logger.info("JOB FINDER PIPELINE — Starting run")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info("=" * 60)
    
    # Validate configuration
    warnings = validate_config()
    for warning in warnings:
        logger.warning(f"Config: {warning}")
    
    # Initialize database
    init_db()
    
    run_start = time.time()
    errors = []
    
    # ===== 1. SCRAPE ALL SOURCES =====
    logger.info("--- Phase 1: Scraping ---")
    all_listings = []
    
    for scraper in get_active_scrapers():
        try:
            with scraper:
                results = scraper.scrape()
                all_listings.extend(results)
                log_scraper_success(logger, scraper.name, len(results))
        except Exception as e:
            errors.append(f"{scraper.name}: {str(e)}")
            log_scraper_failure(logger, scraper.name, e)
    
    log_pipeline_step(logger, "Scraping", 0, len(all_listings))
    
    if not all_listings:
        logger.warning("No listings scraped from any source")
        if len(errors) == len(get_active_scrapers()):
            logger.error("ALL scrapers failed — check connectivity and source availability")
    
    # ===== 2. ASSIGN FUZZY KEYS =====
    for listing in all_listings:
        if not listing.fuzzy_key:
            listing.fuzzy_key = generate_fuzzy_key(listing)
    
    # ===== 3. DEDUPLICATE ACROSS SOURCES =====
    logger.info("--- Phase 2: Deduplication ---")
    unique_listings = deduplicate_batch(all_listings)
    log_pipeline_step(logger, "Deduplication", len(all_listings), len(unique_listings))
    
    # ===== 4. FILTER ALREADY-SEEN JOBS =====
    logger.info("--- Phase 3: Database Check ---")
    new_listings = filter_already_seen(unique_listings)
    log_pipeline_step(logger, "Already-seen filter", len(unique_listings), len(new_listings))
    
    # ===== 5. DETECT REPOSTS =====
    new_listings = detect_reposts(new_listings)
    repost_count = sum(1 for l in new_listings if l.is_repost)
    if repost_count:
        logger.info(f"Reposts detected: {repost_count}")
    
    # ===== 6. STORE RAW LISTINGS =====
    stored = store_listings_batch(new_listings)
    logger.info(f"Stored {stored} new listings in database")
    
    # ===== 7. APPLY HARD FILTERS =====
    logger.info("--- Phase 4: Hard Filters ---")
    filtered = apply_hard_filters(new_listings)
    log_pipeline_step(logger, "Hard filters", len(new_listings), len(filtered))
    
    # ===== 8. APPLY KEYWORD PRE-FILTER =====
    logger.info("--- Phase 5: Keyword Pre-filter ---")
    pre_filtered = apply_keyword_pre_filter(filtered)
    log_pipeline_step(logger, "Keyword pre-filter", len(filtered), len(pre_filtered))
    
    # ===== 9. ENRICH WITH VC DATA =====
    logger.info("--- Phase 6: VC Enrichment ---")
    enriched = enrich_vc_data(pre_filtered)
    logger.info(f"VC enrichment complete for {len(enriched)} listings")
    
    # ===== 10. SCORE WITH CLAUDE API =====
    logger.info("--- Phase 7: Claude API Scoring ---")
    scored = score_listings(enriched)
    log_pipeline_step(logger, "Claude scoring", len(enriched), len(scored))
    
    # ===== 11. ASSIGN FRESHNESS INDICATORS =====
    scored = assign_freshness(scored)
    
    # ===== 12. STORE SCORED RESULTS =====
    for scored_job in scored:
        # Look up the listing ID from the database by URL
        listing_id = get_listing_id_by_url(scored_job.listing.url)
        if listing_id:
            store_scored_job(scored_job, listing_id)
        else:
            logger.warning(f"Could not find listing ID for {scored_job.listing.url}")
    
    # ===== 13. SORT BY SCORE =====
    scored.sort(key=lambda x: x.score, reverse=True)
    
    # ===== 14. CHECK HEALTH OF EXISTING LISTINGS =====
    logger.info("--- Phase 8: Listing Health Check ---")
    try:
        expired_count = check_listing_health()
    except Exception as e:
        expired_count = 0
        errors.append(f"Listing health check: {str(e)}")
        logger.error(f"Listing health check failed: {e}")
    
    # ===== 15. SYNC TO GOOGLE SHEETS =====
    logger.info("--- Phase 9: Google Sheets Sync ---")
    try:
        sync_to_sheet(new_scored_count=len(scored), expired_count=expired_count)
    except Exception as e:
        errors.append(f"Google Sheets sync: {str(e)}")
        logger.error(f"Google Sheets sync failed: {e}")
    
    # ===== 16. SEND EMAIL DIGEST =====
    logger.info("--- Phase 10: Email Digest ---")
    run_duration = time.time() - run_start
    try:
        send_digest(scored, errors, run_duration, expired_count)
    except Exception as e:
        errors.append(f"Email digest: {str(e)}")
        logger.error(f"Email digest failed: {e}")
    
    # ===== 17. LOG RUN SUMMARY =====
    log_run_summary(
        logger,
        listings_scraped=len(all_listings),
        listings_new=len(new_listings),
        listings_passed_filter=len(pre_filtered),
        listings_scored=len(scored),
        listings_expired=expired_count,
        errors=errors,
        duration=run_duration,
    )
    
    # Store run log in database
    log_run(RunLog(
        run_date=datetime.now().isoformat(),
        source="all",
        listings_scraped=len(all_listings),
        listings_new=len(new_listings),
        listings_passed_filter=len(pre_filtered),
        listings_scored=len(scored),
        listings_expired=expired_count,
        errors=errors,
        duration_seconds=run_duration,
    ))
    
    logger.info("JOB FINDER PIPELINE — Run complete")
    
    return {
        "scraped": len(all_listings),
        "new": len(new_listings),
        "filtered": len(pre_filtered),
        "scored": len(scored),
        "expired": expired_count,
        "errors": errors,
        "duration": run_duration,
    }


if __name__ == "__main__":
    run()
