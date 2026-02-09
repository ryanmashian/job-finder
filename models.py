"""
models.py — Data models for the Job Finder application.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class JobListing:
    """Raw job listing scraped from a source."""
    title: str
    company: str
    location: str
    description: str
    url: str
    source: str
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    experience_required: Optional[str] = None
    date_posted: Optional[str] = None
    company_industry: Optional[str] = None
    raw_html: Optional[str] = None
    date_scraped: str = field(default_factory=lambda: datetime.now().isoformat())
    fuzzy_key: Optional[str] = None
    is_repost: bool = False
    original_listing_id: Optional[int] = None


@dataclass
class VCInfo:
    """Venture capital backing information for a company."""
    backed_by_notable_vc: Optional[bool] = None  # None = unknown
    investors: list[str] = field(default_factory=list)
    funding_stage: Optional[str] = None
    source: Optional[str] = None  # "crunchbase", "web_search", "claude", "cache"


@dataclass
class ScoredJob:
    """A job listing that has been scored by the Claude API."""
    listing: JobListing
    score: float
    reasoning: str
    matching_skills: list[str] = field(default_factory=list)
    missing_requirements: list[str] = field(default_factory=list)
    recommendation: str = ""
    vc_info: VCInfo = field(default_factory=VCInfo)
    freshness: str = "unknown"  # "green", "yellow", "red", "black", "unknown"
    is_repost: bool = False
    date_scored: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "new"  # "new", "applied", "skipped", "expired", "archived"
    url_alive: bool = True


@dataclass
class RunLog:
    """Log entry for a single pipeline run."""
    run_date: str
    source: str
    listings_scraped: int = 0
    listings_new: int = 0
    listings_passed_filter: int = 0
    listings_scored: int = 0
    listings_expired: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
