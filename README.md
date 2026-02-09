# 🔍 Job Finder — Startup Operations Job Pipeline

An automated Python pipeline that scrapes startup operations job listings from multiple sources, filters and scores them against your profile using Claude AI, and delivers ranked results to a Google Sheet with daily email digests.

## Features

- **6 job sources**: Wellfound, Built In, YC Work at a Startup, startups.gallery, LinkedIn (via SerpAPI), Indeed (via SerpAPI)
- **Smart filtering**: Hard filters on location, experience, salary, and industry exclusions
- **AI-powered scoring**: Claude Haiku scores each job 1-10 with calibrated prompts
- **VC enrichment**: Identifies if companies are backed by notable VCs
- **Freshness tracking**: Color-coded indicators show how old each listing is
- **Repost detection**: Flags when companies re-list the same role (positive signal — still hiring)
- **Listing health checks**: Detects expired/removed job postings
- **Google Sheets output**: Full tracker with scoring, freshness, VC data, and status columns
- **Daily email digest**: Top 5 matches delivered to your inbox every morning
- **SQLite persistence**: All data stored locally as source of truth

## Quick Start

### 1. Clone and install
```bash
git clone <your-repo-url>
cd job-finder
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env with your API keys
```

**Required:**
- `ANTHROPIC_API_KEY` — Get from [console.anthropic.com](https://console.anthropic.com)
- `GOOGLE_SHEETS_ID` — Create a Google Sheet and copy the ID from the URL
- `GOOGLE_SERVICE_ACCOUNT_JSON` — [Set up a service account](https://docs.gspread.org/en/latest/oauth2.html)
- `GMAIL_APP_PASSWORD` — [Generate an App Password](https://myaccount.google.com/apppasswords)

**Optional:**
- `SERPAPI_KEY` — For LinkedIn/Indeed scrapers ([serpapi.com](https://serpapi.com))
- `CRUNCHBASE_API_KEY` — For VC enrichment

### 3. Customize your search
Edit `preferences.yaml` to adjust:
- Target role titles
- Location preferences
- Salary floor
- Industry exclusions
- Positive signal keywords
- Notable VC list

### 4. Run
```bash
python main.py
```

### 5. Deploy to Railway (for daily automation)
```bash
# Install Railway CLI, then:
railway login
railway init
railway up

# Set up cron job in Railway dashboard: 0 7 * * * (7 AM PT daily)
```

## Architecture

```
Scraping → Deduplication → DB Check → Hard Filters → Keyword Pre-filter 
→ VC Enrichment → Claude Scoring → Freshness → Google Sheets + Email
```

## File Structure
```
job-finder/
├── main.py              # Pipeline orchestrator
├── config.py            # Configuration loader
├── preferences.yaml     # Search criteria (human-editable)
├── models.py            # Data models
├── database.py          # SQLite operations
├── scrapers/            # Job source scrapers
├── filters.py           # Hard pass/fail filters
├── pre_filter.py        # Keyword pre-filter
├── deduplication.py     # Fuzzy dedup + repost detection
├── vc_enrichment.py     # VC backing lookup
├── scorer.py            # Claude AI scoring
├── freshness.py         # Posting age indicators
├── listing_health.py    # URL expiry detection
├── sheets.py            # Google Sheets sync
├── email_digest.py      # Daily email notifications
├── monitoring.py        # Logging + alerting
└── resume.txt           # Your resume for scoring
```

## Estimated Costs
- Claude API: ~$2-4/month
- SerpAPI: Free tier (100/month) or ~$50/month
- Everything else: Free

## License
Personal use.
