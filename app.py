"""
app.py — Flask web server for BTP Cloud Foundry deployment

Two routes:
  GET /        → show the last generated report (or a "not run yet" page)
  POST /run    → trigger a fresh health-check and redirect to /

On BTP, CF injects the PORT environment variable automatically.
"""

import os
import threading
from flask import Flask, redirect, url_for
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

REPORT_PATH = os.getenv("REPORT_PATH", "report.html")
_running    = False


def _run_report():
    global _running
    _running = True
    try:
        from reporter import generate_report
        generate_report(REPORT_PATH)
    finally:
        _running = False


@app.route("/")
def index():
    # Serve the report if it exists
    if os.path.exists(REPORT_PATH):
        with open(REPORT_PATH, encoding="utf-8") as f:
            return f.read()

    # First-visit page — no report yet
    status = "Running now, refresh in ~20 seconds..." if _running else \
             "No report yet. <form method='post' action='/run' style='display:inline'>" \
             "<button style='margin-left:8px;padding:6px 16px;background:#00a8ff;" \
             "color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:13px'>" \
             "Generate Report</button></form>"

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
    <style>body{{background:#080e17;color:#b0c8dc;font-family:monospace;
    display:flex;align-items:center;justify-content:center;height:100vh;text-align:center}}</style>
    </head><body>
    <div>
      <div style="font-size:28px;font-weight:600;color:#e0eef8;margin-bottom:12px">
        HANA Health Reporter
      </div>
      <div style="color:#4a6a84;margin-bottom:20px">{status}</div>
    </div>
    </body></html>"""


@app.route("/run", methods=["POST"])
def run():
    global _running
    if not _running:
        threading.Thread(target=_run_report, daemon=True).start()
    return redirect(url_for("index"))


if __name__ == "__main__":
    port  = int(os.environ.get("PORT", os.getenv("FLASK_PORT", 5000)))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    print(f"  Starting on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
