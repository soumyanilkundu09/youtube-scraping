"""
Export a topic's analysis to Google Sheets, one set of tabs per topic in the same spreadsheet.

  python tools/export_to_sheets.py --topic animation

Reads .tmp/<slug>/analysis.json and writes:
  <slug>_videos      every video with its computed metrics
  <slug>_channels    per-channel summary (tracked and discovered channels)
  <slug>_skills      skill/tool coverage and performance
  <slug>_candidates  channels worth adding to the topic profile
(<slug>_history is written by track_history.py.)

Each tab is cleared before writing, and numbers are written as numbers so they sort and pivot.
Auth: service account (GOOGLE_SERVICE_ACCOUNT_JSON, or ./service_account.json locally).
"""

import json
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
import common  # noqa: E402

load_dotenv()

SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")

VIDEO_HEADERS = [
    "video_id", "title", "channel_name", "channel_subscribers", "published_at",
    "view_count", "like_count", "comment_count", "engagement_rate", "views_per_day",
    "outlier_score", "outlier_basis", "days_since_published", "content_type", "is_short", "duration_seconds",
    "cluster", "tags", "source", "search_query", "url",
]
CHANNEL_HEADERS = [
    "channel_name", "in_profile", "subscribers", "video_count", "total_views",
    "avg_views", "median_views", "avg_engagement_rate",
]
SKILL_HEADERS = [
    "skill", "video_count", "share", "median_views_per_day", "median_outlier",
    "total_views", "top_video_title", "top_video_url",
]
CANDIDATE_HEADERS = [
    "channel_name", "subscribers", "video_count", "median_views", "views_per_subscriber",
    "total_views", "score",
]


def cell(value):
    """Sheets-friendly value: numbers stay numbers, lists are joined, None becomes blank."""
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(x) for x in value)
    return value


def table(headers: list[str], records: list[dict]) -> list[list]:
    return [headers] + [[cell(r.get(h)) for h in headers] for r in records]


def main():
    slug = common.parse_topic_arg()
    if not SPREADSHEET_ID:
        raise ValueError("GOOGLE_SHEETS_SPREADSHEET_ID not set (in .env locally, or in the Modal Secret)")
    apath = common.analysis_path(slug)
    if not os.path.exists(apath):
        raise FileNotFoundError(f"Not found: {apath}. Run analyze_trends.py --topic {slug} first.")
    with open(apath, encoding="utf-8") as f:
        analysis = json.load(f)

    skills = [{**s, "top_video_title": (s.get("top_video") or {}).get("title", ""),
               "top_video_url": (s.get("top_video") or {}).get("url", "")} for s in analysis.get("skills", [])]
    videos = sorted(analysis["videos"], key=lambda v: v["view_count"], reverse=True)

    tabs = {
        "videos": table(VIDEO_HEADERS, videos),
        "channels": table(CHANNEL_HEADERS, analysis.get("channel_stats", [])),
        "skills": table(SKILL_HEADERS, skills),
        "candidates": table(CANDIDATE_HEADERS, analysis.get("channel_candidates", [])),
    }

    service = common.sheets_service()
    for kind, rows in tabs.items():
        tab = common.tab_name(slug, kind)
        common.write_tab(service, SPREADSHEET_ID, tab, rows)
        print(f"{tab}: {len(rows) - 1} rows")

    print(f"\nDone. View at: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}")


if __name__ == "__main__":
    main()
