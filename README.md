# LinkedIn Activity Tracker

This repository contains the coding portion of the LinkedIn weekly activity
pipeline described in `docs/coding_implementation_plan.md`. Project
requirements and integration decisions are documented in
`docs/project_requirement.md`; PhantomBuster and Google Cloud resources are
configured separately during integration.

## Local validation

The retained tests load each Cloud Run function directly and mock Google Sheets
and Gemini integrations:

```bash
python -m pytest -q
```

The deployed functions use the Google runtime service account for Sheets and
Drive access. Keep `.env` and service-account key files local; never commit
them.

## Cloud Run function prototype

The `cloud_function/` directory contains two independently deployable Cloud
Run functions. Each function is self-contained and has its own dependencies:

```text
phantom_function/
  main.py
  requirements.txt
summarize_function/
  main.py
  requirements.txt
```

Deploy `cloud_function/phantom_function` with the function entry point
`phantom_webhook`. Configure PhantomBuster to call this function. Deploy
`cloud_function/summarize_function` with the function entry point
`summarization_webhook`, and configure Apps Script to call this function.
Both functions use Python 3.11 or later. The Phantom function requires:

```text
OUTPUT_SPREADSHEET_ID
WEBHOOK_BEARER_TOKEN
WEBHOOK_SECRET
REPORTING_TIMEZONE=Australia/Brisbane
```

The summarization function requires:

```text
OUTPUT_SPREADSHEET_ID
GEMINI_API_KEY
WEBHOOK_BEARER_TOKEN
WEBHOOK_SECRET
GEMINI_MODEL_NAME=gemini-3.8-flash
MAX_POSTS_PER_GEMINI_REQUEST=10
REPORTING_TIMEZONE=Australia/Brisbane
```

The ingestion function handles `POST /webhook` directly and writes Phantom
results to the `phantom_result` sheet without invoking Gemini. The
summarization function handles `POST /webhook` directly, reads
`phantom_result`, skips already summarized post keys, invokes Gemini, and
writes the processed output tabs. Both functions respond to `GET /health` when
the deployment platform preserves the request path.

PhantomBuster sends its normal result payload (or an `action` of
`ingest_results`) to the ingestion function. The Apps Script menu sends
`action=process_week` to the summarization function. This preserves the
prototype's direct-processing behavior while keeping ingestion and
summarization in separate deployments.
The processing action scans all raw rows, summarizes only post keys that are not
already present in `post_details`, and assigns each new post to the week derived
from its timestamp. This allows one button click to backfill older weeks without
changing an Apps Script date property. The Apps Script menu asks for an inclusive
`YYYY-MM-DD` start and end date, so historical data can be processed in smaller
ranges. Scraping errors are reported per affected customer where the payload
contains a matching profile.

PhantomBuster custom webhooks do not support custom request headers. Configure
its webhook URL with a query secret:

```text
https://<function-url>?secret=<WEBHOOK_SECRET>
```

Set `WEBHOOK_SECRET` in Cloud Run. For the prototype it may equal
`WEBHOOK_BEARER_TOKEN`, but a separate secret is preferred. Apps Script and
terminal requests may continue using the `Authorization: Bearer` header.
