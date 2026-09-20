"""
Analyze .tmp/ai_trends_data.json and compute engagement metrics, trending keywords,
content patterns, and channel comparisons.
Output: .tmp/ai_trends_analysis.json
"""

import os
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

INPUT_PATH = os.path.join(os.path.dirname(__file__), "..", ".tmp", "ai_trends_data.json")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", ".tmp", "ai_trends_analysis.json")

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "this", "that", "these",
    "those", "i", "my", "your", "his", "her", "its", "our", "their",
    "it", "he", "she", "we", "they", "you", "what", "how", "why", "when",
    "where", "which", "who", "all", "just", "so", "if", "not", "no", "new",
    "using", "use", "get", "make", "im", "youre", "its", "vs", "vs.",
}

CONTENT_TYPE_KEYWORDS = {
    "tutorial": ["tutorial", "how to", "guide", "learn", "course", "beginner", "step by step", "crash course"],
    "news": ["news", "update", "announced", "release", "launches", "just dropped", "breaking", "2025", "2024"],
    "review": ["review", "tested", "hands on", "honest", "worth it", "vs", "compared", "best"],
    "interview": ["interview", "conversation", "podcast", "talks with", "feat", "with", "ep."],
    "demo": ["demo", "build", "i built", "created", "making", "showcase", "live"],
}

DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def parse_dt(iso_str: str) -> datetime:
    return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))


def days_since(iso_str: str) -> float:
    dt = parse_dt(iso_str)
    now = datetime.now(timezone.utc)
    return (now - dt).total_seconds() / 86400


def engagement_rate(video: dict) -> float:
    views = video.get("view_count", 0)
    if views == 0:
        return 0.0
    return (video.get("like_count", 0) + video.get("comment_count", 0)) / views


def views_per_day(video: dict) -> float:
    age = days_since(video["published_at"])
    if age < 0.1:
        age = 0.1
    return video.get("view_count", 0) / age


def extract_keywords(title: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 2]


def classify_content_type(title: str) -> str:
    title_lower = title.lower()
    for ctype, keywords in CONTENT_TYPE_KEYWORDS.items():
        if any(kw in title_lower for kw in keywords):
            return ctype
    return "other"


def generate_insights(
    top_by_views: list[dict],
    top_by_engagement: list[dict],
    trending_keywords: list[dict],
    channel_stats: list[dict],
    upload_days: dict,
    content_types: dict,
) -> list[str]:
    insights = []

    if top_by_views:
        v = top_by_views[0]
        insights.append(
            f"Most viewed: \"{v['title'][:60]}\" by {v['channel_name']} "
            f"with {v['view_count']:,} views"
        )

    if top_by_engagement:
        e = top_by_engagement[0]
        rate_pct = e["engagement_rate"] * 100
        insights.append(
            f"Highest engagement: \"{e['title'][:60]}\" by {e['channel_name']} "
            f"({rate_pct:.1f}% engagement rate)"
        )

    if trending_keywords:
        top_kws = [k["keyword"] for k in trending_keywords[:5]]
        insights.append(f"Top trending keywords in titles: {', '.join(top_kws)}")

    best_day = max(upload_days, key=upload_days.get) if upload_days else None
    if best_day:
        insights.append(
            f"Most content uploaded on {best_day}s — consider posting on that day for maximum visibility"
        )

    top_type = max(content_types, key=content_types.get) if content_types else None
    if top_type:
        pct = content_types[top_type] / sum(content_types.values()) * 100
        insights.append(
            f"{top_type.title()} content dominates the niche ({pct:.0f}% of videos)"
        )

    if channel_stats:
        top_ch = max(channel_stats, key=lambda c: c["avg_views"])
        insights.append(
            f"Best performing channel by avg views: {top_ch['channel_name']} "
            f"({top_ch['avg_views']:,.0f} avg views/video)"
        )

    return insights


def main():
    if not os.path.exists(INPUT_PATH):
        raise FileNotFoundError(f"Input not found: {INPUT_PATH}. Run fetch_ai_trends.py first.")

    with open(INPUT_PATH, encoding="utf-8") as f:
        videos = json.load(f)

    print(f"Analyzing {len(videos)} videos...")

    # Enrich each video
    for v in videos:
        v["engagement_rate"] = round(engagement_rate(v), 4)
        v["days_since_published"] = round(days_since(v["published_at"]), 1)
        v["views_per_day"] = round(views_per_day(v), 0)
        v["content_type"] = classify_content_type(v["title"])

    # Top videos
    top_by_views = sorted(videos, key=lambda v: v["view_count"], reverse=True)[:15]
    top_by_engagement = sorted(
        [v for v in videos if v["view_count"] > 1000],
        key=lambda v: v["engagement_rate"],
        reverse=True
    )[:10]
    rising_fast = sorted(
        [v for v in videos if v["days_since_published"] <= 7],
        key=lambda v: v["views_per_day"],
        reverse=True
    )[:10]

    # Trending keywords
    all_keywords = []
    for v in videos:
        all_keywords.extend(extract_keywords(v["title"]))
    keyword_counts = Counter(all_keywords)
    trending_keywords = [
        {"keyword": kw, "count": cnt}
        for kw, cnt in keyword_counts.most_common(25)
    ]

    # Channel stats
    channel_data = defaultdict(lambda: {"views": [], "engagement_rates": [], "count": 0})
    for v in videos:
        ch = v["channel_name"]
        channel_data[ch]["views"].append(v["view_count"])
        channel_data[ch]["engagement_rates"].append(v["engagement_rate"])
        channel_data[ch]["count"] += 1

    channel_stats = []
    for name, data in channel_data.items():
        avg_views = sum(data["views"]) / len(data["views"]) if data["views"] else 0
        avg_eng = sum(data["engagement_rates"]) / len(data["engagement_rates"]) if data["engagement_rates"] else 0
        channel_stats.append({
            "channel_name": name,
            "video_count": data["count"],
            "avg_views": round(avg_views, 0),
            "avg_engagement_rate": round(avg_eng, 4),
            "total_views": sum(data["views"]),
        })
    channel_stats.sort(key=lambda c: c["total_views"], reverse=True)

    # Content type distribution
    type_counter = Counter(v["content_type"] for v in videos)
    content_type_distribution = dict(type_counter)

    # Upload day distribution
    day_counter = Counter()
    for v in videos:
        try:
            dt = parse_dt(v["published_at"])
            day_counter[DAYS_OF_WEEK[dt.weekday()]] += 1
        except Exception:
            pass
    upload_day_distribution = {day: day_counter.get(day, 0) for day in DAYS_OF_WEEK}

    # Key insights
    key_insights = generate_insights(
        top_by_views, top_by_engagement, trending_keywords,
        channel_stats, upload_day_distribution, content_type_distribution
    )

    # Build output
    analysis = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_videos_analyzed": len(videos),
        "key_insights": key_insights,
        "top_videos_by_views": top_by_views,
        "top_videos_by_engagement": top_by_engagement,
        "rising_fast": rising_fast,
        "trending_keywords": trending_keywords,
        "channel_stats": channel_stats,
        "content_type_distribution": content_type_distribution,
        "upload_day_distribution": upload_day_distribution,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)

    print(f"Analysis complete. Saved to {OUTPUT_PATH}")
    print(f"\nKey insights:")
    for insight in key_insights:
        print(f"  • {insight}")


if __name__ == "__main__":
    main()
