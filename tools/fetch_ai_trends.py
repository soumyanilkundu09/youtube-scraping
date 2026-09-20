"""
Fetch enriched video metadata from top AI/automation YouTube channels and keyword searches.
Combines search.list (discovery) with videos.list (statistics) for full engagement data.
Output: .tmp/ai_trends_data.json

Quota budget per run: ~1,950 units (well within 10,000/day free limit)
  - 10 channels x 100 units (search.list) = 1,000
  - ~350 videos x 1 unit (videos.list stats) = 350
  - 6 keyword searches x 100 units = 600
"""

import os
import json
import re
from datetime import datetime, timezone
from dotenv import load_dotenv
from googleapiclient.discovery import build

load_dotenv()

API_KEY = os.getenv("YOUTUBE_API_KEY")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", ".tmp", "ai_trends_data.json")

# Edit these lists to add/remove channels or search queries
CHANNELS = [
    "@mreflow",              # Matt Wolfe — AI news & tools
    "@Fireship",             # Fireship — tech/AI tutorials
    "@aiexplained-official", # AI Explained — research explainers
    "@TwoMinutePapers",      # Two Minute Papers — AI research
    "@lexfridman",           # Lex Fridman — AI interviews
    "@DaveShap",             # David Shapiro — AI automation
    "@theaiadvantage",       # The AI Advantage — AI tools
    "@nicholasrenotte",      # Nicholas Renotte — ML tutorials
    "@samwitteveenai",       # Sam Witteveen — LLM development
    "@aiautomationagency",   # AI Automation Agency
]

KEYWORD_SEARCHES = [
    "AI automation 2025",
    "Claude AI agent",
    "LLM agents tutorial",
    "AI tools productivity",
    "ChatGPT workflow",
    "AI content creation",
]

VIDEOS_PER_CHANNEL = 30
VIDEOS_PER_SEARCH = 20


def get_channel_id(youtube, handle_or_id: str) -> tuple[str, str]:
    """Returns (channel_id, channel_name). Accepts @handle or UCxxx ID."""
    if handle_or_id.startswith("UC"):
        resp = youtube.channels().list(part="snippet", id=handle_or_id).execute()
        items = resp.get("items", [])
        name = items[0]["snippet"]["title"] if items else handle_or_id
        return handle_or_id, name

    resp = youtube.search().list(
        q=handle_or_id, type="channel", part="id,snippet", maxResults=1
    ).execute()
    items = resp.get("items", [])
    if not items:
        print(f"  WARNING: Channel not found: {handle_or_id}")
        return None, None
    return items[0]["id"]["channelId"], items[0]["snippet"]["channelTitle"]


def search_channel_videos(youtube, channel_id: str, max_results: int) -> list[str]:
    """Returns list of video IDs from a channel's recent uploads."""
    video_ids = []
    next_page = None

    while len(video_ids) < max_results:
        resp = youtube.search().list(
            channelId=channel_id,
            part="id",
            order="date",
            type="video",
            maxResults=min(max_results - len(video_ids), 50),
            pageToken=next_page,
        ).execute()

        for item in resp.get("items", []):
            video_ids.append(item["id"]["videoId"])

        next_page = resp.get("nextPageToken")
        if not next_page:
            break

    return video_ids


def search_keyword_videos(youtube, query: str, max_results: int) -> list[str]:
    """Returns list of video IDs matching a keyword search."""
    resp = youtube.search().list(
        q=query,
        part="id",
        order="viewCount",
        type="video",
        maxResults=min(max_results, 50),
        publishedAfter=_days_ago_iso(30),
    ).execute()
    return [item["id"]["videoId"] for item in resp.get("items", [])]


def fetch_video_details(youtube, video_ids: list[str]) -> list[dict]:
    """Batch-fetch full video metadata + statistics. 1 quota unit per video."""
    results = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        resp = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(batch),
        ).execute()

        for item in resp.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            details = item.get("contentDetails", {})

            duration_secs = _iso_duration_to_seconds(details.get("duration", "PT0S"))
            results.append({
                "video_id": item["id"],
                "title": snippet.get("title", ""),
                "channel_name": snippet.get("channelTitle", ""),
                "channel_id": snippet.get("channelId", ""),
                "published_at": snippet.get("publishedAt", ""),
                "description": snippet.get("description", "")[:500],
                "thumbnail_url": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                "url": f"https://www.youtube.com/watch?v={item['id']}",
                "view_count": int(stats.get("viewCount", 0)),
                "like_count": int(stats.get("likeCount", 0)),
                "comment_count": int(stats.get("commentCount", 0)),
                "duration_seconds": duration_secs,
            })

    return results


def _days_ago_iso(days: int) -> str:
    from datetime import timedelta
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_duration_to_seconds(duration: str) -> int:
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return 0
    h, m, s = (int(x or 0) for x in match.groups())
    return h * 3600 + m * 60 + s


def main():
    if not API_KEY:
        raise ValueError("YOUTUBE_API_KEY not set in .env")

    youtube = build("youtube", "v3", developerKey=API_KEY)
    all_videos = {}  # keyed by video_id to deduplicate

    # --- Channel scraping ---
    print(f"Scraping {len(CHANNELS)} channels...")
    for handle in CHANNELS:
        print(f"  {handle}")
        channel_id, channel_name = get_channel_id(youtube, handle)
        if not channel_id:
            continue

        video_ids = search_channel_videos(youtube, channel_id, VIDEOS_PER_CHANNEL)
        videos = fetch_video_details(youtube, video_ids)

        for v in videos:
            v["source"] = "channel"
            v["search_query"] = handle
            all_videos[v["video_id"]] = v

        print(f"    -> {len(videos)} videos fetched")

    # --- Keyword searches ---
    print(f"\nRunning {len(KEYWORD_SEARCHES)} keyword searches...")
    for query in KEYWORD_SEARCHES:
        print(f"  '{query}'")
        video_ids = search_keyword_videos(youtube, query, VIDEOS_PER_SEARCH)
        videos = fetch_video_details(youtube, video_ids)

        for v in videos:
            if v["video_id"] not in all_videos:
                v["source"] = "keyword_search"
                v["search_query"] = query
                all_videos[v["video_id"]] = v

        print(f"    -> {len(videos)} videos found ({len(all_videos)} total unique)")

    result = list(all_videos.values())

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\nDone. Saved {len(result)} unique videos to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
