"""
email_digest.py — Daily email digest with new matches and health summary.
Sends via Gmail SMTP using an App Password.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from models import ScoredJob
from config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD, GOOGLE_SHEETS_ID
from freshness import freshness_to_emoji
from monitoring import get_logger

logger = get_logger("email_digest")

SHEETS_URL_TEMPLATE = "https://docs.google.com/spreadsheets/d/{sheet_id}"


def send_digest(
    scored_jobs: list[ScoredJob],
    errors: list[str],
    duration: float,
    expired_count: int = 0
):
    """
    Send the daily email digest.
    Adapts content based on results:
    - New matches found → full digest with top 5
    - No matches but healthy → short "all clear" email
    - Errors occurred → alert email with details
    """
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        logger.warning("Email credentials not configured — skipping digest")
        return

    subject, html_body = _build_email_content(scored_jobs, errors, duration, expired_count)

    try:
        _send_email(subject, html_body)
        logger.info(f"Email digest sent to {GMAIL_ADDRESS}")
    except Exception as e:
        logger.error(f"Failed to send email digest: {e}")


def _build_email_content(
    scored_jobs: list[ScoredJob],
    errors: list[str],
    duration: float,
    expired_count: int
) -> tuple[str, str]:
    """Build email subject and HTML body based on results."""

    has_jobs = len(scored_jobs) > 0
    has_errors = len(errors) > 0
    sheets_url = SHEETS_URL_TEMPLATE.format(sheet_id=GOOGLE_SHEETS_ID) if GOOGLE_SHEETS_ID else "#"

    # --- Subject line ---
    if has_errors and not has_jobs:
        subject = "⚠️ Job Finder Alert — Errors Detected"
    elif has_jobs:
        top_score = max(j.score for j in scored_jobs)
        subject = f"🎯 {len(scored_jobs)} New Job Matches (Top: {top_score}/10)"
    else:
        subject = "✅ Job Finder — No New Matches Today"

    # --- HTML body ---
    html_parts = []
    html_parts.append(_html_header())

    # Summary section
    html_parts.append(f"""
    <div style="background:#f8f9fa; padding:16px; border-radius:8px; margin-bottom:20px;">
        <h2 style="margin:0 0 8px 0; color:#333;">Daily Summary</h2>
        <p style="margin:4px 0; color:#555;">New matches: <strong>{len(scored_jobs)}</strong></p>
        <p style="margin:4px 0; color:#555;">Expired listings: <strong>{expired_count}</strong></p>
        <p style="margin:4px 0; color:#555;">Errors: <strong>{len(errors)}</strong></p>
        <p style="margin:4px 0; color:#555;">Run time: <strong>{duration:.1f}s</strong></p>
    </div>
    """)

    # Top matches section
    if has_jobs:
        top_jobs = sorted(scored_jobs, key=lambda j: j.score, reverse=True)[:5]
        html_parts.append('<h2 style="color:#333;">Top Matches</h2>')

        for i, job in enumerate(top_jobs, 1):
            freshness_icon = freshness_to_emoji(job.freshness)
            repost_tag = ' <span style="color:#f59e0b;">🔄 Repost</span>' if job.is_repost else ""
            skills = ", ".join(job.matching_skills[:4]) if job.matching_skills else "—"
            missing = ", ".join(job.missing_requirements[:3]) if job.missing_requirements else "—"

            vc_display = ""
            if job.vc_info.investors:
                vc_display = f'<p style="margin:2px 0; color:#555; font-size:13px;">💰 Backed by: {", ".join(job.vc_info.investors[:3])}</p>'

            html_parts.append(f"""
            <div style="border:1px solid #e0e0e0; border-radius:8px; padding:14px; margin-bottom:12px;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <h3 style="margin:0; color:#1a1a1a;">{i}. {job.listing.title}</h3>
                    <span style="background:#4f46e5; color:white; padding:3px 10px; border-radius:12px; font-weight:bold; font-size:14px;">{job.score}/10</span>
                </div>
                <p style="margin:4px 0; color:#666;">{job.listing.company} · {job.listing.location or 'Location N/A'} {freshness_icon}{repost_tag}</p>
                {vc_display}
                <p style="margin:4px 0; color:#555; font-size:13px;">✅ Matches: {skills}</p>
                <p style="margin:4px 0; color:#555; font-size:13px;">⚠️ Gaps: {missing}</p>
                <p style="margin:6px 0; color:#333; font-size:13px; font-style:italic;">{job.recommendation}</p>
                <a href="{job.listing.url}" style="color:#4f46e5; text-decoration:none; font-size:13px;">View Listing →</a>
            </div>
            """)

        if len(scored_jobs) > 5:
            html_parts.append(f'<p style="color:#666;">...and {len(scored_jobs) - 5} more matches.</p>')

    # Sheet link
    html_parts.append(f"""
    <div style="text-align:center; margin:24px 0;">
        <a href="{sheets_url}" style="background:#4f46e5; color:white; padding:12px 24px; border-radius:6px; text-decoration:none; font-weight:bold;">
            View Full Results in Google Sheets
        </a>
    </div>
    """)

    # Errors section
    if has_errors:
        html_parts.append('<h2 style="color:#dc2626;">⚠️ Errors</h2>')
        html_parts.append('<ul style="color:#666;">')
        for error in errors:
            html_parts.append(f'<li>{error}</li>')
        html_parts.append('</ul>')

    html_parts.append(_html_footer())

    return subject, "\n".join(html_parts)


def _html_header() -> str:
    return """
    <!DOCTYPE html>
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width:600px; margin:0 auto; padding:20px; color:#333;">
    <h1 style="color:#4f46e5; border-bottom:2px solid #4f46e5; padding-bottom:8px;">🔍 Job Finder Daily Digest</h1>
    """


def _html_footer() -> str:
    return """
    <hr style="border:none; border-top:1px solid #e0e0e0; margin:24px 0;">
    <p style="color:#999; font-size:12px; text-align:center;">
        This email was sent by your Job Finder pipeline running on Railway.
    </p>
    </body>
    </html>
    """


def _send_email(subject: str, html_body: str):
    """Send an email via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = GMAIL_ADDRESS

    # Attach HTML body
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())
