# Workflow: Scrape YouTube Channel

## Objective
Fetch video metadata from a YouTube channel and export it to Google Sheets.

## Required Inputs
- YouTube channel handle (e.g. `@mkbhd`) or channel ID (starts with `UC`)
- `YOUTUBE_API_KEY` in `.env`
- `GOOGLE_SHEETS_SPREADSHEET_ID` in `.env` (target sheet must exist)
- `credentials.json` in project root (Google OAuth client secret)

## Steps

1. **Fetch videos**
   ```
   python tools/scrape_youtube_channel.py @<handle> --max 50
   ```
   Output: `.tmp/channel_videos.json`

2. **Export to Sheets**
   ```
   python tools/export_to_sheets.py
   ```
   First run opens a browser for OAuth consent. `token.json` is saved for future runs.

## Expected Output
Google Sheet populated with columns: `video_id`, `title`, `published_at`, `description`, `url`

## Edge Cases & Known Constraints
- YouTube Data API v3 has a daily quota of 10,000 units. Each `search.list` call costs 100 units, so ~100 pages max per day.
- If rate-limited (HTTP 429), wait and retry. Do not re-run immediately.
- Channel handles must be exact. If lookup fails, try the channel's full URL to find the ID manually.
- OAuth token expires after 1 hour but auto-refreshes via `token.json`. Delete `token.json` to force re-auth.
