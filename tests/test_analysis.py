"""
Pure-function checks for the analysis and history logic (no network, no API quota).

  python -m pytest tests -q        (or: python tests/test_analysis.py)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import analyze_trends as at  # noqa: E402
import common  # noqa: E402
import track_history as th  # noqa: E402


def make_video(i, channel="c1", views=1000, short=False, title="A video", days_old=10):
    return {
        "video_id": f"v{i}", "title": title, "channel_id": channel, "channel_name": channel,
        "view_count": views, "is_short": short, "published_at": "2026-01-01T00:00:00Z",
        "description": "", "tags": [],
    }


def test_content_type_word_boundaries():
    compiled = at.compile_content_types({"content_types": {}})
    assert at.classify_content_type("Blender Tutorial for Beginners", compiled) == "tutorial"
    # "with" / "without" must not classify as interview, and years must not classify as news
    assert at.classify_content_type("Working without limits in 2025", compiled) == "other"
    assert at.classify_content_type("Lex talks with Sam: podcast", compiled) == "interview"


def test_profile_content_types_take_priority():
    compiled = at.compile_content_types({"content_types": {"showcase": ["short film"]}})
    assert at.classify_content_type("My short film tutorial", compiled) == "showcase"


def test_phrase_extraction_skips_stopwords_and_channel_name():
    uni, bi = at.extract_phrases("Claude Code and the Future of AI Agents")
    assert "claude code" in bi and "ai agents" in bi
    assert "and the" not in bi and "code and" not in bi  # never bridged over stopwords
    uni2, bi2 = at.extract_phrases("Lex Fridman Podcast about AI", {"lex", "fridman"})
    assert "lex fridman" not in bi2 and "fridman" not in uni2


def test_outlier_score_uses_channel_median_when_enough_videos():
    vids = [make_video(i, "big", views=v) for i, v in enumerate([100, 100, 100, 100, 1000])]
    at.assign_outliers(vids)
    assert vids[-1]["outlier_score"] == 10.0
    assert vids[-1]["outlier_basis"] == "channel_format"


def test_outlier_falls_back_to_topic_median_for_small_channels():
    vids = [make_video(i, f"c{i}", views=100) for i in range(6)] + [make_video(99, "tiny", views=500)]
    at.assign_outliers(vids)
    tiny = vids[-1]
    assert tiny["outlier_basis"] == "topic" and tiny["outlier_score"] == 5.0


def test_group_performance_marks_small_groups_insufficient():
    vids = [make_video(i, views=100) for i in range(3)]
    for v in vids:
        v.update(outlier_score=2.0, outlier_basis="channel", views_per_day=5, weekday="Monday")
    rows = at.group_performance(vids, lambda v: v["weekday"], ["Monday", "Tuesday"])
    assert rows[0]["sufficient"] is False and rows[0]["median_outlier"] is None
    assert at.best_group(rows) is None


def test_compile_terms_matches_whole_words_only():
    rx = common.compile_terms(["ai", "after effects"])
    assert rx.search("learn ai today") and rx.search("after effects tips")
    assert not rx.search("training rain")  # 'ai' inside other words must not match


def test_version_terms_do_not_match_longer_versions():
    rx = common.compile_terms(["seedance 2"])
    assert rx.search("seedance 2 is here") and rx.search("try seedance 2.")
    assert not rx.search("seedance 2.5 review")


def test_history_deltas_flag_new_rising_and_cooling():
    prev = {"claude code": {"video_count": 8, "share": 0.02},
            "old topic": {"video_count": 12, "share": 0.03}}
    cur = [{"phrase": "claude code", "video_count": 16, "share": 0.04, "kind": "phrase"},
           {"phrase": "nano banana", "video_count": 6, "share": 0.015, "kind": "phrase"},
           {"phrase": "tiny", "video_count": 2, "share": 0.005, "kind": "phrase"}]
    emerging, cooling = th.compute_deltas(cur, prev)
    status = {e["phrase"]: e["status"] for e in emerging}
    assert status == {"claude code": "rising", "nano banana": "new"}  # 'tiny' is below the minimum count
    assert [c["phrase"] for c in cooling] == ["old topic"]


def test_history_parse_round_trip():
    rows = [th.HISTORY_HEADERS, ["2026-09-13", "claude code", "phrase", "8", "0.02", "400"]]
    parsed = th.parse_history(rows)
    assert parsed["2026-09-13"]["claude code"]["video_count"] == 8


def test_profiles_are_valid():
    for slug in ("ai_automation", "animation"):
        profile = common.load_profile(slug)
        assert profile["skills"] and profile["keyword_searches"]


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"ok    {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL  {name}: {e}")
    sys.exit(1 if failed else 0)
