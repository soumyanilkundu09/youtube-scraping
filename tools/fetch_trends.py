"""
Fetch enriched video metadata for a topic profile (topics/<slug>.json).

  python tools/fetch_trends.py --topic ai_automation [--dry-run]

Discovery:
  - Channels: resolved with channels.list(forHandle=...) and listed through the channel's uploads
    playlist (playlistItems.list). These calls cost 1 unit each and, unlike search.list, return the
    channel's real latest uploads.
  - Keywords: search.list ordered by view count within the profile's lookback window.
    search.list has its own daily cap (100 calls/day, 1 unit each), tracked separately below.
  - All videos: videos.list (1 unit per request of up to 50 ids) for statistics, tags and duration.

Output: .tmp/<slug>/videos.json and .tmp/<slug>/fetch_manifest.json
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

sys.path.insert(0, os.path.dirname(__file__))
import common  # noqa: E402

load_dotenv()

API_KEY = os.getenv("YOUTUBE_API_KEY")
# Abort before spending anything if the estimate exceeds these (override via env).
SEARCH_CALL_BUDGET = int(os.getenv("SEARCH_CALL_BUDGET", "60"))   # hard daily cap is 100
UNIT_BUDGET = int(os.getenv("QUOTA_UNIT_BUDGET", "3000"))         # daily free quota is 10,000
MIN_HEALTHY_CHANNEL_VIDEOS = 10


class Quota:
    def __init__(self):
        self.units = 0
        self.search_calls = 0

    def unit(self, n: int = 1):
        self.units += n

    def search(self):
        self.search_calls += 1


def estimate_cost(profile: dict) -> tuple[int, int]:
    """(units, search_calls) this profile will use, as a slight over-estimate."""
    n_ch = len(profile["channels"])
    per_ch = 1 + 2 * math.ceil(profile["videos_per_channel"] / 50)          # resolve + playlist + videos
    kw = len(profile["keyword_searches"])
    kw_videos = kw * math.ceil(profile["videos_per_search"] / 50)
    channel_stat_batches = math.ceil((n_ch * profile["videos_per_channel"] + kw * profile["videos_per_search"]) / 50)
    units = n_ch * per_ch + kw_videos + channel_stat_batches + kw  # +kw: search calls also cost 1 unit each
    return units, kw


# ---------------------------------------------------------------------------
# YouTube calls
# ---------------------------------------------------------------------------

def resolve_channel(youtube, handle_or_id: str, quota: Quota) -> dict | None:
    """Return {channel_id, name, uploads_playlist, subscribers} or None if the channel isn't found."""
    kwargs = {"part": "snippet,contentDetails,statistics"}
    if handle_or_id.startswith("UC"):
        kwargs["id"] = handle_or_id
    else:
        kwargs["forHandle"] = handle_or_id
    resp = common.call_with_retry(youtube.channels().list(**kwargs))
    quota.unit()
    items = resp.get("items", [])
    if not items:
        return None
    item = items[0]
    stats = item.get("statistics", {})
    return {
        "channel_id": item["id"],
        "name": item["snippet"]["title"],
        "uploads_playlist": item["contentDetails"]["relatedPlaylists"]["uploads"],
        "subscribers": None if stats.get("hiddenSubscriberCount") else int(stats.get("subscriberCount", 0)),
    }


def list_uploads(youtube, playlist_id: str, max_results: int, quota: Quota) -> list[str]:
    """Latest video IDs from an uploads playlist (newest first)."""
    video_ids, page = [], None
    while len(video_ids) < max_results:
        resp = common.call_with_retry(youtube.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=min(max_results - len(video_ids), 50),
            pageToken=page,
        ))
        quota.unit()
        video_ids += [i["contentDetails"]["videoId"] for i in resp.get("items", [])]
        page = resp.get("nextPageToken")
        if not page:
            break
    return video_ids


def search_keyword_videos(youtube, query: str, profile: dict, quota: Quota) -> list[str]:
    since = (datetime.now(timezone.utc) - timedelta(days=profile["lookback_days"])).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = dict(
        q=query, part="id", order="viewCount", type="video",
        maxResults=min(profile["videos_per_search"], 50), publishedAfter=since,
    )
    if profile.get("language"):
        params["relevanceLanguage"] = profile["language"]
    if profile.get("region"):
        params["regionCode"] = profile["region"]
    resp = common.call_with_retry(youtube.search().list(**params))
    quota.unit()
    quota.search()
    return [i["id"]["videoId"] for i in resp.get("items", [])]


def fetch_video_details(youtube, video_ids: list[str], profile: dict, quota: Quota) -> list[dict]:
    results = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        resp = common.call_with_retry(youtube.videos().list(
            part="snippet,statistics,contentDetails", id=",".join(batch)
        ))
        quota.unit()
        for item in resp.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            duration = iso_duration_to_seconds(item.get("contentDetails", {}).get("duration", "PT0S"))
            results.append({
                "video_id": item["id"],
                "title": snippet.get("title", ""),
                "channel_name": snippet.get("channelTitle", ""),
                "channel_id": snippet.get("channelId", ""),
                "published_at": snippet.get("publishedAt", ""),
                "description": snippet.get("description", "")[:500],
                "tags": snippet.get("tags", [])[:15],
                "category_id": snippet.get("categoryId", ""),
                "default_language": snippet.get("defaultAudioLanguage") or snippet.get("defaultLanguage", ""),
                "thumbnail_url": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                "url": f"https://www.youtube.com/watch?v={item['id']}",
                "view_count": int(stats.get("viewCount", 0)),
                "like_count": int(stats.get("likeCount", 0)),
                "comment_count": int(stats.get("commentCount", 0)),
                "duration_seconds": duration,
                "is_short": duration <= profile["shorts_max_seconds"],
            })
    return results


def fetch_subscriber_counts(youtube, channel_ids: list[str], quota: Quota) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    ids = sorted(set(channel_ids))
    for i in range(0, len(ids), 50):
        resp = common.call_with_retry(youtube.channels().list(part="statistics", id=",".join(ids[i:i + 50])))
        quota.unit()
        for item in resp.get("items", []):
            stats = item.get("statistics", {})
            out[item["id"]] = None if stats.get("hiddenSubscriberCount") else int(stats.get("subscriberCount", 0))
    return out


def iso_duration_to_seconds(duration: str) -> int:
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    slug = common.parse_topic_arg()
    profile = common.load_profile(slug)
    dry_run = "--dry-run" in sys.argv

    est_units, est_searches = estimate_cost(profile)
    print(f"Topic: {profile['display_name']} ({slug})")
    print(f"Estimated cost: ~{est_units} units of the 10,000/day free quota, "
          f"{est_searches} search.list calls (separate cap of 100/day)")
    if est_searches > SEARCH_CALL_BUDGET or est_units > UNIT_BUDGET:
        sys.exit(f"Estimate exceeds the budget (search calls <= {SEARCH_CALL_BUDGET}, units <= {UNIT_BUDGET}). "
                 "Trim the profile or raise SEARCH_CALL_BUDGET / QUOTA_UNIT_BUDGET.")
    if dry_run:
        print("Dry run: nothing fetched.")
        return
    if not API_KEY:
        raise ValueError("YOUTUBE_API_KEY not set (in .env locally, or in the Modal Secret)")

    youtube = build("youtube", "v3", developerKey=API_KEY)
    quota = Quota()
    exclude_rx = common.compile_terms(profile["exclude"])
    include_rx = common.compile_terms(profile["must_include"])
    all_videos: dict[str, dict] = {}
    manifest = {"topic": slug, "fetched_at": datetime.now(timezone.utc).isoformat(), "channels": [], "keywords": [],
                "warnings": []}

    # --- Channels -----------------------------------------------------------
    print(f"\nChannels ({len(profile['channels'])}):")
    for handle in profile["channels"]:
        entry = {"handle": handle, "status": "ok", "videos_fetched": 0}
        try:
            info = resolve_channel(youtube, handle, quota)
            if not info:
                entry["status"] = "not_found"
                manifest["warnings"].append(f"Channel not found: {handle}")
                print(f"  {handle}: NOT FOUND")
                manifest["channels"].append(entry)
                continue
            entry.update(channel_id=info["channel_id"], name=info["name"], subscribers=info["subscribers"])
            ids = list_uploads(youtube, info["uploads_playlist"], profile["videos_per_channel"], quota)
            videos = fetch_video_details(youtube, ids, profile, quota)
        except common.QuotaExceeded:
            raise
        except HttpError as e:
            entry["status"] = f"error_{getattr(e.resp, 'status', '?')}"
            manifest["warnings"].append(f"{handle}: API error {getattr(e.resp, 'status', '?')}")
            print(f"  {handle}: API error {getattr(e.resp, 'status', '?')}, skipped")
            manifest["channels"].append(entry)
            continue

        kept = 0
        entry["videos_listed"] = len(videos)
        for v in videos:
            text = common.video_text(v)
            if exclude_rx and exclude_rx.search(text):
                continue
            # General-interest channels (podcasts, broad tech) can be filtered to on-topic videos only
            if profile["filter_channel_videos"] and include_rx and not include_rx.search(text):
                continue
            v["source"], v["search_query"] = "channel", handle
            all_videos[v["video_id"]] = v
            kept += 1
        entry["videos_fetched"] = kept
        # Judge health by videos listed; a low kept count is expected when filter_channel_videos is on
        if len(videos) < min(MIN_HEALTHY_CHANNEL_VIDEOS, profile["videos_per_channel"]):
            manifest["warnings"].append(f"{handle} listed only {len(videos)} videos")
        print(f"  {handle}: {kept} kept of {len(videos)} listed ({info['name']})")
        manifest["channels"].append(entry)

    # --- Keyword searches -----------------------------------------------------
    print(f"\nKeyword searches ({len(profile['keyword_searches'])}):")
    for query in profile["keyword_searches"]:
        ids = search_keyword_videos(youtube, query, profile, quota)
        videos = fetch_video_details(youtube, ids, profile, quota)
        kept = 0
        for v in videos:
            text = common.video_text(v)
            if exclude_rx and exclude_rx.search(text):
                continue
            if include_rx and not include_rx.search(text):
                continue
            if v["video_id"] not in all_videos:
                v["source"], v["search_query"] = "keyword_search", query
                all_videos[v["video_id"]] = v
                kept += 1
        manifest["keywords"].append({"query": query, "found": len(ids), "new_kept": kept})
        print(f"  '{query}': {len(ids)} found, {kept} new after filters ({len(all_videos)} total)")

    # --- Channel subscriber counts (used for outlier and discovery analysis) ------
    subs = fetch_subscriber_counts(youtube, [v["channel_id"] for v in all_videos.values()], quota)
    for v in all_videos.values():
        v["channel_subscribers"] = subs.get(v["channel_id"])

    result = list(all_videos.values())
    with open(common.videos_path(slug), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    manifest["total_videos"] = len(result)
    manifest["quota"] = {"units": quota.units, "search_calls": quota.search_calls}
    with open(common.manifest_path(slug), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"\nDone. {len(result)} unique videos -> {common.videos_path(slug)}")
    print(f"Quota used: ~{quota.units} units, {quota.search_calls} search calls")
    for w in manifest["warnings"]:
        print(f"  WARNING: {w}")


if __name__ == "__main__":
    main()
