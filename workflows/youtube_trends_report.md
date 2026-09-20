# Workflow: AI YouTube Trends Intelligence Report

## Objective
Scrape top AI/automation YouTube channels and keyword searches, analyze trending content,
export raw data to Google Sheets, generate a professional 12-slide deck, and email it to
soumyanilkundu09@gmail.com.

## Required Setup (one-time)

### API Keys (.env)
```
YOUTUBE_API_KEY=<your YouTube Data API v3 key>
GOOGLE_SHEETS_SPREADSHEET_ID=<your target sheet ID>
GMAIL_ADDRESS=soumyanilkundu09@gmail.com
GMAIL_APP_PASSWORD=<16-char app password from Google>
```

### Google OAuth (for Sheets export)
- Place `credentials.json` in the project root (download from Google Cloud Console)
- First run of `export_to_sheets.py` will open a browser for consent → saves `token.json`

### Gmail App Password Setup
1. Enable 2-Step Verification on your Google account
2. Go to myaccount.google.com → Security → App Passwords
3. Create an app password → copy the 16-character code → paste into `.env`

### Install dependencies
```bash
pip install -r requirements.txt
```

## Steps

### Step 1 — Fetch YouTube data (~2,000 API quota units)
```bash
python tools/fetch_ai_trends.py
```
- Scrapes 10 top AI channels (30 videos each) + 6 keyword searches
- Fetches full statistics: views, likes, comments, duration
- Output: `.tmp/ai_trends_data.json`

### Step 2 — Analyze trends
```bash
python tools/analyze_trends.py
```
- Computes engagement rates, views-per-day, trending keywords
- Classifies content type (tutorial/news/demo/interview/other)
- Identifies rising-fast videos and channel stats
- Output: `.tmp/ai_trends_analysis.json`

### Step 3 — Export to Google Sheets
```bash
python tools/export_to_sheets.py
```
- Sheet1: all video data with enriched fields
- Sheet2: per-channel summary stats
- First run opens browser for OAuth consent

### Step 4 — Generate slide deck
```bash
python tools/generate_report.py
```
- Builds 12-slide .pptx with Plotly charts embedded as images
- Design: dark navy + cyan accent, professional corporate style
- Output: `.tmp/ai_youtube_report_YYYY-MM-DD.pptx`

### Step 5 — Email the report
```bash
python tools/send_email_report.py
```
- Attaches latest .pptx from `.tmp/`
- Sends to soumyanilkundu09@gmail.com with 3-insight summary in body

## Slide Deck Contents (12 slides)
1. Title — Report date and scope
2. Executive Summary — 6 auto-generated key insights
3. Top 10 Videos Table — Title, channel, views, engagement rate
4. Most Viewed — Horizontal bar chart, top 15 by views
5. Engagement Champions — Bar chart, top 10 by engagement rate
6. Trending Keywords — Keyword frequency bar chart from titles
7. Channel Comparison — Avg views vs. upload count per channel
8. Content Type Breakdown — Pie chart (tutorial/news/demo/interview/other)
9. Best Days to Publish — Bar chart by day of week
10. Views vs. Engagement — Scatter plot to find the sweet spot
11. Rising Fast — Table of high views-per-day videos under 7 days old
12. Content Recommendations — 6 data-driven action items

## Channels Tracked (editable at top of fetch_ai_trends.py)
- @mreflow (Matt Wolfe) — AI news & tools
- @Fireship — tech/AI tutorials
- @aiexplained-official — AI research explainers
- @TwoMinutePapers — AI research
- @lexfridman — AI interviews
- @DaveShap (David Shapiro) — AI automation
- @theaiadvantage — AI tools
- @nicholasrenotte — ML tutorials
- @samwitteveenai — LLM development
- @aiautomationagency — AI Automation Agency

## Keyword Searches Tracked (editable at top of fetch_ai_trends.py)
- "AI automation 2025"
- "Claude AI agent"
- "LLM agents tutorial"
- "AI tools productivity"
- "ChatGPT workflow"
- "AI content creation"

## Quota Budget
| Operation | Units |
|-----------|-------|
| 10 channels × search.list | 1,000 |
| ~350 videos × videos.list stats | 350 |
| 6 keyword searches × search.list | 600 |
| **Total** | **~1,950 / 10,000 daily free** |

## Edge Cases & Known Constraints

**Rate limiting (HTTP 429):** Wait 15–30 minutes before retrying. Do not re-run immediately.
The quota resets at midnight Pacific time.

**Channel handle not found:** Some handles change. Go to the channel's YouTube page,
copy the URL (it shows the handle or UCxxx ID), and update `CHANNELS` in `fetch_ai_trends.py`.

**OAuth token expired:** Delete `token.json` and rerun `export_to_sheets.py` to re-authenticate.

**kaleido not installed:** If chart PNG generation fails, run `pip install kaleido`. On some
systems you may also need: `pip install --upgrade plotly kaleido`.

**Re-running without re-scraping:** If `.tmp/ai_trends_data.json` already exists and is fresh,
skip Step 1 and run Steps 2–5 directly. Useful if you want to regenerate the deck with the
same data.

**Adding channels:** Edit the `CHANNELS` list at the top of `tools/fetch_ai_trends.py`.
Each additional channel costs 100 quota units. Stays within free tier up to ~80 channels.

## Cloud Scheduling (Modal)

The pipeline runs automatically every **Monday 6PM IST** via `modal_app.py`
(`modal.Cron("0 18 * * 1", timezone="Asia/Kolkata")`). It runs Steps 1–5 in order in a
Modal container, then emails the deck.

### One-time setup
1. `pip install modal` then `python -m modal setup` (use `python`, not `python3`, on Windows)
2. Google Sheets auth is a **service account** (OAuth `token.json` can't be used headlessly):
   enable the Sheets API in Google Cloud, create a service account, download its JSON key to
   `service_account.json` (gitignored), and share the target sheet with the key's
   `client_email` as Editor.
3. Push credentials to the Modal Secret `youtube-analytics` (keys: `YOUTUBE_API_KEY`,
   `GOOGLE_SHEETS_SPREADSHEET_ID`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`,
   `GOOGLE_SERVICE_ACCOUNT_JSON`) with
   `modal secret create youtube-analytics --from-json <file> --force`.
   Build the JSON file in a temp location and delete it afterwards.

### Commands
```bash
modal run modal_app.py      # one manual cloud run (uses ~1,950 quota units, sends a real email)
modal deploy modal_app.py   # activate / update the weekly schedule
```
Re-run `modal deploy` after any change to `modal_app.py`, `tools/` or `requirements.txt`.

### Cloud-specific notes
- **Attachment is the .pptx.** `send_email_report.py` originally looked for a `.pdf` that no
  tool produces; it now attaches the latest `.pptx`. No PowerPoint-to-PDF converter in the image.
- **`export_to_sheets.py`** uses `GOOGLE_SERVICE_ACCOUNT_JSON` when set, else falls back to the
  local OAuth flow.
- **Charts need Chromium.** kaleido 1.x renders through a real browser, so the Modal image
  installs Chromium and its libraries. If chart export fails in the cloud, check the
  image build first (fallback: `plotly_get_chrome -y` in the image build).
- **No retries** on the scheduled function: a retry would re-spend YouTube quota and could
  send a duplicate email. Check run logs in the Modal dashboard after each Monday.
- The container starts with an empty `.tmp/`, so every run re-scrapes fresh data.

## Deliverables
- **Google Sheets**: Raw data for custom filtering and exploration
- **Email**: Professional .pptx deck sent to soumyanilkundu09@gmail.com
