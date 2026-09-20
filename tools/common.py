"""
Shared helpers for the YouTube trends workflow: topic profiles, paths, API retry, Google creds.

Every pipeline step takes `--topic <slug>` (or the TOPIC env var) and reads/writes under
.tmp/<slug>/. Profiles live in topics/<slug>.json.
"""

import argparse
import json
import os
import re
import sys
import time

# tools/ is mounted at /root/tools on Modal, so ROOT resolves to /root there and to the
# project root locally; topics/ and .tmp/ sit next to tools/ in both places.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TOPICS_DIR = os.path.join(ROOT, "topics")
TMP_ROOT = os.path.join(ROOT, ".tmp")

SLUG_RE = re.compile(r"^[a-z0-9_]+$")

PROFILE_DEFAULTS = {
    "channels": [],
    "keyword_searches": [],
    "must_include": [],
    "exclude": [],
    "filter_channel_videos": False,
    "skills": {},
    "content_types": {},
    "lookback_days": 30,
    "region": None,
    "language": None,
    "shorts_max_seconds": 60,
    "videos_per_channel": 30,
    "videos_per_search": 50,
    "recipient": None,
}


class QuotaExceeded(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Topic profiles
# ---------------------------------------------------------------------------

def parse_topic_arg(argv=None) -> str:
    """Return the topic slug from --topic or the TOPIC env var; exit with a clear message if absent."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--topic")
    args, _ = parser.parse_known_args(argv)
    slug = args.topic or os.getenv("TOPIC")
    if not slug:
        available = sorted(f[:-5] for f in os.listdir(TOPICS_DIR)) if os.path.isdir(TOPICS_DIR) else []
        sys.exit(f"No topic given. Pass --topic <slug> or set TOPIC. Available: {', '.join(available) or '(none)'}")
    return slug


def load_profile(slug: str) -> dict:
    if not SLUG_RE.match(slug):
        sys.exit(f"Invalid topic slug '{slug}': use lowercase letters, digits and underscores only.")
    path = os.path.join(TOPICS_DIR, f"{slug}.json")
    if not os.path.exists(path):
        sys.exit(f"Topic profile not found: {path}")
    with open(path, encoding="utf-8") as f:
        profile = json.load(f)
    return validate_profile({**PROFILE_DEFAULTS, **profile}, slug)


def validate_profile(profile: dict, slug: str) -> dict:
    problems = []
    if profile.get("slug") != slug:
        problems.append(f"'slug' must equal the file name ('{slug}'), got {profile.get('slug')!r}")
    if not profile.get("display_name"):
        problems.append("'display_name' is required")
    for key in ("channels", "keyword_searches", "must_include", "exclude"):
        if not isinstance(profile[key], list) or not all(isinstance(x, str) and x.strip() for x in profile[key]):
            problems.append(f"'{key}' must be a list of non-empty strings")
    if not profile["channels"] and not profile["keyword_searches"]:
        problems.append("need at least one channel or keyword search")
    skills = profile["skills"]
    if not isinstance(skills, dict) or not all(
        isinstance(v, list) and v and all(isinstance(t, str) for t in v) for v in skills.values()
    ):
        problems.append("'skills' must map a skill name to a non-empty list of search terms")
    if not isinstance(profile["content_types"], dict):
        problems.append("'content_types' must map a type name to a list of phrases")
    for key in ("lookback_days", "shorts_max_seconds", "videos_per_channel", "videos_per_search"):
        if not isinstance(profile[key], int) or profile[key] <= 0:
            problems.append(f"'{key}' must be a positive integer")
    if problems:
        sys.exit(f"Invalid topic profile '{slug}':\n  - " + "\n  - ".join(problems))
    return profile


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def tmp_dir(slug: str) -> str:
    path = os.path.join(TMP_ROOT, slug)
    os.makedirs(path, exist_ok=True)
    return path


def videos_path(slug: str) -> str:
    return os.path.join(tmp_dir(slug), "videos.json")


def manifest_path(slug: str) -> str:
    return os.path.join(tmp_dir(slug), "fetch_manifest.json")


def analysis_path(slug: str) -> str:
    return os.path.join(tmp_dir(slug), "analysis.json")


def tab_name(slug: str, kind: str) -> str:
    return f"{slug}_{kind}"


# ---------------------------------------------------------------------------
# Text matching (must_include / exclude / skills)
# ---------------------------------------------------------------------------

def compile_terms(terms: list[str]):
    """Case-insensitive, whole-word regex for a list of terms; None if the list is empty."""
    if not terms:
        return None
    # Trailing boundary also rejects ".<digit>", so the term "seedance 2" doesn't match "seedance 2.5"
    parts = [r"(?<![a-z0-9])" + re.escape(t.lower().strip()) + r"(?![a-z0-9]|\.\d)" for t in terms if t.strip()]
    return re.compile("|".join(parts)) if parts else None


def video_text(video: dict) -> str:
    """Lower-cased searchable text of a video: title, description and tags."""
    tags = " ".join(video.get("tags", []) or [])
    return f"{video.get('title', '')} {video.get('description', '')} {tags}".lower()


# ---------------------------------------------------------------------------
# API retry
# ---------------------------------------------------------------------------

RETRY_STATUSES = {429, 500, 502, 503, 504}


def call_with_retry(request, attempts: int = 4, base_delay: float = 2.0):
    """
    Execute a googleapiclient request, retrying transient errors with exponential backoff.
    A quota-exhausted 403 raises QuotaExceeded immediately: retrying only wastes time.
    """
    from googleapiclient.errors import HttpError

    for attempt in range(1, attempts + 1):
        try:
            return request.execute()
        except HttpError as e:
            status = getattr(e.resp, "status", None)
            body = e.content.decode("utf-8", errors="ignore") if isinstance(e.content, bytes) else str(e)
            if status == 403 and ("quotaExceeded" in body or "dailyLimitExceeded" in body):
                raise QuotaExceeded(
                    "YouTube API quota exhausted (resets at midnight Pacific). "
                    "Do not re-run until then."
                ) from e
            if status in RETRY_STATUSES and attempt < attempts:
                delay = base_delay * (2 ** (attempt - 1))
                print(f"    API error {status}; retrying in {delay:.0f}s ({attempt}/{attempts - 1})")
                time.sleep(delay)
                continue
            raise


# ---------------------------------------------------------------------------
# Google credentials (Sheets)
# ---------------------------------------------------------------------------

def get_google_creds(scopes: list[str]):
    """
    Service account first (GOOGLE_SERVICE_ACCOUNT_JSON on Modal, or ./service_account.json locally),
    then the interactive local OAuth flow as a last resort.
    """
    from google.oauth2 import service_account

    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        return service_account.Credentials.from_service_account_info(json.loads(sa_json), scopes=scopes)
    sa_file = os.path.join(ROOT, "service_account.json")
    if os.path.exists(sa_file):
        return service_account.Credentials.from_service_account_file(sa_file, scopes=scopes)

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token_path = os.path.join(ROOT, "token.json")
    creds_path = os.path.join(ROOT, "credentials.json")
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, scopes)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, scopes)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return creds


# ---------------------------------------------------------------------------
# Sheets helpers
# ---------------------------------------------------------------------------

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def sheets_service():
    from googleapiclient.discovery import build

    return build("sheets", "v4", credentials=get_google_creds(SHEETS_SCOPES))


def ensure_tab(service, spreadsheet_id: str, title: str) -> None:
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    if title not in [s["properties"]["title"] for s in meta.get("sheets", [])]:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        ).execute()


def write_tab(service, spreadsheet_id: str, tab: str, rows: list[list]) -> None:
    """Replace a tab's contents (clears first so a shorter run leaves no stale rows). Numbers stay numbers."""
    ensure_tab(service, spreadsheet_id, tab)
    service.spreadsheets().values().clear(spreadsheetId=spreadsheet_id, range=tab, body={}).execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"{tab}!A1", valueInputOption="RAW", body={"values": rows},
    ).execute()


def read_tab(service, spreadsheet_id: str, tab: str) -> list[list]:
    """All rows of a tab, or [] if the tab doesn't exist yet."""
    from googleapiclient.errors import HttpError

    try:
        resp = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=tab).execute()
    except HttpError as e:
        if getattr(e.resp, "status", None) == 400:  # "Unable to parse range": tab missing
            return []
        raise
    return resp.get("values", [])
