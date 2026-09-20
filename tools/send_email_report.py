"""
Send the latest .pptx report from .tmp/ to the configured recipient via Gmail SMTP.
Uses app password auth (no OAuth needed — just GMAIL_ADDRESS + GMAIL_APP_PASSWORD in .env).

Setup (one-time):
  1. Enable 2-Step Verification on your Google account
  2. Go to myaccount.google.com → Security → App Passwords
  3. Create a new app password → copy the 16-char code
  4. Add to .env: GMAIL_APP_PASSWORD=<the 16-char code>
"""

import os
import glob
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
RECIPIENT = "soumyanilkundu09@gmail.com"

TMP_DIR = os.path.join(os.path.dirname(__file__), "..", ".tmp")
ANALYSIS_PATH = os.path.join(TMP_DIR, "ai_trends_analysis.json")


def find_latest_deck() -> str | None:
    pattern = os.path.join(TMP_DIR, "ai_youtube_report_*.pptx")
    matches = sorted(glob.glob(pattern), reverse=True)
    return matches[0] if matches else None


def load_insights() -> list[str]:
    if not os.path.exists(ANALYSIS_PATH):
        return []
    import json
    with open(ANALYSIS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("key_insights", [])[:3]


def build_email_body(insights: list[str], deck_filename: str) -> str:
    date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    bullets = "\n".join(f"  • {i}" for i in insights) if insights else "  • See the attached deck for full analysis."

    return f"""Hi Soumy,

Your weekly AI & Automation YouTube Intelligence Report is attached for {date_str}.

Top 3 insights from this week's data:
{bullets}

The full 12-slide deck ({deck_filename}) includes:
  - Top trending videos by views and engagement
  - Trending keywords dominating AI titles
  - Channel comparisons and content type breakdown
  - Upload pattern analysis
  - Content recommendations tailored to your niche

Stay ahead of the curve!

— WAT Framework Automation
"""


def main():
    if not GMAIL_ADDRESS:
        raise ValueError("GMAIL_ADDRESS not set in .env")
    if not GMAIL_APP_PASSWORD:
        raise ValueError("GMAIL_APP_PASSWORD not set in .env — see setup instructions at top of this file")

    deck_path = find_latest_deck()
    if not deck_path:
        raise FileNotFoundError(f"No .pptx found in {TMP_DIR}. Run generate_report.py first.")

    deck_filename = os.path.basename(deck_path)
    insights = load_insights()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    subject = f"AI YouTube Trends Report — {date_str}"

    print(f"Sending '{deck_filename}' to {RECIPIENT}...")

    msg = MIMEMultipart()
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = RECIPIENT
    msg["Subject"] = subject
    msg.attach(MIMEText(build_email_body(insights, deck_filename), "plain"))

    with open(deck_path, "rb") as f:
        part = MIMEBase(
            "application",
            "vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=deck_filename)
    msg.attach(part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.send_message(msg)

    print(f"Email sent to {RECIPIENT}")


if __name__ == "__main__":
    main()
