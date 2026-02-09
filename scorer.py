"""
scorer.py — Claude API scoring engine with calibrated prompt.
Uses Anthropic's Claude Haiku for cost-efficient job-resume matching.
"""

import json
from typing import Optional

import anthropic

from models import JobListing, ScoredJob, VCInfo
from config import ANTHROPIC_API_KEY, RESUME_FILE, VC_BONUS
from vc_enrichment import check_investors_notable, format_vc_display
from monitoring import get_logger

logger = get_logger("scorer")

# Load resume text once
_resume_text: Optional[str] = None


def _get_resume_text() -> str:
    """Load and cache the resume text."""
    global _resume_text
    if _resume_text is None:
        with open(RESUME_FILE, "r") as f:
            _resume_text = f.read()
    return _resume_text


SCORING_PROMPT = """You are evaluating job listings for a recent USC graduate with experience in startup operations, venture capital, financial modeling, and automation (Python, n8n, Zapier).

Here is the candidate's resume:

{resume}

SCORING CALIBRATION — use these anchors to ensure consistent scoring:

SCORE 9-10 (Perfect match):
- Title is exactly an ops role at an early-stage startup
- Mentions tools the candidate knows (Python, Notion, Excel, automation)
- Involves financial modeling, KPI tracking, or working directly with founders
- 0-2 years experience required
- Company is in a relevant space (fintech, SaaS, consumer tech)
- Example: "Business Operations Associate at a Series A fintech startup, working directly with the CEO on KPI dashboards, financial models, and process automation. Python or automation experience preferred. 0-2 years."

SCORE 6-8 (Good match with some gaps):
- Title is ops-adjacent or a broader role
- Some skill overlap but missing 1-2 key areas
- May ask for 2-3 years experience
- Good company but not perfect stage/industry fit
- Example: "Strategy & Operations Analyst at a Series C SaaS company. Requires SQL and Tableau (candidate doesn't have). 2-3 years preferred."

SCORE 3-5 (Weak match):
- Title is loosely related but role is different in practice
- Minimal skill overlap
- May be in a less relevant industry
- Example: "Operations Coordinator at a real estate company. Mostly logistics and vendor management. No financial or technical component."

SCORE 1-2 (Not a match):
- Slipped through filters but clearly wrong
- Example: "Senior VP of Operations, 10+ years required"

Here is the job listing:
Title: {title}
Company: {company}
Location: {location}
Date Posted: {date_posted}
Description:
{description}

VC Backing Info: {vc_info}

Score the match from 1-10 based on:
- Skill alignment (tools, technical abilities)
- Experience relevance (startup ops, VC, finance)
- Responsibility match (automation, KPI tracking, financial modeling, working with founders)
- Growth potential (will this role leverage the candidate's strengths?)
- Company stage fit (early-stage/high-growth preference)
- If the company is backed by a notable VC, add +0.5 to the score

You MUST respond with valid JSON only, no markdown, no backticks, no other text. Keep reasoning under 100 words:
{{"score": 8.5, "reasoning": "Strong match because...", "matching_skills": ["Python", "Notion", "financial modeling"], "missing_requirements": ["SQL experience preferred"], "recommendation": "Apply — strong fit for your background", "detected_vc_investors": ["Sequoia"]}}"""


def score_listings(enriched_listings: list[tuple[JobListing, VCInfo]]) -> list[ScoredJob]:
    """
    Score a batch of listings using Claude API.
    Returns a list of ScoredJob objects.
    """
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not set — cannot score listings")
        return []
    
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resume = _get_resume_text()
    scored_jobs = []
    errors = 0
    
    for i, (listing, vc_info) in enumerate(enriched_listings):
        logger.info(
            f"Scoring {i+1}/{len(enriched_listings)}: "
            f"{listing.company} — {listing.title}"
        )
        
        try:
            scored = _score_single(client, resume, listing, vc_info)
            if scored:
                scored_jobs.append(scored)
            else:
                errors += 1
        except Exception as e:
            logger.error(f"Scoring failed for {listing.company} — {listing.title}: {e}")
            errors += 1
    
    logger.info(
        f"Scoring complete: {len(scored_jobs)} scored, {errors} errors "
        f"out of {len(enriched_listings)} listings"
    )
    
    return scored_jobs


def _score_single(
    client: anthropic.Anthropic,
    resume: str,
    listing: JobListing,
    vc_info: VCInfo
) -> Optional[ScoredJob]:
    """Score a single job listing. Returns ScoredJob or None on failure."""
    
    vc_display = format_vc_display(vc_info)
    
    prompt = SCORING_PROMPT.format(
        resume=resume,
        title=listing.title,
        company=listing.company,
        location=listing.location or "Not specified",
        date_posted=listing.date_posted or "Not specified",
        description=(listing.description or "No description available")[:3000],  # Truncate long descriptions
        vc_info=vc_display,
    )
    
    # First attempt
    result = _call_claude(client, prompt)
    
    if result is None:
        # Retry with stricter instructions
        logger.warning(f"Retrying scoring for {listing.company} — {listing.title}")
        retry_prompt = prompt + "\n\nCRITICAL: Respond ONLY with a JSON object. No other text whatsoever."
        result = _call_claude(client, retry_prompt)
    
    if result is None:
        return None
    
    # Process VC info from Claude's response
    detected_vcs = result.get("detected_vc_investors", [])
    if detected_vcs and vc_info.source == "unknown":
        # Claude found VC info we didn't have
        vc_info.investors = detected_vcs
        vc_info.backed_by_notable_vc = check_investors_notable(detected_vcs)
        vc_info.source = "claude"
    
    # Apply VC bonus
    score = result.get("score", 5)
    if vc_info.backed_by_notable_vc and score < 10:
        score = min(10, score + VC_BONUS)
    
    return ScoredJob(
        listing=listing,
        score=score,
        reasoning=result.get("reasoning", ""),
        matching_skills=result.get("matching_skills", []),
        missing_requirements=result.get("missing_requirements", []),
        recommendation=result.get("recommendation", ""),
        vc_info=vc_info,
        is_repost=listing.is_repost,
    )


def _call_claude(client: anthropic.Anthropic, prompt: str) -> Optional[dict]:
    """Call Claude API and parse JSON response."""
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        
        text = response.content[0].text.strip()
        
        # Clean up response — remove markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]  # Remove first line
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        
        # Remove 'json' prefix if present
        if text.startswith("json"):
            text = text[4:].strip()
        
        result = json.loads(text)
        
        # Validate required fields
        if "score" not in result:
            logger.warning(f"Claude response missing 'score' field: {text[:200]}")
            return None
        
        return result
        
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse Claude JSON response: {e}")
        return None
    except anthropic.APIError as e:
        logger.error(f"Claude API error: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error calling Claude: {e}")
        return None
