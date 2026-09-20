# Workflow: YouTube Trends Intelligence Report (topic-driven)

## Objective
For any topic (AI & automation, animation, ...), find what is trending on YouTube: top and
breakout videos, trending and emerging phrases, topic clusters with related videos, skills and
tools in demand, and channels worth following. Export the data to Google Sheets, build a 16-slide
deck and email it. The topic comes from a saved profile in `topics/<slug>.json`.

## Required Setup (one-time)

### API keys (.env)
```
YOUTUBE_API_KEY=<your YouTube Data API v3 key>
GOOGLE_SHEETS_SPREADSHEET_ID=<your target sheet ID>
GMAIL_ADDRESS=<sender Gmail address>
GMAIL_APP_PASSWORD=<16-char app password from Google>
```
Optional: `REPORT_RECIPIENT` (default recipient when a profile doesn't set one),
`SEARCH_CALL_BUDGET` and `QUOTA_UNIT_BUDGET` (fetch aborts before spending anything if its
estimate exceeds them; defaults 60 search calls and 3,000 units).

### Google Sheets auth
A **service account** is used everywhere: `GOOGLE_SERVICE_ACCOUNT_JSON` on Modal, or
`service_account.json` in the project root locally (gitignored). Share the target spreadsheet with
the key's `client_email` as Editor. The old OAuth flow (`credentials.json` / `token.json`) is only a
last-resort fallback and needs a browser.

### Gmail app password
1. Enable 2-Step Verification on your Google account
2. myaccount.google.com -> Security -> App Passwords
3. Create an app password, copy the 16-character code (no spaces) into `.env`

### Install dependencies
```bash
pip install -r requirements.txt
```

## Topic profiles (`topics/<slug>.json`)
| Field | Meaning |
|-------|---------|
| `slug`, `display_name` | File name / label used in slides, email and Sheet tab names |
| `channels` | Handles (`@name`) or `UC...` IDs tracked every run |
| `keyword_searches` | YouTube searches (most-viewed within `lookback_days`) |
| `must_include` | Whole-word terms; a keyword-search video must contain one (title, description or tags) |
| `exclude` | Whole-word terms that drop a video anywhere |
| `filter_channel_videos` | `true` also applies `must_include` to channel videos (for general-interest channels) |
| `skills` | Skill/tool name -> search terms; drives the Skills slide and `<slug>_skills` tab |
| `content_types` | Optional extra content types, checked before the defaults |
| `lookback_days`, `region`, `language` | Search window and locale hints (`language` is a `relevanceLanguage` hint) |
| `shorts_max_seconds` | Videos at or under this length count as Shorts (default 60) |
| `videos_per_channel`, `videos_per_search` | Sample sizes (defaults 30 and 50) |
| `recipient` | Email recipient (default: `REPORT_RECIPIENT`, then the original address) |

Existing profiles: `ai_automation`, `animation`, `seedance`.

## Adding a new topic
1. Tell the agent the topic ("run the report for <topic>"). The agent drafts `topics/<slug>.json`
   (channels, keyword searches, `must_include`/`exclude`, skills) from its own knowledge.
2. Run `python tools/validate_topic.py --topic <slug>`. It checks the schema and resolves each
   channel handle (about 1 quota unit per channel). Fix handles reported as MISSING.
3. Review the profile with the agent and edit it. Later runs surface channel candidates (see the
   Channels to Watch slide and `<slug>_candidates` tab); to track one, add its handle to `channels`.
4. Run the pipeline. To schedule it, add the slug to `SCHEDULED_TOPICS` in `modal_app.py` and
   `modal deploy`.

## Steps
Every step takes `--topic <slug>` (or the `TOPIC` env var) and works in `.tmp/<slug>/`.

### Step 1 - Fetch YouTube data
```bash
python tools/fetch_trends.py --topic <slug> [--dry-run]
```
- `--dry-run` prints the quota estimate and stops.
- Channels: `channels.list(forHandle=...)` then the channel's uploads playlist (1 unit per call);
  this returns the real latest uploads. Keywords: `search.list` within the lookback window.
- Captures views, likes, comments, duration, tags, category, language, subscriber counts, `is_short`.
- Output: `.tmp/<slug>/videos.json`, `.tmp/<slug>/fetch_manifest.json` (per-channel counts, warnings, quota used)

### Step 2 - Analyze
```bash
python tools/analyze_trends.py --topic <slug>
```
- Per video: engagement rate, views/day (age floored at 1 day), content type, **outlier score**
  (views / that channel's median views; falls back to the topic-wide median for channels with fewer
  than 5 sampled videos), weekday, duration bucket.
- Phrases (words and two-word phrases, counted by videos, channel names removed), skills, topic
  clusters (TF-IDF + KMeans, needs 30+ videos), long-form vs Shorts, performance by weekday, length
  and content type, channel stats and channel candidates. Performance medians use only videos scored
  against their own channel's norm (not the topic-wide fallback, which makes tiny channels look like
  flops), need n >= 5, and a "best" day/length/type is only called out if it beats norms by 20%+.
- Output: `.tmp/<slug>/analysis.json` (includes the full enriched video list)

### Step 3 - Track history
```bash
python tools/track_history.py --topic <slug>
```
- Compares today's phrase snapshot with the previous one stored in the `<slug>_history` tab and
  flags **emerging** (new, or share up 1.5x+, at least 4 videos) and **cooling** phrases.
- First run only records a baseline. Non-fatal: if Sheets is unreachable the run continues.

### Step 4 - Export to Google Sheets
```bash
python tools/export_to_sheets.py --topic <slug>
```
- Tabs (same spreadsheet): `<slug>_videos`, `<slug>_channels`, `<slug>_skills`, `<slug>_candidates`
  (and `<slug>_history` from Step 3). Tabs are cleared before writing; numbers are real numbers.

### Step 5 - Generate the deck
```bash
python tools/generate_report.py --topic <slug>
```
- Output: `.tmp/<slug>/report_<slug>_YYYY-MM-DD.pptx` (design: dark navy + cyan)

### Step 6 - Email
```bash
python tools/send_email_report.py --topic <slug>
```
- Attaches the latest `.pptx`, sends the top 3 insights and the Sheet link.
- `--failure "<step>"` sends a short failure notice instead (Modal does this automatically).

## Slide deck (16 slides)
1. Title  2. Executive Summary (with data-quality notes)  3. Top 10 Videos  4. Most Viewed
5. Engagement Champions  6. Trending Phrases  7. Emerging Topics (week over week)
8. Topic Clusters & Related Videos  9. Skills & Tools  10. Channel Comparison
11. Channels to Watch  12. Content Type & Format (long-form vs Shorts)
13. Best Day & Length to Publish (performance-based, dotted line = channel norm)
14. Breakout & Rising Videos  15. Views vs. Engagement  16. Recommendations (all computed from the
data; any recommendation without enough sample is left out)

## Quota (YouTube Data API)
As of the current Google docs: `search.list` has its **own bucket of 100 calls/day** (1 unit each),
separate from the 10,000 units/day for everything else; `videos.list`, `channels.list` and
`playlistItems.list` cost 1 unit **per request** (up to 50 ids), not per video.

| Operation | Cost |
|-----------|------|
| Channel: resolve + uploads + details | about 3 units per channel |
| Keyword search | 1 search call + about 1 unit for details |
| Subscriber counts | 1 unit per 50 channels |
| **Typical topic run** | **about 55-60 units and 6-8 search calls** |

The old design used `search.list` for channel lookups too (about 26 search calls per run), which
would exhaust the search bucket after a few topics and also returned too few videos for some channels.
Quota resets at midnight Pacific.

## Edge Cases & Known Constraints

**HTTP 429 / 5xx:** calls retry with backoff automatically. A quota-exhausted 403 aborts the run with a
clear message; do not re-run until the quota resets.

**A handle can resolve to the wrong channel.** `forHandle` returns whatever owns that handle, e.g.
`@AIAnimation` was a 993-subscriber unrelated channel. `validate_topic.py` prints each channel's name and
subscriber count: check them, not just the ok/MISSING status.

**Channel handle not found:** shows as a warning in the run output and on the deck's summary slide.
Run `validate_topic.py`, check the channel page for its current handle (or use the `UC...` ID) and
edit the profile.

**Version-style skill terms:** a term such as `seedance 2` does not match `seedance 2.5` (whole-word match
also rejects a trailing `.digit`), so list each version as its own skill.

**A channel returns few videos:** the fetch manifest flags any channel under 10 videos.
`filter_channel_videos` can also thin a channel out on purpose (general-interest channels).

**No related-videos API:** YouTube removed `relatedToVideoId` in 2023. "Related videos" are built by
clustering the collected videos (Topic Clusters slide) and by phrase (Emerging Topics slide).

**Timezones:** publish weekdays are computed in UTC.

**History depends on the `<slug>_history` tab.** If it is deleted, the next run records a new baseline.

**kaleido:** chart export needs Chrome/Chromium (kaleido 1.x). Locally it uses the installed browser; in
the Modal image Chromium is installed via apt.

**Re-running without re-fetching:** if `.tmp/<slug>/videos.json` is fresh, run Steps 2-6 directly.

**Not covered:** transcripts. This workflow uses titles, descriptions, tags and statistics only.

## Cloud Scheduling (Modal)

`modal_app.py` runs every topic in `SCHEDULED_TOPICS` every **Monday 6PM IST**
(`modal.Cron("0 18 * * 1", timezone="Asia/Kolkata")`), one container per topic, running Steps 1-6 in order.

### One-time setup
1. `pip install modal`, then `python -m modal setup` (use `python`, not `python3`, on Windows)
2. Service account for Sheets (see above): enable the Sheets API, create the account, share the sheet.
3. Modal Secret `youtube-analytics` with `YOUTUBE_API_KEY`, `GOOGLE_SHEETS_SPREADSHEET_ID`,
   `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `GOOGLE_SERVICE_ACCOUNT_JSON`
   (`~/.claude/skills/deploy-to-modal/scripts/push_modal_secret.py` builds it from `.env`).

### Commands
```bash
modal run modal_app.py --topic animation   # one cloud run for any saved profile (real email, Sheet tabs, quota)
modal deploy modal_app.py                  # activate / update the weekly schedule
```
Re-run `modal deploy` after any change to `modal_app.py`, `tools/`, `topics/` or `requirements.txt`.

### Cloud-specific notes
- If a step fails, Modal emails a failure notice (step name only) and the run fails in the dashboard.
- **No retries** on the functions: a retry would re-spend quota and could send a duplicate email.
- The container starts with an empty `.tmp/`, so every run re-fetches. History lives in Google Sheets,
  not on the container.
- The attachment is the `.pptx` (no PDF converter in the image).

## Deliverables
- **Google Sheets:** per-topic tabs for filtering and exploration
- **Email:** the `.pptx` deck plus top insights, sent to the topic's recipient
