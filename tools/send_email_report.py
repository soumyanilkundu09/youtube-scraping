"""
Email a topic's latest report deck, or a short failure notice, via Gmail SMTP.

  python tools/send_email_report.py --topic animation
  python tools/send_email_report.py --topic animation --failure "analyze_trends.py"

Uses app password auth (no OAuth needed: just GMAIL_ADDRESS + GMAIL_APP_PASSWORD).
Recipient: the topic profile's `recipient`, else REPORT_RECIPIENT, else DEFAULT_RECIPIENT.

Setup (one-time):
  1. Enable 2-Step Verification on your Google account
  2. Go to myaccount.google.com -> Security -> App Passwords
  3. Create a new app password -> copy the 16-char code
  4. Add to .env: GMAIL_APP_PASSWORD=<the 16-char code>
"""

import glob
import json
import os
import smtplib
import sys
from datetime import datetime, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
import common  # noqa: E402

load_dotenv()

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
DEFAULT_RECIPIENT = "soumyanilkundu09@gmail.com"


def find_latest_deck(slug: str) -> str | None:
    matches = sorted(glob.glob(os.path.join(common.tmp_dir(slug), f"report_{slug}_*.pptx")), reverse=True)
    return matches[0] if matches else None


def load_insights(slug: str) -> list[str]:
    path = common.analysis_path(slug)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("key_insights", [])[:3]


def build_report_body(display_name: str, insights: list[str], deck_filename: str) -> str:
    date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    bullets = "\n".join(f"  - {i}" for i in insights) if insights else "  - See the attached deck for full analysis."
    sheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
    sheet_line = f"\nRaw data: https://docs.google.com/spreadsheets/d/{sheet_id}\n" if sheet_id else ""
    return f"""Hi Soumy,

Your {display_name} YouTube Intelligence Report is attached for {date_str}.

Top 3 insights from this run's data:
{bullets}

The deck ({deck_filename}) covers:
  - Top videos by views and engagement, plus breakout videos versus their channel's norm
  - Trending and emerging phrases, and topic clusters with related videos
  - Skills and tools coverage, channel comparison, and channels worth adding
  - Long-form vs Shorts, best day and length to publish, and data-driven recommendations
{sheet_line}
- WAT Framework Automation
"""


def build_failure_body(display_name: str, step: str) -> str:
    return f"""The scheduled {display_name} YouTube report did not complete.

Failed step: {step}

Open the run logs in the Modal dashboard for the traceback. No report was sent for this run.
Do not re-run straight away if the failure was a YouTube quota error: quota resets at midnight Pacific.

- WAT Framework Automation
"""


def send(msg: MIMEMultipart) -> None:
    if not GMAIL_ADDRESS:
        raise ValueError("GMAIL_ADDRESS not set")
    if not GMAIL_APP_PASSWORD:
        raise ValueError("GMAIL_APP_PASSWORD not set: see setup instructions at the top of this file")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.send_message(msg)


def main():
    slug = common.parse_topic_arg()
    profile = common.load_profile(slug)
    recipient = profile.get("recipient") or os.getenv("REPORT_RECIPIENT") or DEFAULT_RECIPIENT
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    msg = MIMEMultipart()
    msg["From"] = GMAIL_ADDRESS or ""
    msg["To"] = recipient

    if "--failure" in sys.argv:
        idx = sys.argv.index("--failure")
        step = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "unknown step"
        msg["Subject"] = f"FAILED: {profile['display_name']} YouTube report ({date_str})"
        msg.attach(MIMEText(build_failure_body(profile["display_name"], step), "plain"))
        send(msg)
        print(f"Failure notice sent to {recipient}")
        return

    deck_path = find_latest_deck(slug)
    if not deck_path:
        raise FileNotFoundError(f"No report_{slug}_*.pptx in {common.tmp_dir(slug)}. Run generate_report.py first.")
    deck_filename = os.path.basename(deck_path)

    msg["Subject"] = f"{profile['display_name']} YouTube Trends Report - {date_str}"
    msg.attach(MIMEText(build_report_body(profile["display_name"], load_insights(slug), deck_filename), "plain"))
    with open(deck_path, "rb") as f:
        part = MIMEBase("application", "vnd.openxmlformats-officedocument.presentationml.presentation")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=deck_filename)
    msg.attach(part)

    print(f"Sending '{deck_filename}' to {recipient}...")
    send(msg)
    print(f"Email sent to {recipient}")


if __name__ == "__main__":
    main()
