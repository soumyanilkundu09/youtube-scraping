"""
Modal deployment for the YouTube Trends Intelligence Report (topic-driven).

  modal run modal_app.py --topic animation   # one manual cloud run for a saved topic profile
                                             # (real side effects: API quota, Sheet tabs, an email)
  modal deploy modal_app.py                  # activate / update the weekly schedule

Topics live in topics/<slug>.json. The weekly schedule runs every topic in SCHEDULED_TOPICS,
Monday 6PM IST; add a slug there to schedule another topic, then redeploy.

Secrets: Modal Secret "youtube-analytics" must hold YOUTUBE_API_KEY,
GOOGLE_SHEETS_SPREADSHEET_ID, GMAIL_ADDRESS, GMAIL_APP_PASSWORD and
GOOGLE_SERVICE_ACCOUNT_JSON. See workflows/youtube_trends_report.md.
"""

import subprocess
import sys

import modal

APP_DIR = "/root"

# Topics the weekly schedule runs, one container each. Add a slug here and redeploy.
SCHEDULED_TOPICS = ["ai_automation"]

# Order matters: each step reads the previous step's output from .tmp/<topic>/
PIPELINE = [
    "tools/fetch_trends.py",
    "tools/analyze_trends.py",
    "tools/track_history.py",
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
    .add_local_dir("topics", f"{APP_DIR}/topics")
)

app = modal.App("youtube-ai-trends", image=image)
SECRETS = [modal.Secret.from_name("youtube-analytics")]


class StepFailed(RuntimeError):
    pass


def run_pipeline(topic: str) -> None:
    for script in PIPELINE:
        print(f"\n=== [{topic}] {script} ===", flush=True)
        result = subprocess.run([sys.executable, script, "--topic", topic], cwd=APP_DIR)
        if result.returncode != 0:
            # Tell the user, with the step name only (no secrets), then fail the run loudly.
            subprocess.run(
                [sys.executable, "tools/send_email_report.py", "--topic", topic, "--failure", script],
                cwd=APP_DIR,
            )
            raise StepFailed(f"{script} failed for topic '{topic}' (exit {result.returncode})")
    print(f"\n[{topic}] pipeline complete.")


@app.function(secrets=SECRETS, timeout=1800, retries=0)  # retries=0: a retry would re-spend quota and email twice
def run_topic(topic: str):
    run_pipeline(topic)


@app.function(
    schedule=modal.Cron("0 18 * * 1", timezone="Asia/Kolkata"),
    secrets=SECRETS,
    timeout=1800 * max(len(SCHEDULED_TOPICS), 1) + 300,  # runs the topics one after another
    retries=0,
)
def run_weekly_reports():
    failures = []
    for topic in SCHEDULED_TOPICS:
        try:
            run_topic.remote(topic)  # its own container per topic; one failure doesn't stop the others
        except Exception as e:
            failures.append(f"{topic}: {e}")
    if failures:
        raise RuntimeError("Some topics failed: " + "; ".join(failures))


@app.local_entrypoint()
def main(topic: str):
    run_topic.remote(topic)
