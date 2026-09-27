# LinkedIn Activity Tracker

This repository contains the coding portion of the LinkedIn weekly activity
pipeline described in `docs/coding_implementation_plan.md`. Project
requirements and integration decisions are documented in
`docs/project_requirement.md`; PhantomBuster and Google Cloud resources are
configured separately during integration.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
uvicorn main:app --reload
```

The application does not need Google credentials for the core unit and fixture
tests. Cloud adapters are exercised through mocks in integration tests and use
Application Default Credentials when deployed.

## Runtime endpoints

- `GET /health` checks service availability.
- `POST /webhook` authenticates a PhantomBuster completion payload and publishes
  a durable Pub/Sub job.
- `POST /pubsub` accepts a Pub/Sub push envelope and processes a queued job.

The production worker reads the retained Pub/Sub payload, loads the
`customer_info` sheet, summarizes qualifying posts with Gemini, and upserts
`post_details` and `weekly_summary`. Google Sheets is the only application data
store.

## Configuration

Required runtime configuration includes:

```text
OUTPUT_SPREADSHEET_ID
PUBSUB_TOPIC
PUBSUB_SUBSCRIPTION
GEMINI_API_KEY
WEBHOOK_AUTH_MODE=bearer
WEBHOOK_BEARER_TOKEN
REPORTING_TIMEZONE=Australia/Brisbane
GEMINI_MODEL_NAME=gemini-2.5-flash
```

Use Secret Manager for credentials and tokens. Do not commit `.env` files or
service-account key files.

## Deployment

The scripts under `scripts/` enable the required APIs, create the Pub/Sub
processing and dead-letter resources with three delivery attempts and message
retention, and deploy the container with Secret Manager references. Set
`PROJECT_ID`, `SERVICE_ACCOUNT`, `PUBSUB_TOPIC`, `PUBSUB_SUBSCRIPTION`,
`OUTPUT_SPREADSHEET_ID`, and create the `GEMINI_API_KEY` and
`WEBHOOK_BEARER_TOKEN` secrets before running them. Configure authenticated
Pub/Sub push delivery to `/pubsub` using the runtime service account before
production use.
