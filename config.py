"""
config.py — Loads preferences.yaml and environment variables.
Provides typed access to all configuration.
"""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Project root directory
PROJECT_ROOT = Path(__file__).parent

# Load preferences.yaml
PREFERENCES_PATH = PROJECT_ROOT / "preferences.yaml"
with open(PREFERENCES_PATH, "r") as f:
    _prefs = yaml.safe_load(f)


# --- Candidate ---
CANDIDATE_NAME = _prefs["candidate"]["name"]
CANDIDATE_EMAIL = _prefs["candidate"]["email"]
RESUME_FILE = PROJECT_ROOT / _prefs["candidate"]["resume_file"]

# --- Target Roles ---
TARGET_ROLES = _prefs["target_roles"]

# --- Locations ---
LOCATIONS = _prefs["locations"]

def get_all_location_aliases() -> list[str]:
    """Return a flat list of all location aliases (lowercased)."""
    aliases = []
    for loc_data in LOCATIONS.values():
        aliases.extend([a.lower() for a in loc_data["aliases"]])
    return aliases

LOCATION_ALIASES = get_all_location_aliases()

# --- Filters ---
EXPERIENCE_MAX_YEARS = _prefs["filters"]["experience_max_years"]
SALARY_MIN = _prefs["filters"]["salary_min"]
EXCLUDED_INDUSTRIES = [kw.lower() for kw in _prefs["filters"]["excluded_industries"]]
REMOTE_ALLOWED = _prefs["filters"]["remote_allowed"]

# --- Positive Signals ---
POSITIVE_SIGNALS = _prefs["positive_signals"]
SIGNAL_TOOLS = [t.lower() for t in POSITIVE_SIGNALS["tools"]]
SIGNAL_THEMES = [t.lower() for t in POSITIVE_SIGNALS["themes"]]
SIGNAL_RESPONSIBILITIES = [r.lower() for r in POSITIVE_SIGNALS["responsibilities"]]

# --- Notable VCs ---
NOTABLE_VCS = _prefs["notable_vcs"]
ALL_NOTABLE_VCS = [vc.lower() for vc in NOTABLE_VCS["tier_1"] + NOTABLE_VCS["tier_2"]]

# --- Scoring ---
VC_BONUS = _prefs["scoring"]["vc_bonus"]
REPOST_FLAG = _prefs["scoring"]["repost_flag"]
FRESHNESS_THRESHOLDS = _prefs["scoring"]["freshness_thresholds"]

# --- Rate Limiting ---
RATE_LIMITS = _prefs["rate_limiting"]

# --- Schedule ---
SCHEDULE = _prefs["schedule"]

# --- Listing Health ---
LISTING_HEALTH = _prefs["listing_health"]

# --- API Keys & Secrets (from .env) ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", CANDIDATE_EMAIL)
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
CRUNCHBASE_API_KEY = os.getenv("CRUNCHBASE_API_KEY", "")

# --- Database ---
DB_PATH = PROJECT_ROOT / "data" / "jobs.db"

# --- Logging ---
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "job_finder.log"


def validate_config():
    """Check that critical configuration is present."""
    warnings = []
    
    if not ANTHROPIC_API_KEY:
        warnings.append("ANTHROPIC_API_KEY is not set — scoring will not work")
    if not GOOGLE_SHEETS_ID:
        warnings.append("GOOGLE_SHEETS_ID is not set — sheet sync will not work")
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        warnings.append("GOOGLE_SERVICE_ACCOUNT_JSON is not set — sheet sync will not work")
    if not GMAIL_APP_PASSWORD:
        warnings.append("GMAIL_APP_PASSWORD is not set — email digest will not work")
    if not SERPAPI_KEY:
        warnings.append("SERPAPI_KEY is not set — LinkedIn and Indeed scrapers will not work")
    
    if not RESUME_FILE.exists():
        warnings.append(f"Resume file not found at {RESUME_FILE}")
    
    return warnings
