# HANA Health Reporter

> A Python script that queries SAP HANA system monitoring views, sends the
> metrics to Claude API for Basis analysis, and renders a self-contained
> HTML health report — deployable on SAP BTP Cloud Foundry.

---
## Live Demo
https://hana-health-reporter.cfapps.us10-001.hana.ondemand.com/


## What This Demonstrates

| Skill | Evidence |
|---|---|
| **SAP Basis** | Queries real HANA monitoring views: M_SERVICES, M_SERVICE_MEMORY, M_DISK_USAGE, M_BACKUP_CATALOG |
| **Python** | hdbcli HANA driver, environment-based secrets, HTML generation, modular functions |
| **Claude API** | Structured JSON prompt → AI-generated Basis health analysis and recommendations |
| **SAP BTP** | Cloud Foundry deployment via manifest.yml and cf CLI |

---

## Project Structure

```
hana-health-reporter/
├── reporter.py       ← core: collect metrics → call Claude → render HTML
├── app.py            ← Flask server for BTP deployment
├── manifest.yml      ← CF deployment config
├── requirements.txt
└── .env.template     ← copy to .env, add your credentials
```

---

## Run Locally

```bash
# Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.template .env
# Edit .env — add ANTHROPIC_API_KEY at minimum

# Demo mode (no HANA needed)
DEMO_MODE=true python reporter.py
# → opens report.html

# Live HANA (after creating read-only user — see below)
python reporter.py
```

---

## HANA Setup (one-time, run as SYSTEM)

```sql
CREATE USER HANA_REPORTER PASSWORD "YourPassword!" NO FORCE_FIRST_PASSWORD_CHANGE;
GRANT CATALOG READ TO HANA_REPORTER;
GRANT SELECT ON SYS.M_DATABASE             TO HANA_REPORTER;
GRANT SELECT ON SYS.M_SERVICES             TO HANA_REPORTER;
GRANT SELECT ON SYS.M_SERVICE_MEMORY       TO HANA_REPORTER;
GRANT SELECT ON SYS.M_DISK_USAGE           TO HANA_REPORTER;
GRANT SELECT ON SYS.M_BACKUP_CATALOG       TO HANA_REPORTER;
```

---

## Deploy to SAP BTP

```bash
cf login -a https://api.cf.ap10.hana.ondemand.com
cf target -o trial-org -s dev
cf set-env hana-health-reporter ANTHROPIC_API_KEY sk-ant-...
cf set-env hana-health-reporter DEMO_MODE true
cf push
# Live at: https://hana-health-reporter.cfapps.ap10.hana.ondemand.com
```

---

**Stack:** Python 3.11 · Anthropic Claude API · SAP hdbcli · Flask · SAP BTP Cloud Foundry
