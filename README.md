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

Set `PROCESSING_MODE=direct` for a short-lived prototype deployment without
Pub/Sub. In direct mode, `/webhook` processes the payload synchronously and
returns only after Gemini and Sheets processing complete. The default
`PROCESSING_MODE=pubsub` remains the production path.

The worker reads the job payload, loads the `customer_info` sheet, summarizes
qualifying posts with Gemini, and upserts `post_details` and `weekly_summary`.

## Configuration

Required runtime configuration includes:

```text
OUTPUT_SPREADSHEET_ID
PROCESSING_MODE=direct
GEMINI_API_KEY
WEBHOOK_AUTH_MODE=bearer
WEBHOOK_BEARER_TOKEN
REPORTING_TIMEZONE=Australia/Brisbane
GEMINI_MODEL_NAME=gemini-3.8-flash
MAX_POSTS_PER_GEMINI_REQUEST=10
```

Use Secret Manager for credentials and tokens. Do not commit `.env` files or
service-account key files.

## Deployment

The scripts under `scripts/` create the basic Google Cloud resources and deploy
the container. Review the generated IAM bindings and configure authenticated
Pub/Sub push delivery before production use.

For a quota-limited prototype without Pub/Sub, use
`scripts/deploy-direct.sh` with `PROCESSING_MODE=direct`. Direct mode processes
the webhook synchronously and should only be used for a few manual tests.

## Cloud Run function prototype

The `cloud_function/` directory is a standalone, direct-processing prototype
for the Cloud Run function deployment option. Upload only these two files from
that directory:

```text
main.py
requirements.txt
```

Set the function entry point to `phantom_webhook`, runtime to Python 3.11 or
later, and configure these environment variables:

```text
OUTPUT_SPREADSHEET_ID
GEMINI_API_KEY
WEBHOOK_BEARER_TOKEN
GEMINI_MODEL_NAME=gemini-3.8-flash
MAX_POSTS_PER_GEMINI_REQUEST=10
REPORTING_TIMEZONE=Australia/Brisbane
```

The function handles `POST /webhook` directly and writes to Google Sheets
without Pub/Sub. It also responds to `GET /health` when the deployment
platform preserves the request path. This is intentionally a prototype
deviation from the production plan: the modular application and Pub/Sub path
remain the production implementation.

The function supports two direct-mode actions. PhantomBuster sends its normal
result payload (or an `action` of `ingest_results`) to append/upsert raw rows in
`phantom_result`. The Apps Script menu sends `action=process_week`; the function
then reads `phantom_result`, skips already summarized post keys, and writes the
processed output tabs.
The processing action scans all raw rows, summarizes only post keys that are not
already present in `post_details`, and assigns each new post to the week derived
from its timestamp. This allows one button click to backfill older weeks without
changing an Apps Script date property.

PhantomBuster custom webhooks do not support custom request headers. Configure
its webhook URL with a query secret:

```text
https://<function-url>?secret=<WEBHOOK_SECRET>
```

Set `WEBHOOK_SECRET` in Cloud Run. For the prototype it may equal
`WEBHOOK_BEARER_TOKEN`, but a separate secret is preferred. Apps Script and
terminal requests may continue using the `Authorization: Bearer` header.
