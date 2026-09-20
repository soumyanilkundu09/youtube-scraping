"""
Track phrase history week over week and flag emerging / cooling topics.

  python tools/track_history.py --topic animation

Reads the previous snapshot from the `<slug>_history` tab of the Google Sheet, compares it with
today's phrase snapshot (from analysis.json), writes `emerging_topics` and `cooling_topics` back
into analysis.json, then stores today's snapshot in the tab (replacing any rows for today's date,
so a same-day re-run doesn't duplicate). Non-fatal: if Sheets is unreachable the pipeline continues
without week-over-week data.
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
import common  # noqa: E402
from analyze_trends import top_videos_for_phrase  # noqa: E402

load_dotenv()

HISTORY_HEADERS = ["date", "phrase", "kind", "video_count", "share", "total_videos"]
MIN_COUNT = 4          # a phrase needs at least this many videos to be called emerging
RISING_RATIO = 1.5     # share must grow by at least this factor
COOLING_RATIO = 0.5
MAX_LISTED = 12


def parse_history(rows: list[list]) -> dict[str, dict[str, dict]]:
    """rows (with header) -> {date: {phrase: {video_count, share}}}."""
    by_date: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows[1:] if rows and rows[0] and rows[0][0] == "date" else rows:
        if len(row) < 5:
            continue
        try:
            by_date[str(row[0])][str(row[1])] = {
                "video_count": int(float(row[3])), "share": float(row[4]),
                "kind": row[2], "total": row[5] if len(row) > 5 else "",
            }
        except (ValueError, TypeError):
            continue
    return by_date


def compute_deltas(current: list[dict], previous: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """
    current: [{phrase, video_count, share, kind}]; previous: {phrase: {video_count, share}}.
    Returns (emerging, cooling), each a list of dicts sorted by significance.
    """
    emerging, cooling = [], []
    cur_map = {r["phrase"]: r for r in current}
    for r in current:
        if r["video_count"] < MIN_COUNT:
            continue
        prev = previous.get(r["phrase"])
        if prev is None:
            emerging.append({**_base(r), "status": "new", "previous_count": 0, "change": None,
                             "score": r["video_count"] * 2})
        elif prev["share"] > 0 and r["share"] / prev["share"] >= RISING_RATIO:
            ratio = r["share"] / prev["share"]
            emerging.append({**_base(r), "status": "rising", "previous_count": prev["video_count"],
                             "change": round(ratio, 2), "score": r["video_count"] * ratio})
    for phrase, prev in previous.items():
        if prev["video_count"] < MIN_COUNT:
            continue
        cur = cur_map.get(phrase)
        cur_share = cur["share"] if cur else 0.0
        if prev["share"] > 0 and cur_share / prev["share"] <= COOLING_RATIO:
            cooling.append({"phrase": phrase, "video_count": cur["video_count"] if cur else 0,
                            "previous_count": prev["video_count"],
                            "change": round(cur_share / prev["share"], 2), "score": prev["video_count"]})
    emerging.sort(key=lambda r: r["score"], reverse=True)
    cooling.sort(key=lambda r: r["score"], reverse=True)
    return emerging[:MAX_LISTED], cooling[:6]


def _base(r: dict) -> dict:
    return {"phrase": r["phrase"], "video_count": r["video_count"], "share": r["share"], "kind": r.get("kind", "")}


def main():
    slug = common.parse_topic_arg()
    apath = common.analysis_path(slug)
    if not os.path.exists(apath):
        sys.exit(f"Not found: {apath}. Run analyze_trends.py --topic {slug} first.")
    with open(apath, encoding="utf-8") as f:
        analysis = json.load(f)

    sheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snapshot = analysis.get("phrase_snapshot", [])
    note = "History tracking has not run."

    try:
        if not sheet_id:
            raise RuntimeError("GOOGLE_SHEETS_SPREADSHEET_ID not set")
        service = common.sheets_service()
        tab = common.tab_name(slug, "history")
        history = parse_history(common.read_tab(service, sheet_id, tab))
        earlier = sorted(d for d in history if d < today)

        if earlier:
            prev_date = earlier[-1]
            days = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(prev_date, "%Y-%m-%d")).days
            emerging, cooling = compute_deltas(snapshot, history[prev_date])
            for e in emerging:
                e["top_videos"] = [{"title": v["title"], "channel_name": v["channel_name"],
                                    "view_count": v["view_count"], "url": v["url"]}
                                   for v in top_videos_for_phrase(analysis["videos"], e["phrase"])]
            analysis["emerging_topics"], analysis["cooling_topics"] = emerging, cooling
            note = f"Compared with the snapshot from {prev_date} ({days} days earlier)."
        else:
            analysis["emerging_topics"], analysis["cooling_topics"] = [], []
            note = "Baseline recorded today; week-over-week changes start with the next run."

        # Replace today's rows, keep everything else
        total = analysis["total_videos_analyzed"]
        history[today] = {r["phrase"]: {"video_count": r["video_count"], "share": r["share"],
                                        "kind": r.get("kind", ""), "total": total} for r in snapshot}
        rows = [HISTORY_HEADERS]
        for d in sorted(history):
            for phrase, r in history[d].items():
                rows.append([d, phrase, r.get("kind", ""), r["video_count"], r["share"], r.get("total", "")])
        common.write_tab(service, sheet_id, tab, rows)
        print(f"History: {note} Stored {len(snapshot)} phrases for {today} in '{tab}'.")
        print(f"  Emerging: {len(analysis['emerging_topics'])}, cooling: {len(analysis.get('cooling_topics', []))}")
    except Exception as e:  # non-fatal by design
        analysis.setdefault("emerging_topics", [])
        analysis.setdefault("cooling_topics", [])
        note = f"History unavailable this run ({type(e).__name__}: {e})."
        print(f"WARNING: {note}")

    analysis["history_note"] = note
    with open(apath, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
