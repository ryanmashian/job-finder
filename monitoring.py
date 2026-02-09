"""
monitoring.py — Logging setup and alerting for the Job Finder pipeline.
"""

import logging
import sys
from pathlib import Path

from config import LOG_DIR, LOG_FILE


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """
    Set up structured logging to both file and stdout.
    Returns the root logger for the application.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    logger = logging.getLogger("job_finder")
    logger.setLevel(level)
    
    # Prevent duplicate handlers on re-init
    if logger.handlers:
        return logger
    
    # Format
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # File handler (append mode, rotates manually or via logrotate)
    file_handler = logging.FileHandler(str(LOG_FILE), mode="a", encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Stdout handler
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger for a specific module."""
    return logging.getLogger(f"job_finder.{name}")


def log_scraper_success(logger: logging.Logger, scraper_name: str, count: int):
    """Log a successful scraper run."""
    logger.info(f"[{scraper_name}] Scraped {count} listings successfully")


def log_scraper_failure(logger: logging.Logger, scraper_name: str, error: Exception):
    """Log a scraper failure."""
    logger.error(f"[{scraper_name}] Scraper failed: {type(error).__name__}: {str(error)}")


def log_pipeline_step(logger: logging.Logger, step: str, input_count: int, output_count: int):
    """Log a pipeline step with input/output counts."""
    filtered = input_count - output_count
    logger.info(f"[{step}] {input_count} in → {output_count} out ({filtered} filtered)")


def log_run_summary(
    logger: logging.Logger,
    listings_scraped: int,
    listings_new: int,
    listings_passed_filter: int,
    listings_scored: int,
    listings_expired: int,
    errors: list[str],
    duration: float
):
    """Log a complete run summary."""
    logger.info("=" * 60)
    logger.info("RUN SUMMARY")
    logger.info(f"  Total scraped:     {listings_scraped}")
    logger.info(f"  New (not seen):    {listings_new}")
    logger.info(f"  Passed filters:    {listings_passed_filter}")
    logger.info(f"  Scored by Claude:  {listings_scored}")
    logger.info(f"  Expired listings:  {listings_expired}")
    logger.info(f"  Errors:            {len(errors)}")
    logger.info(f"  Duration:          {duration:.1f}s")
    
    if errors:
        logger.warning("ERRORS:")
        for err in errors:
            logger.warning(f"  - {err}")
    
    logger.info("=" * 60)
