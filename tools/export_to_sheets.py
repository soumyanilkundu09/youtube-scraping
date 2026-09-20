"""
Export AI trends data to Google Sheets.
Reads .tmp/ai_trends_data.json and .tmp/ai_trends_analysis.json.
Writes two tabs:
  Sheet1 — raw video data (all enriched fields)
  Sheet2 — channel stats summary

Requires credentials.json (OAuth) and GOOGLE_SHEETS_SPREADSHEET_ID in .env.
"""

import os
import json
from dotenv import load_dotenv
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
VIDEOS_PATH = os.path.join(BASE_DIR, ".tmp", "ai_trends_data.json")
ANALYSIS_PATH = os.path.join(BASE_DIR, ".tmp", "ai_trends_analysis.json")
TOKEN_PATH = os.path.join(BASE_DIR, "token.json")
CREDS_PATH = os.path.join(BASE_DIR, "credentials.json")

VIDEO_HEADERS = [
    "video_id", "title", "channel_name", "published_at",
    "view_count", "like_count", "comment_count",
    "engagement_rate", "views_per_day", "days_since_published",
    "content_type", "duration_seconds", "source", "search_query", "url",
]

CHANNEL_HEADERS = [
    "channel_name", "video_count", "total_views", "avg_views", "avg_engagement_rate",
]


def get_creds():
    # Headless (e.g. Modal): service account JSON supplied via environment variable
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        return service_account.Credentials.from_service_account_info(
            json.loads(sa_json), scopes=SCOPES
        )

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return creds


def ensure_sheet_tab(service, spreadsheet_id: str, title: str) -> None:
    """Create a tab if it doesn't already exist."""
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    existing = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if title not in existing:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        ).execute()


def write_tab(service, spreadsheet_id: str, tab: str, rows: list[list]) -> None:
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{tab}!A1",
        valueInputOption="RAW",
        body={"values": rows},
    ).execute()


def main():
    if not SPREADSHEET_ID:
        raise ValueError("GOOGLE_SHEETS_SPREADSHEET_ID not set in .env")
    if not os.path.exists(VIDEOS_PATH):
        raise FileNotFoundError(f"Not found: {VIDEOS_PATH}. Run fetch_ai_trends.py first.")

    with open(VIDEOS_PATH, encoding="utf-8") as f:
        videos = json.load(f)

    # Load enriched fields from analysis if available
    if os.path.exists(ANALYSIS_PATH):
        with open(ANALYSIS_PATH, encoding="utf-8") as f:
            analysis = json.load(f)
        # Build lookup for enriched video fields
        enriched = {}
        for v in analysis.get("top_videos_by_views", []) + analysis.get("top_videos_by_engagement", []):
            enriched[v["video_id"]] = v
        # Merge into videos list
        for v in videos:
            if v["video_id"] in enriched:
                v.update({
                    k: enriched[v["video_id"]][k]
                    for k in ["engagement_rate", "views_per_day", "days_since_published", "content_type"]
                    if k in enriched[v["video_id"]]
                })
        channel_stats = analysis.get("channel_stats", [])
    else:
        channel_stats = []

    creds = get_creds()
    service = build("sheets", "v4", credentials=creds)

    # Ensure both tabs exist
    ensure_sheet_tab(service, SPREADSHEET_ID, "Sheet1")
    ensure_sheet_tab(service, SPREADSHEET_ID, "Sheet2")

    # --- Sheet1: Raw video data ---
    video_rows = [VIDEO_HEADERS]
    for v in videos:
        row = [str(v.get(h, "")) for h in VIDEO_HEADERS]
        video_rows.append(row)

    write_tab(service, SPREADSHEET_ID, "Sheet1", video_rows)
    print(f"Sheet1: exported {len(videos)} video rows")

    # --- Sheet2: Channel stats ---
    if channel_stats:
        channel_rows = [CHANNEL_HEADERS]
        for ch in channel_stats:
            channel_rows.append([str(ch.get(h, "")) for h in CHANNEL_HEADERS])
        write_tab(service, SPREADSHEET_ID, "Sheet2", channel_rows)
        print(f"Sheet2: exported {len(channel_stats)} channel rows")
    else:
        print("Sheet2: no channel stats available (run analyze_trends.py first)")

    print(f"\nDone. View at: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}")


if __name__ == "__main__":
    main()
