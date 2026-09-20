"""
Modal deployment for the AI YouTube Trends Intelligence Report.
Runs the full pipeline every Monday at 6PM IST.

  modal run modal_app.py      # one manual run in the cloud (sends a real email)
  modal deploy modal_app.py   # activate the weekly schedule

Secrets: Modal Secret "youtube-analytics" must hold YOUTUBE_API_KEY,
GOOGLE_SHEETS_SPREADSHEET_ID, GMAIL_ADDRESS, GMAIL_APP_PASSWORD and
GOOGLE_SERVICE_ACCOUNT_JSON. See workflows/youtube_trends_report.md.
"""

import subprocess
import sys

import modal

APP_DIR = "/root"

# Order matters: each step reads the previous step's output from .tmp/
PIPELINE = [
    "tools/fetch_ai_trends.py",
    "tools/analyze_trends.py",
    "tools/export_to_sheets.py",
    "tools/generate_report.py",
    "tools/send_email_report.py",
]

image = (
    modal.Image.debian_slim(python_version="3.12")
    # Chromium + libs: kaleido 1.x renders Plotly charts through a real browser
    .apt_install(
        "chromium",
        "libnss3",
        "libgbm1",
        "libasound2",
        "libatk-bridge2.0-0",
        "libcups2",
        "libxcomposite1",
        "libxdamage1",
        "libxfixes3",
        "libxrandr2",
        "libxkbcommon0",
        "libpango-1.0-0",
        "libcairo2",
        "fonts-liberation",
    )
    .pip_install_from_requirements("requirements.txt")
    .add_local_dir("tools", f"{APP_DIR}/tools")
)

app = modal.App("youtube-ai-trends", image=image)


@app.function(
    schedule=modal.Cron("0 18 * * 1", timezone="Asia/Kolkata"),
    secrets=[modal.Secret.from_name("youtube-analytics")],
    timeout=1800,
    retries=0,  # a retry would re-spend YouTube quota and could email twice
)
def run_weekly_report():
    for script in PIPELINE:
        print(f"\n=== {script} ===", flush=True)
        subprocess.run([sys.executable, script], cwd=APP_DIR, check=True)
    print("\nPipeline complete.")


@app.local_entrypoint()
def main():
    run_weekly_report.remote()
