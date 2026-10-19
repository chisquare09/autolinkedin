# LinkedIn Activity Tracker

This repository contains the current Apps Script implementation for collecting
LinkedIn activity with PhantomBuster, importing it into Google Sheets, and
generating post summaries with Gemini.

The production workflow is Apps Script-only. The older Cloud Run functions are
kept under `cloud_function/` for reference and legacy maintenance

## Architecture

```text
Google Sheets: customer_info
        |
        v
Apps Script: schedulePhantomRun
        |
        v
PhantomBuster Activity Extractor
        |
        v
Apps Script: retryIncompleteWork
        |
        v
Combined result.csv
        |
        v
Weekly Google Sheet tab
        |
        v
Apps Script: summarizeImportedWeek
        |
        v
Gemini structured summaries
```

The workflow uses PhantomBuster's permanent Agent ID and polls the launch
Container ID until it finishes. With **Combine files** enabled, the result CSV
is cumulative. Apps Script therefore calculates stable post keys and imports
only rows that have not already been recorded.

## Repository structure

```text
autolinkedin/
├── apps_scripts/
│   ├── PhantomAutomation.gs       # Phantom launch, polling, import, logging
│   ├── SummarizationAutomation.gs # Gemini summarization and validation
│   └── .env                       # Configuration template; not read at runtime
├── cloud_function/
│   ├── phantom_function/          # Legacy Cloud Run ingestion function
│   └── summarize_function/        # Legacy Cloud Run summarization function
├── docs/
│   ├── project_requirement.md
│   ├── coding_implementation_plan.md
│   └── testing_guide.md
├── tests/
│   ├── test_apps_script_workflow.py
│   └── test_cloud_functions.py
└── README.md
```

## Google Sheets setup

Create a visible input tab named `customer_info` with these exact headers in
row 1:

```text
customer_name | linkedin_profile_url
```

Add one customer or LinkedIn profile per row. The URLs must be valid LinkedIn
URLs. Do not place API keys, LinkedIn session cookies, or other secrets in the
workbook.

Apps Script creates weekly tabs using this format:

```text
DD - DD MMM YYYY
```

For example:

```text
11 - 17 Oct 2026
```

Each weekly tab contains all raw columns returned by PhantomBuster followed by:

```text
content_summary
content_type
processing_status
processing_error
```

The workflow may also create these technical tabs:

- `_automation_state`: hidden deduplication and run state;
- `_automation_log`: persistent progress and error history.

Do not edit either technical tab manually.

## PhantomBuster setup

Configure the permanent PhantomBuster Activity Extractor Agent to:

- accept the Google Sheet URL supplied by Apps Script;
- read profile URLs from `linkedin_profile_url`;
- scrape `Post` activities;
- use a valid LinkedIn session;
- use **Combine files** for result storage;
- produce `result.csv`.

Copy the permanent Agent ID into the Apps Script Script Properties. Apps Script
uses the returned Container ID to poll the launch and uses `/agents/fetch` to
retrieve the accumulated result-file metadata.

## Apps Script installation

Add the following properties in **Apps Script → Project Settings → Script
properties**:

```text
PHANTOMBUSTER_API_KEY=<PhantomBuster API key>
PHANTOMBUSTER_AGENT_ID=<permanent PhantomBuster Agent ID>
GEMINI_API_KEY=<Gemini API key>
GEMINI_MODEL=<Gemini model name>
TIMEZONE=Australia/Brisbane
WEEK_START_DAY=SUNDAY
SCHEDULE_DAY=SUNDAY
SCHEDULE_TIME=00:15
ENABLE_MANUAL_TEST_MENU=false
```

Use the appropriate IANA timezone for the deployment. `TIMEZONE` controls
reporting-period calculations, date filtering, weekly worksheet names, and
trigger creation.

`WEEK_START_DAY` defines the reporting-period boundary. 
`SCHEDULE_DAY` defines
when the weekly launch runs. They may differ, but the scheduled run must occur
after the reporting period closes.

## Production triggers

Run `configureTriggers()` once from the Apps Script editor after setting the
Script Properties and approving the requested permissions. It creates the
permanent weekly launcher:

| Function | Frequency | Purpose |
|---|---|---|
| `schedulePhantomRun` | Weekly at `SCHEDULE_DAY` and `SCHEDULE_TIME` | Launches PhantomBuster |

When a PhantomBuster run starts, `schedulePhantomRun` creates the two temporary
worker triggers below. They run hourly only while work is active:

| Function | Frequency while active | Purpose |
|---|---:|---|
| `retryIncompleteWork` | Every hour | Polls the active container and imports finished CSV results |
| `summarizeImportedWeek` | Every hour | Summarizes pending weekly-sheet rows with Gemini |

After import and summarization finish, the worker triggers delete themselves.
The next weekly launch creates them again. `configureTriggers()` also removes
any old worker triggers before installing the permanent weekly launcher.

An hourly worker execution is only a lightweight progress check. If there are
no active PhantomBuster runs or pending rows, it exits without launching
PhantomBuster or calling Gemini. In particular, a log entry such as:

```text
Found 0 unsummarized row(s).
Finished: 0 processed, 11 skipped, 0 failed.
```

means that no Gemini request was sent and no Gemini tokens or API fees were
incurred for that execution.

Google time-driven triggers run approximately at the configured time and may
apply a small scheduling window.

After live testing, keep:

```text
ENABLE_MANUAL_TEST_MENU=false
```

## Manual testing menu

For controlled testing only, set:

```text
ENABLE_MANUAL_TEST_MENU=true
```

Refresh the spreadsheet. The temporary menu will contain:

- **Phantom Data Scraping**: launches PhantomBuster and polls once;
- **Content Summarization**: runs Gemini summarization immediately.

The Phantom process may still be running after the manual scraping action
returns. Run `retryIncompleteWork()` after PhantomBuster finishes, or wait for
the temporary hourly recovery trigger. The worker triggers stop after all
imported rows are completed or marked failed.


## Monitoring

The `_automation_log` tab is the authoritative progress history. Important
steps include:

```text
PHANTOM_LAUNCH
PHANTOM_POLL
PHANTOM_IMPORT
GEMINI_SUMMARY
```

A normal successful run eventually records:

```text
Launched container ...
Container ... status: finished.
Imported N new row(s); skipped M.
Found N unsummarized row(s).
Finished: N processed, 0 skipped, 0 failed.
```

Spreadsheet toasts show the current step while the workbook is open, but
`_automation_log` remains available after the toast disappears.


For the complete setup, production workflow, and remaining live integration
checks, see [`docs/testing_guide.md`](docs/testing_guide.md).
