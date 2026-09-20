"""
Fetch video metadata from a YouTube channel using the YouTube Data API v3.
Output: .tmp/channel_videos.json
"""

import os
import json
import argparse
from dotenv import load_dotenv
from googleapiclient.discovery import build

load_dotenv()

API_KEY = os.getenv("YOUTUBE_API_KEY")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", ".tmp", "channel_videos.json")


def get_channel_id(youtube, handle_or_id: str) -> str:
    if handle_or_id.startswith("UC"):
        return handle_or_id
    resp = youtube.search().list(q=handle_or_id, type="channel", part="id", maxResults=1).execute()
    items = resp.get("items", [])
    if not items:
        raise ValueError(f"Channel not found: {handle_or_id}")
    return items[0]["id"]["channelId"]


def fetch_videos(channel_id: str, max_results: int = 50) -> list[dict]:
    youtube = build("youtube", "v3", developerKey=API_KEY)
    videos = []
    next_page = None

    while True:
        resp = youtube.search().list(
            channelId=channel_id,
            part="id,snippet",
            order="date",
            type="video",
            maxResults=min(max_results - len(videos), 50),
            pageToken=next_page,
        ).execute()

        for item in resp.get("items", []):
            videos.append({
                "video_id": item["id"]["videoId"],
                "title": item["snippet"]["title"],
                "published_at": item["snippet"]["publishedAt"],
                "description": item["snippet"]["description"],
                "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
            })

        next_page = resp.get("nextPageToken")
        if not next_page or len(videos) >= max_results:
            break

    return videos


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("channel", help="Channel handle (@name) or ID (UCxxx)")
    parser.add_argument("--max", type=int, default=50, help="Max videos to fetch")
    args = parser.parse_args()

    youtube = build("youtube", "v3", developerKey=API_KEY)
    channel_id = get_channel_id(youtube, args.channel)
    videos = fetch_videos(channel_id, max_results=args.max)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(videos, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(videos)} videos to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
