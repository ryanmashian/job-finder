"""
sheets.py — Google Sheets integration.
Sheets is a VIEW of the SQLite database, not the source of truth.
"""

import json
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from config import GOOGLE_SHEETS_ID, GOOGLE_SERVICE_ACCOUNT_JSON
from database import get_unsynced_scored_jobs, mark_synced
from freshness import freshness_to_emoji
from monitoring import get_logger

logger = get_logger("sheets")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Sheet tab names
TAB_NEW = "New Matches"
TAB_ALL = "All Matches"

# Column headers
HEADERS = [
    "Score", "Freshness", "Title", "Company", "Location", "Salary",
    "Notable VCs", "Repost?", "Source", "Key Matches", "Missing",
    "Link", "Date Found", "Date Posted", "Status", "Recommendation"
]


def get_sheets_client() -> Optional[gspread.Spreadsheet]:
    """Authenticate and return the Google Sheets spreadsheet object."""
    if not GOOGLE_SERVICE_ACCOUNT_JSON or not GOOGLE_SHEETS_ID:
        logger.warning("Google Sheets credentials not configured")
        return None
    
    try:
        creds = Credentials.from_service_account_file(
            GOOGLE_SERVICE_ACCOUNT_JSON, scopes=SCOPES
        )
        gc = gspread.authorize(creds)
        spreadsheet = gc.open_by_key(GOOGLE_SHEETS_ID)
        return spreadsheet
    except Exception as e:
        logger.error(f"Failed to connect to Google Sheets: {e}")
        return None


def sync_to_sheet(new_scored_count: int = 0, expired_count: int = 0):
    """
    Sync unsynced scored jobs from SQLite to Google Sheets.
    """
    spreadsheet = get_sheets_client()
    if not spreadsheet:
        logger.warning("Skipping Google Sheets sync — not configured")
        return
    
    # Get unsynced jobs from database
    unsynced = get_unsynced_scored_jobs()
    
    if not unsynced:
        logger.info("No new jobs to sync to Google Sheets")
        return
    
    logger.info(f"Syncing {len(unsynced)} new jobs to Google Sheets")
    
    try:
        # Ensure tabs exist with headers
        _ensure_tab(spreadsheet, TAB_NEW, HEADERS)
        _ensure_tab(spreadsheet, TAB_ALL, HEADERS)
        
        # Prepare rows
        rows = []
        scored_ids = []
        for job in unsynced:
            row = _format_row(job)
            rows.append(row)
            scored_ids.append(job["id"])
        
        # Clear "New Matches" tab and write fresh
        new_sheet = spreadsheet.worksheet(TAB_NEW)
        new_sheet.clear()
        new_sheet.append_row(HEADERS, value_input_option="RAW")
        if rows:
            new_sheet.append_rows(rows, value_input_option="RAW")
        
        # Append to "All Matches" tab
        all_sheet = spreadsheet.worksheet(TAB_ALL)
        if rows:
            all_sheet.append_rows(rows, value_input_option="RAW")
        
        # Mark as synced in database
        mark_synced(scored_ids)
        
        logger.info(f"Successfully synced {len(rows)} jobs to Google Sheets")
        
    except Exception as e:
        logger.error(f"Error syncing to Google Sheets: {e}")
        raise


def _ensure_tab(spreadsheet: gspread.Spreadsheet, tab_name: str, headers: list[str]):
    """Ensure a tab exists with the correct headers."""
    try:
        spreadsheet.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=len(headers))
        worksheet.append_row(headers, value_input_option="RAW")
        logger.info(f"Created new tab: {tab_name}")


def _format_row(job: dict) -> list:
    """Format a scored job dict into a row for Google Sheets."""
    # Parse JSON fields
    matching_skills = _safe_json_loads(job.get("matching_skills", "[]"))
    missing_reqs = _safe_json_loads(job.get("missing_requirements", "[]"))
    vc_investors = _safe_json_loads(job.get("vc_investors", "[]"))
    
    # Format salary
    salary = _format_salary(job.get("salary_min"), job.get("salary_max"))
    
    # Format VCs
    if vc_investors:
        vc_display = ", ".join(vc_investors[:3])
    elif job.get("vc_backed") == 1:
        vc_display = "VC-backed"
    elif job.get("vc_backed") == 0:
        vc_display = "No notable VC"
    else:
        vc_display = "Unknown"
    
    # Repost indicator
    repost = "🔄 Repost" if job.get("is_repost") else ""
    
    return [
        f"{job.get('score', 0)}/10",
        freshness_to_emoji(job.get("freshness", "unknown")),
        job.get("title", ""),
        job.get("company", ""),
        job.get("location", ""),
        salary,
        vc_display,
        repost,
        job.get("source", ""),
        ", ".join(matching_skills) if matching_skills else "",
        ", ".join(missing_reqs) if missing_reqs else "",
        job.get("url", ""),
        job.get("date_scraped", ""),
        job.get("date_posted", ""),
        job.get("status", "new"),
        job.get("recommendation", ""),
    ]


def _format_salary(salary_min: Optional[float], salary_max: Optional[float]) -> str:
    """Format salary range for display."""
    if salary_min and salary_max:
        return f"${salary_min/1000:.0f}K–${salary_max/1000:.0f}K"
    elif salary_min:
        return f"${salary_min/1000:.0f}K+"
    elif salary_max:
        return f"Up to ${salary_max/1000:.0f}K"
    return "—"


def _safe_json_loads(value) -> list:
    """Safely parse a JSON string, returning empty list on failure."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
    return []
