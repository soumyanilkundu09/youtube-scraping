"""
Analyze .tmp/<slug>/videos.json for a topic and compute engagement metrics, outliers, phrases,
skills, topic clusters, format/timing performance and channel candidates.

  python tools/analyze_trends.py --topic ai_automation

Output: .tmp/<slug>/analysis.json
"""

import json
import math
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import common  # noqa: E402

MIN_N = 5            # minimum sample before a performance claim is made
MIN_CLUSTER_VIDEOS = 30
MIN_CLUSTER_SIZE = 4
MIN_LIFT = 1.2        # a 'best' day/length/type must beat channel norms by this factor to be called out
MIN_RELATIVE_SMALL = 3  # channel-relative videos needed for a skill/cluster performance figure

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "this", "that", "these",
    "those", "i", "my", "your", "his", "her", "its", "our", "their",
    "it", "he", "she", "we", "they", "you", "what", "how", "why", "when",
    "where", "which", "who", "all", "just", "so", "if", "not", "no", "new",
    "using", "use", "get", "make", "im", "youre", "vs", "than", "then",
    "into", "about", "out", "up", "more", "most", "now", "will", "way",
    "video", "videos", "full", "free", "official", "live", "ft", "feat",
    "part", "episode", "ep", "s", "t", "m",
}

# Words that add noise to clustering because they come from description boilerplate and URLs.
CLUSTER_STOPWORDS = STOPWORDS | {
    "http", "https", "www", "com", "youtube", "subscribe", "follow", "instagram", "twitter",
    "link", "links", "discord", "channel", "patreon", "facebook", "tiktok", "bit", "ly", "watch",
    "like", "comment", "share", "join", "click", "check", "week", "today",
}

# Ordered: first matching type wins. A profile's `content_types` are checked first.
DEFAULT_CONTENT_TYPES = {
    "tutorial": ["tutorial", "how to", "guide", "learn", "course", "beginner", "beginners",
                 "step by step", "crash course", "walkthrough"],
    "explainer": ["explained", "explainer", "what is", "what are", "deep dive"],
    "news": ["news", "update", "updates", "announced", "announces", "released", "launches",
             "launched", "just dropped", "breaking"],
    "review": ["review", "tested", "hands on", "hands-on", "honest", "worth it", "comparison",
               "compared", "vs", "versus"],
    "interview": ["interview", "conversation", "podcast", "fireside", "talks with"],
    "roundup": ["best", "top", "ways to", "things", "mistakes", "tips", "secrets", "hacks", "tools"],
    "demo": ["demo", "i built", "i made", "let's build", "building", "build", "showcase"],
}

DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

DURATION_BUCKETS = [
    (0, 60, "<1 min"), (60, 300, "1-5 min"), (300, 600, "5-10 min"),
    (600, 1200, "10-20 min"), (1200, 2400, "20-40 min"), (2400, math.inf, "40+ min"),
]


# ---------------------------------------------------------------------------
# Per-video metrics
# ---------------------------------------------------------------------------

def parse_dt(iso_str: str) -> datetime:
    return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))


def days_since(iso_str: str) -> float:
    return (datetime.now(timezone.utc) - parse_dt(iso_str)).total_seconds() / 86400


def engagement_rate(video: dict) -> float:
    views = video.get("view_count", 0)
    return 0.0 if views == 0 else (video.get("like_count", 0) + video.get("comment_count", 0)) / views


def views_per_day(video: dict) -> float:
    # Floor the age at one day so a video published an hour ago doesn't look 24x more viral.
    return video.get("view_count", 0) / max(days_since(video["published_at"]), 1.0)


def compile_content_types(profile: dict) -> list[tuple[str, object]]:
    merged = {**profile.get("content_types", {})}
    for name, phrases in DEFAULT_CONTENT_TYPES.items():
        if name not in merged:
            merged[name] = phrases
    return [(name, common.compile_terms(phrases)) for name, phrases in merged.items()]


def classify_content_type(title: str, compiled: list[tuple[str, object]]) -> str:
    text = title.lower()
    for name, rx in compiled:
        if rx and rx.search(text):
            return name
    return "other"


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def assign_outliers(videos: list[dict]) -> None:
    """
    outlier_score = views / typical views for that channel (median of its videos in this dataset).
    Falls back channel+format -> channel -> topic-wide for the same format when a channel has
    fewer than MIN_N videos. `outlier_basis` records which one was used.
    """
    groups_cf, groups_c, groups_f = defaultdict(list), defaultdict(list), defaultdict(list)
    for v in videos:
        groups_cf[(v["channel_id"], v["is_short"])].append(v["view_count"])
        groups_c[v["channel_id"]].append(v["view_count"])
        groups_f[v["is_short"]].append(v["view_count"])
    for v in videos:
        candidates = [
            ("channel_format", groups_cf[(v["channel_id"], v["is_short"])]),
            ("channel", groups_c[v["channel_id"]]),
            ("topic", groups_f[v["is_short"]]),
        ]
        for basis, values in candidates:
            if len(values) >= MIN_N or basis == "topic":
                base = median(values) or 0
                v["outlier_score"] = round(v["view_count"] / base, 2) if base else 0.0
                v["outlier_basis"] = basis
                break


def channel_relative(videos: list[dict]) -> list[dict]:
    """
    Videos whose outlier_score is measured against their own channel's norm. Videos scored against the
    topic-wide median (tiny channels) are left out of performance medians: almost any small-channel
    video looks like a 0.01x flop against that baseline, which would bias skills and clusters.
    """
    return [v for v in videos if v.get("outlier_basis") != "topic"]


def duration_bucket(seconds: int) -> str:
    for lo, hi, label in DURATION_BUCKETS:
        if lo <= seconds < hi:
            return label
    return DURATION_BUCKETS[-1][2]


# ---------------------------------------------------------------------------
# Phrases
# ---------------------------------------------------------------------------

def channel_tokens(video: dict) -> set[str]:
    """Words of the video's own channel name (3+ chars), so 'lex fridman' isn't reported as a trend."""
    return {t for t in re.findall(r"[a-z0-9]+", video.get("channel_name", "").lower()) if len(t) >= 3}


def extract_phrases(title: str, skip: frozenset | set = frozenset()) -> tuple[set[str], set[str]]:
    """(unigrams, bigrams) of a title. Bigrams are adjacent real words, never bridged over stopwords."""
    toks = re.findall(r"[a-z0-9]+", title.lower())

    def ok(t: str) -> bool:
        return t not in STOPWORDS and t not in skip and len(t) >= 2 and not t.isdigit()

    unigrams = {t for t in toks if ok(t)}
    bigrams = {f"{a} {b}" for a, b in zip(toks, toks[1:]) if ok(a) and ok(b)}
    return unigrams, bigrams


def phrase_rows(videos: list[dict], min_df: int) -> tuple[list[dict], list[dict]]:
    uni_map, bi_map = defaultdict(list), defaultdict(list)
    for v in videos:
        uni, bi = extract_phrases(v["title"], channel_tokens(v))
        for p in uni:
            uni_map[p].append(v)
        for p in bi:
            bi_map[p].append(v)

    def rows(m: dict) -> list[dict]:
        out = []
        for phrase, vs in m.items():
            if len(vs) < min_df:
                continue
            out.append({
                "phrase": phrase,
                "video_count": len(vs),
                "share": round(len(vs) / len(videos), 4),
                "median_views_per_day": round(median([x["views_per_day"] for x in vs]) or 0),
                "total_views": sum(x["view_count"] for x in vs),
            })
        out.sort(key=lambda r: (r["video_count"], r["total_views"]), reverse=True)
        return out

    return rows(uni_map), rows(bi_map)


def top_videos_for_phrase(videos: list[dict], phrase: str, n: int = 3) -> list[dict]:
    rx = common.compile_terms([phrase])
    hits = [v for v in videos if rx.search(v["title"].lower())]
    return sorted(hits, key=lambda v: v["view_count"], reverse=True)[:n]


# ---------------------------------------------------------------------------
# Skills, clusters, channels
# ---------------------------------------------------------------------------

def skill_stats(videos: list[dict], skills: dict) -> list[dict]:
    texts = [(v, common.video_text(v)) for v in videos]
    rows = []
    for name, terms in skills.items():
        rx = common.compile_terms(terms)
        hits = [v for v, text in texts if rx and rx.search(text)]
        row = {"skill": name, "video_count": len(hits), "share": round(len(hits) / len(videos), 4),
               "median_views_per_day": None, "median_outlier": None, "total_views": 0, "top_video": None}
        if hits:
            row["median_views_per_day"] = round(median([v["views_per_day"] for v in hits]))
            rel = channel_relative(hits)
            row["median_outlier"] = (round(median([v["outlier_score"] for v in rel]), 2)
                                     if len(rel) >= MIN_RELATIVE_SMALL else None)
            row["total_views"] = sum(v["view_count"] for v in hits)
            best = max(hits, key=lambda v: v["view_count"])
            row["top_video"] = {"title": best["title"], "channel_name": best["channel_name"],
                                "view_count": best["view_count"], "url": best["url"]}
        rows.append(row)
    rows.sort(key=lambda r: (r["video_count"], r["total_views"]), reverse=True)
    return rows


def build_clusters(videos: list[dict]) -> tuple[list[dict], str | None]:
    """TF-IDF + KMeans over title/tags/description. Returns (clusters, skip_reason)."""
    if len(videos) < MIN_CLUSTER_VIDEOS:
        return [], f"needs at least {MIN_CLUSTER_VIDEOS} videos (have {len(videos)})"
    try:
        from sklearn.cluster import KMeans
        from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
    except ImportError:
        return [], "scikit-learn is not installed"

    # Title and tags only: descriptions are mostly channel promo boilerplate.
    texts = []
    for v in videos:
        text = f"{v['title']} {' '.join(v.get('tags', [])[:8])}".lower()
        for tok in channel_tokens(v):
            text = re.sub(rf"{re.escape(tok)}", " ", text)
        texts.append(text)
    vec = TfidfVectorizer(
        stop_words=sorted(set(ENGLISH_STOP_WORDS) | CLUSTER_STOPWORDS),
        ngram_range=(1, 2), min_df=2, max_df=0.4, sublinear_tf=True,
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9]+\b",
    )
    try:
        X = vec.fit_transform(texts)
    except ValueError:
        return [], "not enough distinct vocabulary"
    if X.shape[1] < 10:
        return [], "not enough distinct vocabulary"

    k = max(3, min(14, round(math.sqrt(len(videos) / 2))))
    km = KMeans(n_clusters=k, n_init=10, random_state=42).fit(X)
    terms = vec.get_feature_names_out()

    clusters = []
    for c in range(k):
        members = [v for v, lab in zip(videos, km.labels_) if lab == c]
        if len(members) < MIN_CLUSTER_SIZE:
            continue
        order = km.cluster_centers_[c].argsort()[::-1][:12]
        chosen: list[str] = []
        for t in (terms[i] for i in order):
            if any(t in ch or ch in t for ch in chosen):
                continue
            chosen.append(t)
            if len(chosen) == 3:
                break
        label = ", ".join(chosen)
        for v in members:
            v["cluster"] = label
        mature = [v for v in members if v["days_since_published"] >= 2]
        ranked = sorted(mature or members, key=lambda v: v["outlier_score"], reverse=True)[:3]
        clusters.append({
            "label": label,
            "video_count": len(members),
            "total_views": sum(v["view_count"] for v in members),
            "median_views_per_day": round(median([v["views_per_day"] for v in members])),
            "median_outlier": (round(median([v["outlier_score"] for v in channel_relative(members)]), 2)
                               if len(channel_relative(members)) >= MIN_RELATIVE_SMALL else None),
            "top_videos": [{"title": v["title"], "channel_name": v["channel_name"], "view_count": v["view_count"],
                            "outlier_score": v["outlier_score"], "url": v["url"]} for v in ranked],
        })
    clusters.sort(key=lambda c: c["total_views"], reverse=True)
    return clusters, None


def channel_stats(videos: list[dict], profile_channel_ids: set[str]) -> list[dict]:
    by_ch = defaultdict(list)
    for v in videos:
        by_ch[v["channel_id"]].append(v)
    rows = []
    for ch_id, vs in by_ch.items():
        views = [v["view_count"] for v in vs]
        rows.append({
            "channel_name": vs[0]["channel_name"],
            "channel_id": ch_id,
            "in_profile": ch_id in profile_channel_ids,
            "subscribers": vs[0].get("channel_subscribers"),
            "video_count": len(vs),
            "total_views": sum(views),
            "avg_views": round(sum(views) / len(views)),
            "median_views": round(median(views)),
            "avg_engagement_rate": round(sum(v["engagement_rate"] for v in vs) / len(vs), 4),
        })
    rows.sort(key=lambda r: r["total_views"], reverse=True)
    return rows


def channel_candidates(stats: list[dict], limit: int = 15) -> list[dict]:
    """Channels seen in keyword results that aren't already tracked, ranked by appearances x typical views."""
    out = []
    for c in stats:
        if c["in_profile"]:
            continue
        row = dict(c)
        row["score"] = c["video_count"] * c["median_views"]
        subs = c.get("subscribers")
        row["views_per_subscriber"] = round(c["median_views"] / subs, 2) if subs else None
        out.append(row)
    out.sort(key=lambda r: (r["video_count"] >= 2, r["score"], r["total_views"]), reverse=True)
    return out[:limit]


# ---------------------------------------------------------------------------
# Format and timing performance
# ---------------------------------------------------------------------------

def group_performance(videos: list[dict], key_fn, order: list[str] | None = None) -> list[dict]:
    """Median outlier_score and views/day per group; groups under MIN_N are marked insufficient."""
    groups = defaultdict(list)
    for v in videos:
        groups[key_fn(v)].append(v)
    keys = order if order is not None else sorted(groups)
    rows = []
    for k in keys:
        vs = groups.get(k, [])
        rel = channel_relative(vs)
        rows.append({
            "group": k,
            "video_count": len(vs),
            "n_relative": len(rel),
            "median_outlier": round(median([v["outlier_score"] for v in rel]), 2) if len(rel) >= MIN_N else None,
            "median_views_per_day": round(median([v["views_per_day"] for v in vs])) if len(vs) >= MIN_N else None,
            "sufficient": len(rel) >= MIN_N,
        })
    return rows


def best_group(rows: list[dict], min_lift: float = MIN_LIFT) -> dict | None:
    valid = [r for r in rows if r["sufficient"] and r["median_outlier"] is not None]
    best = max(valid, key=lambda r: r["median_outlier"]) if valid else None
    return best if best and best["median_outlier"] >= min_lift else None


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------

def generate_insights(a: dict) -> list[str]:
    out = []
    if a["top_videos_by_views"]:
        v = a["top_videos_by_views"][0]
        out.append(f"Most viewed: \"{v['title'][:60]}\" by {v['channel_name']} with {v['view_count']:,} views")
    if a["breakout_videos"]:
        v = a["breakout_videos"][0]
        out.append(f"Biggest breakout: \"{v['title'][:60]}\" by {v['channel_name']} got "
                   f"{v['outlier_score']:.1f}x its channel's typical views")
    if a["trending_phrases"]:
        out.append("Most common title phrases: " + ", ".join(p["phrase"] for p in a["trending_phrases"][:5]))
    skills = [s for s in a["skills"] if s["video_count"] > 0]
    if skills:
        s = skills[0]
        out.append(f"Most covered skill/tool: {s['skill']} ({s['video_count']} videos, "
                   f"{s['share'] * 100:.0f}% of the sample)")
    best_len = best_group(a["performance_by_duration"])
    if best_len:
        out.append(f"Best-performing length: {best_len['group']} videos run at "
                   f"{best_len['median_outlier']:.1f}x their channel's typical views (n={best_len['n_relative']})")
    best_day = best_group(a["performance_by_weekday"])
    if best_day:
        out.append(f"Best publish day: {best_day['group']} (median {best_day['median_outlier']:.1f}x typical views, "
                   f"n={best_day['n_relative']}, UTC)")
    if not best_len and not best_day and (a["performance_by_duration"] or a["performance_by_weekday"]):
        out.append("No publish day or video length stands out: all measured groups sit within about 20% of "
                   "their channels' typical views")
    fmt = a["format_split"]
    if fmt["short"]["video_count"] and fmt["long"]["video_count"]:
        share = fmt["short"]["video_count"] / a["total_videos_analyzed"] * 100
        out.append(f"Shorts make up {share:.0f}% of the sample; long-form median is "
                   f"{fmt['long']['median_views']:,} views vs {fmt['short']['median_views']:,} for Shorts")
    if a["top_videos_by_engagement"]:
        e = a["top_videos_by_engagement"][0]
        out.append(f"Highest engagement: \"{e['title'][:60]}\" by {e['channel_name']} "
                   f"({e['engagement_rate'] * 100:.1f}% engagement rate)")
    established = [c for c in a["channel_stats"] if c["video_count"] >= 3]
    if established:
        top_ch = max(established, key=lambda c: c["avg_views"])
        out.append(f"Best channel by average views: {top_ch['channel_name']} ({top_ch['avg_views']:,.0f} per video, "
                   f"{top_ch['video_count']} videos sampled)")
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    slug = common.parse_topic_arg()
    profile = common.load_profile(slug)
    vpath = common.videos_path(slug)
    if not os.path.exists(vpath):
        sys.exit(f"Input not found: {vpath}. Run fetch_trends.py --topic {slug} first.")
    with open(vpath, encoding="utf-8") as f:
        videos = json.load(f)
    if not videos:
        sys.exit("No videos to analyze. Check the topic profile filters and the fetch output.")

    print(f"Analyzing {len(videos)} videos for '{profile['display_name']}'...")
    compiled_types = compile_content_types(profile)
    for v in videos:
        v.setdefault("tags", [])
        v.setdefault("is_short", v.get("duration_seconds", 0) <= profile["shorts_max_seconds"])
        v.setdefault("channel_subscribers", None)
        v["engagement_rate"] = round(engagement_rate(v), 4)
        v["days_since_published"] = round(days_since(v["published_at"]), 1)
        v["views_per_day"] = round(views_per_day(v))
        v["content_type"] = classify_content_type(v["title"], compiled_types)
        v["duration_bucket"] = duration_bucket(v.get("duration_seconds", 0))
        v["weekday"] = DAYS_OF_WEEK[parse_dt(v["published_at"]).weekday()]
        v["cluster"] = ""
    assign_outliers(videos)

    mature = [v for v in videos if v["days_since_published"] >= 2]

    top_by_views = sorted(videos, key=lambda v: v["view_count"], reverse=True)[:15]
    top_by_engagement = sorted([v for v in videos if v["view_count"] > 1000],
                               key=lambda v: v["engagement_rate"], reverse=True)[:10]
    rising_fast = sorted([v for v in videos if v["days_since_published"] <= 7],
                         key=lambda v: v["views_per_day"], reverse=True)[:10]
    breakout = sorted([v for v in mature if v["view_count"] >= 1000],
                      key=lambda v: v["outlier_score"], reverse=True)[:10]

    min_df = 3 if len(videos) >= 100 else 2
    uni_rows, bi_rows = phrase_rows(videos, min_df)
    trending_keywords = [{"keyword": r["phrase"], "count": r["video_count"]} for r in uni_rows[:25]]
    snapshot = sorted(
        [dict(r, kind="word") for r in uni_rows] + [dict(r, kind="phrase") for r in bi_rows],
        key=lambda r: r["video_count"], reverse=True,
    )[:200]
    phrase_videos = {
        r["phrase"]: [{"title": v["title"], "channel_name": v["channel_name"],
                       "view_count": v["view_count"], "url": v["url"]}
                      for v in top_videos_for_phrase(videos, r["phrase"])]
        for r in bi_rows[:8]
    }

    profile_channel_ids = {v["channel_id"] for v in videos if v.get("source") == "channel"}
    ch_stats = channel_stats(videos, profile_channel_ids)

    clusters, cluster_skip = build_clusters(videos)
    if cluster_skip:
        print(f"  Clusters skipped: {cluster_skip}")

    long_form = [v for v in videos if not v["is_short"]]
    shorts = [v for v in videos if v["is_short"]]

    def fmt_stats(vs: list[dict]) -> dict:
        return {
            "video_count": len(vs),
            "median_views": round(median([v["view_count"] for v in vs])) if vs else 0,
            "median_views_per_day": round(median([v["views_per_day"] for v in vs])) if vs else 0,
            "avg_engagement_rate": round(sum(v["engagement_rate"] for v in vs) / len(vs), 4) if vs else 0,
        }

    manifest = {}
    mpath = common.manifest_path(slug)
    if os.path.exists(mpath):
        with open(mpath, encoding="utf-8") as f:
            manifest = json.load(f)

    analysis = {
        "topic": slug,
        "display_name": profile["display_name"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lookback_days": profile["lookback_days"],
        "total_videos_analyzed": len(videos),
        "channels_tracked": len(profile["channels"]),
        "fetch_warnings": manifest.get("warnings", []),
        "top_videos_by_views": top_by_views,
        "top_videos_by_engagement": top_by_engagement,
        "rising_fast": rising_fast,
        "breakout_videos": breakout,
        "trending_keywords": trending_keywords,
        "trending_phrases": bi_rows[:20],
        "phrase_videos": phrase_videos,
        "phrase_snapshot": snapshot,
        "skills": skill_stats(videos, profile["skills"]),
        "clusters": clusters,
        "clusters_skipped_reason": cluster_skip,
        "channel_stats": ch_stats,
        "channel_candidates": channel_candidates(ch_stats),
        "content_type_distribution": dict(Counter(v["content_type"] for v in videos)),
        "performance_by_content_type": group_performance(
            mature, lambda v: v["content_type"], sorted({v["content_type"] for v in mature})),
        "upload_day_distribution": {d: sum(1 for v in videos if v["weekday"] == d) for d in DAYS_OF_WEEK},
        "performance_by_weekday": group_performance([v for v in mature if not v["is_short"]],
                                                    lambda v: v["weekday"], DAYS_OF_WEEK),
        "performance_by_duration": group_performance(mature, lambda v: v["duration_bucket"],
                                                     [b[2] for b in DURATION_BUCKETS]),
        "format_split": {"long": fmt_stats(long_form), "short": fmt_stats(shorts)},
        "emerging_topics": [],
        "history_note": "History tracking has not run.",
        "videos": videos,
    }
    analysis["key_insights"] = generate_insights(analysis)

    with open(common.analysis_path(slug), "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)

    print(f"Analysis complete. Saved to {common.analysis_path(slug)}")
    print("\nKey insights:")
    for insight in analysis["key_insights"]:
        print(f"  - {insight}")


if __name__ == "__main__":
    main()
