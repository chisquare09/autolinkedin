# LinkedIn Activity Tracker

This repository contains the production code for collecting LinkedIn activity
with PhantomBuster, storing the raw results in Google Sheets, and generating
post and weekly summaries with Gemini. The requirements and historical design
notes are documented in `docs/project_requirement.md` and
`docs/coding_implementation_plan.md`.

## Codebase structure

```text
autolinkedin/
├── cloud_function/
│   ├── AppsScript.gs              # Spreadsheet menu and Cloud Run client
│   ├── phantom_function/          # Independently deployable Phantom ingestion
│   │   ├── main.py                # PhantomBuster webhook and raw Sheets ingestion
│   │   └── requirements.txt       # Phantom ingestion deployment dependencies
│   └── summarize_function/        # Independently deployable Gemini summarization
│       ├── main.py                # Sheets reader, Gemini, and output upserts
│       └── requirements.txt       # Summarization deployment dependencies
├── data/                           # Local workbook and export samples
│   ├── Linkedin Summarize.xlsx
│   └── result.xls
├── docs/                           # Requirements and design reference documents
│   ├── project_requirement.md
│   └── coding_implementation_plan.md
├── tests/
│   └── test_cloud_functions.py     # Tests for both Cloud Run functions
├── .env                            # Local environment values; ignored by Git
├── .gitignore                      # Ignore rules for local and generated files
└── README.md                       # Project documentation
```

The two Python function directories are intentionally self-contained and are
deployed independently. Each directory has its own `main.py` and
`requirements.txt`; the repository root is not a deployable Python
application.

## Architecture

```text
┌──────────────────────┐
│ PhantomBuster         │
│ LinkedIn extractor    │
└──────────┬───────────┘
           │ POST /webhook
           │ ?secret=WEBHOOK_SECRET
           ▼
┌──────────────────────────────┐
│ Cloud Run: Phantom function  │
│ entry: phantom_webhook       │
│                              │
│ validate → normalize         │
│ deduplicate → write raw data │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│ Google Sheets                │
│ phantom_result              │
│ customer_info               │
└──────────┬───────────────────┘
           │
           │ User selects “Weekly Summarize”
           ▼
┌──────────────────────────────┐
│ Google Apps Script           │
│ cloud_function/AppsScript.gs│
│ POST action=process_week     │
└──────────┬───────────────────┘
           │ Authorization: Bearer token
           ▼
┌──────────────────────────────┐
│ Cloud Run: Summarization     │
│ entry: summarization_webhook │
│                              │
│ read → filter → deduplicate  │
│ Gemini → upsert outputs      │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│ Google Sheets                │
│ post_details                 │
│ weekly_summary               │
└──────────────────────────────┘
```


## Configuration

### Cloud Run deployments

Deploy the two directories separately with Python buildpacks in
`australia-southeast1`:

| Cloud Run function | Source directory | Entry point |
|---|---|---|
| Phantom ingestion | `cloud_function/phantom_function` | `phantom_webhook` |
| Summarization | `cloud_function/summarize_function` | `summarization_webhook` |


### Phantom environment

```text
OUTPUT_SPREADSHEET_ID=<Google Sheets workbook ID>
REPORTING_TIMEZONE=Australia/Brisbane
WEBHOOK_SECRET=<query-string secret used by PhantomBuster>
WEBHOOK_BEARER_TOKEN=<optional bearer token for non-Phantom requests>
```

PhantomBuster custom webhooks should use the query-secret URL because custom
headers are not available:

```text
https://<phantom-cloud-run-url>/webhook?secret=<WEBHOOK_SECRET>
```

The webhook expects PhantomBuster's normal JSON result payload. It also accepts
an `action` field only when its value is `ingest_results`.

### Cloud Run environment

```text
OUTPUT_SPREADSHEET_ID=<Google Sheets workbook ID>
REPORTING_TIMEZONE=Australia/Brisbane
WEBHOOK_BEARER_TOKEN=<token used by Apps Script>
WEBHOOK_SECRET=<optional query secret>
GEMINI_API_KEY=<Gemini API key>
GEMINI_MODEL_NAME=gemini-3.8-flash
MAX_POSTS_PER_GEMINI_REQUEST=10
```

Apps Script

```http
Authorization: Bearer <WEBHOOK_BEARER_TOKEN>
```

```javascript
const SUMMARIZATION_FUNCTION_URL = 'https://<summarization-cloud-run-url>';
```

Add `WEBHOOK_BEARER_TOKEN` to the bound Apps Script project's Script
Properties. The spreadsheet must contain these sheets:

```text
customer_info
phantom_result
post_details
weekly_summary
```

Use Secret Manager or Cloud Run's secret integration for API keys and webhook
tokens. The runtime service account needs access to the target spreadsheet and
Drive as required by the Google Sheets client.

## Local validation

Install test dependencies in a local virtual environment, then run:

```bash
python -m pytest -q
python -m py_compile \
  cloud_function/phantom_function/main.py \
  cloud_function/summarize_function/main.py
git diff --check
```

The tests load both function modules directly and mock Google Sheets and Gemini
integrations. The Cloud Run dependency manifests remain separate because the
functions are deployed independently.
