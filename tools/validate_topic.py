"""
Validate a topic profile before a real run.

  python tools/validate_topic.py --topic animation

Checks the schema, then resolves every channel handle (1 quota unit each, no search.list calls)
and prints which ones exist, with subscriber counts and recent upload dates, so bad handles
get fixed before a full fetch.
"""

import os
import sys

from dotenv import load_dotenv
from googleapiclient.discovery import build

sys.path.insert(0, os.path.dirname(__file__))
import common  # noqa: E402
from fetch_trends import Quota, estimate_cost, resolve_channel  # noqa: E402

load_dotenv()


def main():
    slug = common.parse_topic_arg()
    profile = common.load_profile(slug)  # exits with a message if the schema is invalid
    print(f"Profile '{slug}' schema OK: {len(profile['channels'])} channels, "
          f"{len(profile['keyword_searches'])} keyword searches, {len(profile['skills'])} skills")
    units, searches = estimate_cost(profile)
    print(f"A full run would cost ~{units} units and {searches} search.list calls.\n")

    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        sys.exit("YOUTUBE_API_KEY not set; cannot resolve channels.")
    youtube = build("youtube", "v3", developerKey=api_key)
    quota = Quota()

    missing = []
    for handle in profile["channels"]:
        info = resolve_channel(youtube, handle, quota)
        if info:
            subs = f"{info['subscribers']:,}" if info["subscribers"] is not None else "hidden"
            print(f"  ok       {handle:<24} -> {info['name']} ({subs} subscribers)")
        else:
            missing.append(handle)
            print(f"  MISSING  {handle}")

    print(f"\nValidation used {quota.units} units.")
    if missing:
        print(f"{len(missing)} channel(s) not found: {', '.join(missing)}. "
              "Fix the handle (or use the UC... channel ID) in the profile.")
        sys.exit(1)
    print("All channels resolved.")


if __name__ == "__main__":
    main()
