"""
database.py — SQLite database setup, queries, and helpers.
SQLite is the single source of truth. Google Sheets is a downstream view.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config import DB_PATH
from models import JobListing, ScoredJob, VCInfo, RunLog


def get_connection() -> sqlite3.Connection:
    """Get a database connection, creating the DB file if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS job_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT,
            description TEXT,
            salary_min REAL,
            salary_max REAL,
            experience_required TEXT,
            source TEXT,
            date_posted TEXT,
            company_industry TEXT,
            date_scraped TEXT,
            fuzzy_key TEXT,
            is_repost INTEGER DEFAULT 0,
            original_listing_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS scored_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER REFERENCES job_listings(id),
            score REAL,
            reasoning TEXT,
            matching_skills TEXT,
            missing_requirements TEXT,
            recommendation TEXT,
            vc_backed INTEGER,
            vc_investors TEXT,
            funding_stage TEXT,
            freshness TEXT DEFAULT 'unknown',
            is_repost INTEGER DEFAULT 0,
            date_scored TEXT,
            synced_to_sheet INTEGER DEFAULT 0,
            status TEXT DEFAULT 'new',
            url_alive INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS vc_cache (
            company_name TEXT PRIMARY KEY,
            investors TEXT,
            funding_stage TEXT,
            backed_by_notable INTEGER,
            date_checked TEXT
        );

        CREATE TABLE IF NOT EXISTS run_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT,
            source TEXT,
            listings_scraped INTEGER DEFAULT 0,
            listings_new INTEGER DEFAULT 0,
            listings_passed_filter INTEGER DEFAULT 0,
            listings_scored INTEGER DEFAULT 0,
            listings_expired INTEGER DEFAULT 0,
            errors TEXT,
            duration_seconds REAL
        );

        CREATE INDEX IF NOT EXISTS idx_listings_fuzzy_key ON job_listings(fuzzy_key);
        CREATE INDEX IF NOT EXISTS idx_listings_url ON job_listings(url);
        CREATE INDEX IF NOT EXISTS idx_scored_status ON scored_jobs(status);
        CREATE INDEX IF NOT EXISTS idx_scored_synced ON scored_jobs(synced_to_sheet);
    """)
    
    conn.commit()
    conn.close()


# --- Job Listings ---

def url_exists(url: str) -> bool:
    """Check if a URL is already in the database."""
    conn = get_connection()
    result = conn.execute("SELECT 1 FROM job_listings WHERE url = ?", (url,)).fetchone()
    conn.close()
    return result is not None


def get_listing_id_by_url(url: str) -> Optional[int]:
    """Get the listing ID for a given URL."""
    conn = get_connection()
    result = conn.execute("SELECT id FROM job_listings WHERE url = ?", (url,)).fetchone()
    conn.close()
    return result["id"] if result else None


def get_existing_fuzzy_keys() -> dict[str, int]:
    """Return a dict of fuzzy_key -> listing_id for all existing listings."""
    conn = get_connection()
    rows = conn.execute("SELECT id, fuzzy_key FROM job_listings WHERE fuzzy_key IS NOT NULL").fetchall()
    conn.close()
    return {row["fuzzy_key"]: row["id"] for row in rows}


def get_recent_fuzzy_keys(days: int = 30) -> dict[str, int]:
    """Return fuzzy keys from the last N days for repost detection."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, fuzzy_key FROM job_listings WHERE fuzzy_key IS NOT NULL AND date_scraped >= ?",
        (cutoff,)
    ).fetchall()
    conn.close()
    return {row["fuzzy_key"]: row["id"] for row in rows}


def store_listing(listing: JobListing) -> int:
    """Store a raw job listing. Returns the inserted row ID."""
    conn = get_connection()
    cursor = conn.execute(
        """INSERT OR IGNORE INTO job_listings 
           (url, title, company, location, description, salary_min, salary_max,
            experience_required, source, date_posted, company_industry, date_scraped,
            fuzzy_key, is_repost, original_listing_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            listing.url, listing.title, listing.company, listing.location,
            listing.description, listing.salary_min, listing.salary_max,
            listing.experience_required, listing.source, listing.date_posted,
            listing.company_industry, listing.date_scraped, listing.fuzzy_key,
            int(listing.is_repost), listing.original_listing_id
        )
    )
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id


def store_listings_batch(listings: list[JobListing]) -> int:
    """Store multiple listings. Returns count of inserted rows."""
    conn = get_connection()
    inserted = 0
    for listing in listings:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO job_listings 
                   (url, title, company, location, description, salary_min, salary_max,
                    experience_required, source, date_posted, company_industry, date_scraped,
                    fuzzy_key, is_repost, original_listing_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    listing.url, listing.title, listing.company, listing.location,
                    listing.description, listing.salary_min, listing.salary_max,
                    listing.experience_required, listing.source, listing.date_posted,
                    listing.company_industry, listing.date_scraped, listing.fuzzy_key,
                    int(listing.is_repost), listing.original_listing_id
                )
            )
            if conn.total_changes:
                inserted += 1
        except sqlite3.IntegrityError:
            continue
    conn.commit()
    conn.close()
    return inserted


# --- Scored Jobs ---

def store_scored_job(scored: ScoredJob, listing_id: int) -> int:
    """Store a scored job result. Returns the inserted row ID."""
    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO scored_jobs 
           (listing_id, score, reasoning, matching_skills, missing_requirements,
            recommendation, vc_backed, vc_investors, funding_stage, freshness,
            is_repost, date_scored, status, url_alive)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            listing_id, scored.score, scored.reasoning,
            json.dumps(scored.matching_skills),
            json.dumps(scored.missing_requirements),
            scored.recommendation,
            1 if scored.vc_info.backed_by_notable_vc else (0 if scored.vc_info.backed_by_notable_vc is False else None),
            json.dumps(scored.vc_info.investors),
            scored.vc_info.funding_stage,
            scored.freshness, int(scored.is_repost),
            scored.date_scored, scored.status, int(scored.url_alive)
        )
    )
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id


def get_unsynced_scored_jobs() -> list[dict]:
    """Get scored jobs that haven't been synced to Google Sheets yet."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT s.*, j.title, j.company, j.location, j.url, j.salary_min, j.salary_max,
                  j.source, j.date_posted, j.date_scraped
           FROM scored_jobs s
           JOIN job_listings j ON s.listing_id = j.id
           WHERE s.synced_to_sheet = 0
           ORDER BY s.score DESC"""
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def mark_synced(scored_job_ids: list[int]):
    """Mark scored jobs as synced to Google Sheets."""
    conn = get_connection()
    placeholders = ",".join("?" * len(scored_job_ids))
    conn.execute(
        f"UPDATE scored_jobs SET synced_to_sheet = 1 WHERE id IN ({placeholders})",
        scored_job_ids
    )
    conn.commit()
    conn.close()


def update_job_status(scored_job_id: int, status: str):
    """Update the status of a scored job."""
    conn = get_connection()
    conn.execute(
        "UPDATE scored_jobs SET status = ? WHERE id = ?",
        (status, scored_job_id)
    )
    conn.commit()
    conn.close()


def mark_url_dead(listing_url: str):
    """Mark a listing URL as no longer alive."""
    conn = get_connection()
    conn.execute(
        """UPDATE scored_jobs SET url_alive = 0, status = 'expired'
           WHERE listing_id IN (SELECT id FROM job_listings WHERE url = ?)""",
        (listing_url,)
    )
    conn.commit()
    conn.close()


def get_urls_to_health_check(max_checks: int = 50, recheck_days: int = 3) -> list[dict]:
    """Get URLs of 'new' status jobs that haven't been checked recently."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT j.url, j.id as listing_id, s.id as scored_id
           FROM scored_jobs s
           JOIN job_listings j ON s.listing_id = j.id
           WHERE s.status = 'new' AND s.url_alive = 1
           ORDER BY j.date_scraped ASC
           LIMIT ?""",
        (max_checks,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


# --- VC Cache ---

def get_cached_vc(company_name: str) -> Optional[dict]:
    """Check if we have cached VC data for a company."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM vc_cache WHERE company_name = ?",
        (company_name.lower().strip(),)
    ).fetchone()
    conn.close()
    if row:
        return {
            "investors": json.loads(row["investors"]) if row["investors"] else [],
            "funding_stage": row["funding_stage"],
            "backed_by_notable": bool(row["backed_by_notable"]),
            "date_checked": row["date_checked"]
        }
    return None


def cache_vc_data(company_name: str, investors: list[str], funding_stage: Optional[str], backed_by_notable: bool):
    """Cache VC data for a company."""
    conn = get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO vc_cache 
           (company_name, investors, funding_stage, backed_by_notable, date_checked)
           VALUES (?, ?, ?, ?, ?)""",
        (
            company_name.lower().strip(),
            json.dumps(investors),
            funding_stage,
            int(backed_by_notable),
            datetime.now().isoformat()
        )
    )
    conn.commit()
    conn.close()


# --- Run Log ---

def log_run(run_log: RunLog):
    """Store a run log entry."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO run_log 
           (run_date, source, listings_scraped, listings_new, listings_passed_filter,
            listings_scored, listings_expired, errors, duration_seconds)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_log.run_date, run_log.source, run_log.listings_scraped,
            run_log.listings_new, run_log.listings_passed_filter,
            run_log.listings_scored, run_log.listings_expired,
            json.dumps(run_log.errors), run_log.duration_seconds
        )
    )
    conn.commit()
    conn.close()


def get_last_run() -> Optional[dict]:
    """Get the most recent run log entry."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM run_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None
