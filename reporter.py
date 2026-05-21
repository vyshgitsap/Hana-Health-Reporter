"""
reporter.py — SAP HANA Health Reporter
---------------------------------------
1. Collect metrics from HANA (or synthetic demo data)
2. Send metrics to Claude API for Basis analysis
3. Render a self-contained HTML report

Author : Vysh — SAP Basis Administrator
Stack  : Python · hdbcli · Anthropic Claude API · SAP BTP
"""

import os
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Read DEMO_MODE — print it so we can see it in BTP logs ───────────────────
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"
print(f"[STARTUP] DEMO_MODE={DEMO_MODE} | raw value='{os.getenv('DEMO_MODE', 'NOT SET')}'")


# ── 1. COLLECT METRICS FROM HANA ─────────────────────────────────────────────

def collect_metrics() -> dict:
    """
    Run five Basis monitoring queries against SAP HANA.
    Falls back to realistic demo data if DEMO_MODE=true or connection fails.
    """
    print(f"[collect_metrics] DEMO_MODE={DEMO_MODE}")

    if DEMO_MODE:
        print("[collect_metrics] Demo mode active — returning synthetic data.")
        return _demo_metrics()

    # ── Read Cloud Connector proxy from VCAP_SERVICES ────────────────────────
    proxy_host = None
    proxy_port = None

    vcap_raw = os.getenv("VCAP_SERVICES", "{}")
    print(f"[collect_metrics] VCAP_SERVICES present: {len(vcap_raw) > 2}")

    try:
        vcap_services = json.loads(vcap_raw)
        connectivity  = vcap_services.get("connectivity", [{}])[0].get("credentials", {})
        proxy_host    = connectivity.get("onpremise_proxy_host")
        proxy_port    = connectivity.get("onpremise_socks5_proxy_port")
        print(f"[collect_metrics] proxy_host={proxy_host} | proxy_port={proxy_port}")
    except Exception as e:
        print(f"[collect_metrics] VCAP_SERVICES parse error: {e}")

    # ── Connect to HANA ───────────────────────────────────────────────────────
    try:
        from hdbcli import dbapi

        hana_host = os.getenv("HANA_HOST", "NOT_SET")
        hana_port = int(os.getenv("HANA_PORT", "30015"))
        hana_user = os.getenv("HANA_USER", "NOT_SET")
        print(f"[collect_metrics] Connecting to {hana_host}:{hana_port} as {hana_user}")

        if proxy_host and proxy_port:
            print(f"[collect_metrics] Using Cloud Connector SOCKS5 proxy: {proxy_host}:{proxy_port}")

            # Fetch JWT token for proxy authentication
            import urllib.request
            import urllib.parse
            import base64

            token_url      = connectivity.get("token_service_url") + "/oauth/token"
            client_id      = connectivity.get("clientid")
            client_secret  = connectivity.get("clientsecret")

            print(f"[collect_metrics] Fetching JWT token from: {token_url}")

            credentials = base64.b64encode(
                f"{client_id}:{client_secret}".encode()
            ).decode()

            token_request = urllib.request.Request(
                token_url,
                data=urllib.parse.urlencode(
                    {"grant_type": "client_credentials"}
                ).encode(),
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )

            with urllib.request.urlopen(token_request, timeout=10) as resp:
                token_data = json.loads(resp.read().decode())
                jwt_token = token_data["access_token"]

            print("[collect_metrics] JWT token obtained successfully.")

            conn = dbapi.connect(
                address=hana_host,
                port=hana_port,
                user=hana_user,
                password=os.environ["HANA_PASSWORD"],
                proxyHostname=proxy_host,
                proxyPort=int(proxy_port),
                proxyMode="tunneling",
                proxyPassword=jwt_token,
            )
        else:
            print("[collect_metrics] No proxy found — connecting directly.")
            conn = dbapi.connect(
                address=hana_host,
                port=hana_port,
                user=hana_user,
                password=os.environ["HANA_PASSWORD"],
            )

        print("[collect_metrics] HANA connection established.")

        def q(sql):
            from decimal import Decimal
            cur = conn.cursor()
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = []
            for row in cur.fetchall():
                clean = {k: float(v) if isinstance(v, Decimal) else v
                         for k, v in zip(cols, row)}
                rows.append(clean)
            return rows

        metrics = {
            "source": "live",

            "system": q(
                "SELECT DATABASE_NAME, VERSION, USAGE, "
                "TO_VARCHAR(START_TIME,'YYYY-MM-DD HH24:MI:SS') AS START_TIME "
                "FROM SYS.M_DATABASE"
            )[0],

            "services": q(
                "SELECT SERVICE_NAME, ACTIVE_STATUS, PORT "
                "FROM SYS.M_SERVICES ORDER BY SERVICE_NAME"
            ),

            "memory": q(
                "SELECT S.SERVICE_NAME, "
                "ROUND(M.HEAP_MEMORY_USED_SIZE/1073741824.0,2) AS USED_GB, "
                "ROUND(M.EFFECTIVE_ALLOCATION_LIMIT/1073741824.0,2) AS LIMIT_GB, "
                "ROUND(M.HEAP_MEMORY_USED_SIZE*100.0/NULLIF(M.EFFECTIVE_ALLOCATION_LIMIT,0),1) AS USED_PCT "
                "FROM SYS.M_SERVICE_MEMORY M "
                "JOIN SYS.M_SERVICES S ON M.HOST=S.HOST AND M.PORT=S.PORT "
                "ORDER BY USED_PCT DESC NULLS LAST"
            ),

            "disk": q(
                "SELECT USAGE_TYPE, "
                "ROUND(USED_SIZE/1073741824.0,1) AS USED_GB, "
                "ROUND(FILE_SIZE/1073741824.0,1) AS TOTAL_GB, "
                "ROUND(USED_SIZE*100.0/NULLIF(FILE_SIZE,0),1) AS USED_PCT "
                "FROM SYS.M_DISK_USAGE ORDER BY USAGE_TYPE"
            ),

            "backup": q(
                "SELECT TOP 1 ENTRY_TYPE_NAME, STATE_NAME, "
                "TO_VARCHAR(SYS_END_TIME,'YYYY-MM-DD HH24:MI:SS') AS LAST_BACKUP "
                "FROM SYS.M_BACKUP_CATALOG "
                "ORDER BY SYS_END_TIME DESC"
            ),
        }

        conn.close()
        print("[collect_metrics] Metrics collected successfully. Source: LIVE")
        return metrics

    except Exception as e:
        import traceback
        print(f"[collect_metrics] HANA connection FAILED: {e}")
        print(f"[collect_metrics] Traceback: {traceback.format_exc()}")
        print("[collect_metrics] Falling back to demo data.")
        return _demo_metrics()


def _demo_metrics() -> dict:
    """Realistic synthetic HANA metrics for demo / portfolio use."""
    return {
        "source": "demo",
        "system": {
            "DATABASE_NAME": "HXE",
            "VERSION":       "2.00.067.00",
            "USAGE":         "DEVELOPMENT",
            "START_TIME":    "2024-01-15 06:00:00"
        },
        "services": [
            {"SERVICE_NAME": "nameserver",   "ACTIVE_STATUS": "YES", "PORT": 39001},
            {"SERVICE_NAME": "indexserver",  "ACTIVE_STATUS": "YES", "PORT": 39003},
            {"SERVICE_NAME": "xsengine",     "ACTIVE_STATUS": "YES", "PORT": 39007},
            {"SERVICE_NAME": "preprocessor", "ACTIVE_STATUS": "YES", "PORT": 39010},
            {"SERVICE_NAME": "dpserver",     "ACTIVE_STATUS": "NO",  "PORT": 39013},
        ],
        "memory": [
            {"SERVICE_NAME": "indexserver",  "USED_GB": 9.5,  "LIMIT_GB": 16.0, "USED_PCT": 59.4},
            {"SERVICE_NAME": "xsengine",     "USED_GB": 2.5,  "LIMIT_GB": 4.0,  "USED_PCT": 62.5},
            {"SERVICE_NAME": "nameserver",   "USED_GB": 1.2,  "LIMIT_GB": 4.0,  "USED_PCT": 30.0},
            {"SERVICE_NAME": "preprocessor", "USED_GB": 0.2,  "LIMIT_GB": 2.0,  "USED_PCT": 10.0},
        ],
        "disk": [
            {"USAGE_TYPE": "DATA",   "USED_GB": 17.0, "TOTAL_GB": 50.0, "USED_PCT": 34.0},
            {"USAGE_TYPE": "LOG",    "USED_GB": 5.0,  "TOTAL_GB": 20.0, "USED_PCT": 25.0},
            {"USAGE_TYPE": "BACKUP", "USED_GB": 43.0, "TOTAL_GB": 50.0, "USED_PCT": 86.0},
            {"USAGE_TYPE": "TRACE",  "USED_GB": 2.0,  "TOTAL_GB": 10.0, "USED_PCT": 20.0},
        ],
        "backup": [
            {
                "ENTRY_TYPE_NAME": "complete data backup",
                "STATE_NAME":      "successful",
                "LAST_BACKUP":     "2024-01-14 07:00:00"
            }
        ],
    }


# ── 2. ANALYSE WITH CLAUDE API ────────────────────────────────────────────────

def analyse_with_claude(metrics: dict) -> dict:
    """
    Send HANA metrics to Claude and get a structured Basis health analysis back.
    Returns a dict with: score, grade, findings (list), recommendations (list), summary.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    prompt = f"""You are an expert SAP Basis Administrator.
Analyse these SAP HANA system metrics and return a JSON health report.

METRICS:
{json.dumps(metrics, indent=2)}

Return ONLY valid JSON with exactly these keys:
{{
  "score": <integer 0-100>,
  "grade": <"HEALTHY" | "DEGRADED" | "CRITICAL">,
  "findings": [
    {{"check": "<name>", "status": "<ok|warning|critical>", "detail": "<one sentence>"}}
  ],
  "recommendations": ["<actionable step with SAP T-code where relevant>"],
  "summary": "<2-3 sentence professional Basis commentary>"
}}

Scoring guide:
- Deduct 30 for each critical finding (stopped service, backup >24h overdue, disk >90%)
- Deduct 15 for each warning (memory >80%, disk >75%, backup >12h)
- Start at 100

Be specific — use service names, percentages, and timestamps from the data."""

    response = client.messages.create(
        model      = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        max_tokens = 2048,
        messages   = [{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]

    return json.loads(text.strip())


# ── 3. RENDER HTML REPORT ─────────────────────────────────────────────────────

def render_html(metrics: dict, analysis: dict) -> str:
    """Build a self-contained single-page HTML report."""

    score  = analysis.get("score", 0)
    grade  = analysis.get("grade", "UNKNOWN")
    source = metrics.get("source", "unknown").upper()
    sys    = metrics.get("system", {})

    grade_colour = {
        "HEALTHY":  "#00c896",
        "DEGRADED": "#f0b429",
        "CRITICAL": "#ff4757"
    }.get(grade, "#aaa")

    # ── Findings rows ─────────────────────────────────────────────────────────
    chip_colour  = {"ok": "#00c896", "warning": "#f0b429", "critical": "#ff4757"}
    findings_html = ""
    for f in analysis.get("findings", []):
        c = chip_colour.get(f.get("status", "ok"), "#aaa")
        findings_html += f"""
        <tr>
          <td style="font-family:monospace;font-size:13px;color:#7eb8d4">{f.get('check','')}</td>
          <td><span style="background:{c}22;color:{c};border:1px solid {c}55;
              border-radius:3px;font-size:11px;padding:2px 8px;font-family:monospace;
              font-weight:600">{f.get('status','').upper()}</span></td>
          <td style="font-size:13px;color:#b0c8dc">{f.get('detail','')}</td>
        </tr>"""

    # ── Recommendations ───────────────────────────────────────────────────────
    recs_html = "".join(
        f'<li style="margin-bottom:8px;color:#b0c8dc;font-size:13px">{r}</li>'
        for r in analysis.get("recommendations", [])
    )

    # ── Services rows ─────────────────────────────────────────────────────────
    services_html = ""
    for svc in metrics.get("services", []):
        active = svc.get("ACTIVE_STATUS", "NO") == "YES"
        dot_c  = "#00c896" if active else "#ff4757"
        label  = "RUNNING" if active else "STOPPED"
        services_html += f"""
        <tr>
          <td style="font-family:monospace;font-size:13px;color:#7eb8d4">{svc.get('SERVICE_NAME','')}</td>
          <td style="font-family:monospace;font-size:12px;color:#4a6a84">{svc.get('PORT','')}</td>
          <td><span style="color:{dot_c};font-size:11px;font-family:monospace;font-weight:600">● {label}</span></td>
        </tr>"""

    # ── Memory rows ───────────────────────────────────────────────────────────
    memory_html = ""
    for m in metrics.get("memory", []):
        pct   = m.get("USED_PCT", 0) or 0
        bar_c = "#ff4757" if pct >= 90 else ("#f0b429" if pct >= 80 else "#00c896")
        memory_html += f"""
        <tr>
          <td style="font-family:monospace;font-size:13px;color:#7eb8d4">{m.get('SERVICE_NAME','')}</td>
          <td style="font-family:monospace;font-size:12px;color:#4a6a84">{m.get('USED_GB',0)} / {m.get('LIMIT_GB',0)} GB</td>
          <td style="min-width:120px">
            <div style="background:#1a2a3a;border-radius:3px;height:6px;overflow:hidden">
              <div style="background:{bar_c};width:{min(pct,100)}%;height:100%;border-radius:3px"></div>
            </div>
            <span style="font-size:11px;font-family:monospace;color:{bar_c}">{pct}%</span>
          </td>
        </tr>"""

    # ── Disk rows ─────────────────────────────────────────────────────────────
    disk_html = ""
    for d in metrics.get("disk", []):
        pct   = d.get("USED_PCT", 0) or 0
        bar_c = "#ff4757" if pct >= 90 else ("#f0b429" if pct >= 75 else "#00c896")
        disk_html += f"""
        <tr>
          <td style="font-family:monospace;font-size:13px;color:#7eb8d4">{d.get('USAGE_TYPE','')}</td>
          <td style="font-family:monospace;font-size:12px;color:#4a6a84">{d.get('USED_GB',0)} / {d.get('TOTAL_GB',0)} GB</td>
          <td style="min-width:120px">
            <div style="background:#1a2a3a;border-radius:3px;height:6px;overflow:hidden">
              <div style="background:{bar_c};width:{min(pct,100)}%;height:100%;border-radius:3px"></div>
            </div>
            <span style="font-size:11px;font-family:monospace;color:{bar_c}">{pct}%</span>
          </td>
        </tr>"""

    # ── Backup ────────────────────────────────────────────────────────────────
    backup     = metrics.get("backup", [{}])
    backup_row = backup[0] if backup else {}
    backup_ts  = backup_row.get("LAST_BACKUP", "No backup found")
    backup_st  = backup_row.get("STATE_NAME", "unknown")
    backup_c   = "#00c896" if backup_st == "successful" else "#ff4757"

    # ── Full HTML ─────────────────────────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HANA Health Report — {sys.get('DATABASE_NAME','HXE')}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing:border-box; margin:0; padding:0 }}
  body {{ background:#080e17; color:#b0c8dc;
          font-family:'IBM Plex Sans',sans-serif; padding:32px 20px; min-height:100vh }}
  .wrap {{ max-width:860px; margin:0 auto }}
  .header {{ display:flex; justify-content:space-between; align-items:flex-start;
             margin-bottom:16px; flex-wrap:wrap; gap:16px }}
  .brand {{ font-family:'IBM Plex Mono',monospace; font-size:11px; color:#3d5570;
            letter-spacing:.1em; text-transform:uppercase; margin-bottom:6px }}
  .title {{ font-family:'IBM Plex Mono',monospace; font-size:22px;
            font-weight:600; color:#e0eef8 }}
  .meta  {{ font-size:12px; color:#3d5570; margin-top:4px; font-family:'IBM Plex Mono',monospace }}
  .source-badge {{ font-family:'IBM Plex Mono',monospace; font-size:10px;
                   padding:4px 10px; border-radius:3px;
                   background:{'rgba(0,200,150,.1)' if source=='LIVE' else 'rgba(240,180,41,.1)'};
                   color:{'#00c896' if source=='LIVE' else '#f0b429'};
                   border:1px solid {'#00c89633' if source=='LIVE' else '#f0b42933'} }}
  .score-card {{ background:#0d1825; border:1px solid #1a2d42; border-radius:8px;
                 padding:24px 28px; margin-bottom:20px;
                 display:flex; align-items:center; gap:28px; flex-wrap:wrap }}
  .score-ring {{ position:relative; width:100px; height:100px; flex-shrink:0 }}
  .score-ring svg {{ transform:rotate(-90deg) }}
  .score-num {{ position:absolute; inset:0; display:flex; flex-direction:column;
                align-items:center; justify-content:center }}
  .score-num span:first-child {{ font-family:'IBM Plex Mono',monospace;
                                  font-size:26px; font-weight:600; color:#e0eef8 }}
  .score-num span:last-child  {{ font-family:'IBM Plex Mono',monospace;
                                  font-size:10px; color:#3d5570 }}
  .score-info {{ flex:1 }}
  .grade {{ font-family:'IBM Plex Mono',monospace; font-size:18px;
            font-weight:600; color:{grade_colour}; margin-bottom:6px }}
  .summary-text {{ font-size:14px; color:#7ea8c4; line-height:1.6 }}
  .section {{ background:#0d1825; border:1px solid #1a2d42; border-radius:8px;
              padding:0; margin-bottom:16px; overflow:hidden }}
  .section-head {{ padding:12px 18px; border-bottom:1px solid #1a2d42;
                   font-family:'IBM Plex Mono',monospace; font-size:10px;
                   color:#3d5570; letter-spacing:.08em; text-transform:uppercase }}
  table {{ width:100%; border-collapse:collapse }}
  td {{ padding:10px 18px; border-bottom:1px solid #0f1e2e; vertical-align:middle }}
  tr:last-child td {{ border-bottom:none }}
  tr:hover td {{ background:#0f1e2e }}
  .recs {{ padding:16px 18px }}
  ul {{ list-style:none; padding-left:0 }}
  ul li::before {{ content:"→ "; color:#3d5570; font-family:'IBM Plex Mono',monospace }}
  .footer {{ text-align:center; margin-top:28px;
             font-family:'IBM Plex Mono',monospace; font-size:11px; color:#1e3048 }}
</style>
</head>
<body>
<div class="wrap">

  <div class="header">
    <div>
      <div class="brand">SAP HANA Health Report</div>
      <div class="title">System: {sys.get('DATABASE_NAME','HXE')}</div>
      <div class="meta">
        v{sys.get('VERSION','—')} &nbsp;·&nbsp;
        Usage: {sys.get('USAGE','—')} &nbsp;·&nbsp;
        Started: {sys.get('START_TIME','—')}
      </div>
    </div>
    <div style="display:flex;flex-direction:column;align-items:flex-end;gap:8px">
      <span class="source-badge">{'● LIVE DATA' if source=='LIVE' else '◌ DEMO DATA'}</span>
      <span style="font-family:'IBM Plex Mono',monospace;font-size:11px;color:#3d5570">
        {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
      </span>
    </div>
  </div>

  <!-- Refresh Button -->
  <div style="text-align:right;margin-bottom:20px">
    <form method="post" action="/run">
      <button style="padding:8px 20px;background:#00a8ff;color:#fff;
                     border:none;border-radius:5px;cursor:pointer;
                     font-family:'IBM Plex Mono',monospace;font-size:12px">
        ↻ Generate New Report
      </button>
    </form>
  </div>

  <!-- Score Card -->
  <div class="score-card">
    <div class="score-ring">
      <svg width="100" height="100" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r="42" fill="none" stroke="#1a2d42" stroke-width="8"/>
        <circle cx="50" cy="50" r="42" fill="none"
          stroke="{grade_colour}" stroke-width="8" stroke-linecap="round"
          stroke-dasharray="{2*3.14159*42:.1f}"
          stroke-dashoffset="{2*3.14159*42*(1-score/100):.1f}"/>
      </svg>
      <div class="score-num">
        <span>{score}</span><span>/100</span>
      </div>
    </div>
    <div class="score-info">
      <div class="grade">{grade}</div>
      <div class="summary-text">{analysis.get('summary','')}</div>
    </div>
  </div>

  <!-- AI Findings -->
  <div class="section">
    <div class="section-head">AI Analysis — Health Findings</div>
    <table>{findings_html}</table>
  </div>

  <!-- Services -->
  <div class="section">
    <div class="section-head">HANA Services (SYS.M_SERVICES)</div>
    <table>{services_html}</table>
  </div>

  <!-- Memory -->
  <div class="section">
    <div class="section-head">Memory Utilisation (SYS.M_SERVICE_MEMORY)</div>
    <table>{memory_html}</table>
  </div>

  <!-- Disk -->
  <div class="section">
    <div class="section-head">Disk Usage (SYS.M_DISK_USAGE)</div>
    <table>{disk_html}</table>
  </div>

  <!-- Backup -->
  <div class="section">
    <div class="section-head">Last Backup (SYS.M_BACKUP_CATALOG)</div>
    <table>
      <tr>
        <td style="font-family:monospace;font-size:13px;color:#7eb8d4">{backup_row.get('ENTRY_TYPE_NAME','—')}</td>
        <td style="font-family:monospace;font-size:12px;color:#4a6a84">{backup_ts}</td>
        <td style="font-family:monospace;font-size:12px;color:{backup_c};font-weight:600">{backup_st.upper()}</td>
      </tr>
    </table>
  </div>

  <!-- Recommendations -->
  <div class="section">
    <div class="section-head">Recommended Actions</div>
    <div class="recs"><ul>{recs_html}</ul></div>
  </div>

  <div class="footer">
    Generated by HANA Health Reporter &nbsp;·&nbsp;
    Powered by Anthropic Claude API &nbsp;·&nbsp;
    Deployed on SAP BTP Cloud Foundry
  </div>

</div>
</body>
</html>"""


# ── Entry point ───────────────────────────────────────────────────────────────

def generate_report(output_path: str = "report.html") -> str:
    """Full pipeline: collect → analyse → render → save. Returns HTML string."""
    print("  Collecting HANA metrics...")
    metrics  = collect_metrics()
    print(f"  Source: {metrics['source'].upper()}")

    print("  Calling Claude API for analysis...")
    analysis = analyse_with_claude(metrics)
    print(f"  Score: {analysis.get('score')}/100 — {analysis.get('grade')}")

    print("  Rendering HTML report...")
    html = render_html(metrics, analysis)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Report saved → {output_path}")

    return html


if __name__ == "__main__":
    generate_report("report.html")
    print("\n  Open report.html in your browser.")
