# Apps Script Implementation Plan

## 1. Scope and confirmed direction

The next implementation will move the runtime workflow from Cloud Run to
Google Apps Script. The existing `cloud_function/` directory is out of scope
for this change and must not be modified.

Create a new top-level folder:

```text
apps_scripts/
├── PhantomAutomation.gs       # PhantomBuster launch, polling, and raw import
└── SummarizationAutomation.gs # Gemini content summaries and sheet updates
```

The two scripts may be copied into one spreadsheet-bound Apps Script project or
kept as separate script projects, but they must share the same workbook
configuration and Script Properties. The implementation should use separate
functions and responsibilities so Phantom execution and Gemini processing can be
run, scheduled, and retried independently.

The first release covers:

1. Launching a PhantomBuster agent on a schedule through the PhantomBuster API.
2. Receiving the completed run's CSV download link.
3. Creating a new weekly worksheet before importing the CSV.
4. Importing the CSV into that worksheet.
5. Adding a `content_summary` column to that worksheet.
6. Calling Gemini from Apps Script to summarize each post.
7. Writing each validated summary back to the same weekly worksheet.
8. Using Gemini `ThinkingConfig` at `LOW`.

Weekly, multi-post company synthesis is explicitly deferred. The future
`weekly_summarize` value may be added as a column later, but no
`weekly_summary` worksheet is created by this plan.

## 2. Target workbook design

### 2.1 Existing and retained sheet

`customer_info` remains the only permanent input sheet. It is the source used
to configure the Phantom run and must retain:

```text
customer_name
linkedin_profile_url
```

The script must validate required headers, reject empty profile URLs, and
normalize duplicate profile rows before building the Phantom request.

### 2.2 Weekly result sheets

Remove the operational dependency on these old tabs:

```text
phantom_result
post_details
weekly_summary
```

For each completed run, create or reuse one worksheet dedicated to that
reporting period. The worksheet name must be deterministic and collision-safe,
for example:

```text
04 - 10 Oct 2025
```

The intended display format is:

```text
DD - DD MMM YYYY
```

For example, a reporting period from 4 October through 10 October 2025 must
use:

```text
04 - 10 Oct 2025
```

This format is valid for a Google Sheets tab because it uses only numbers,
letters, spaces, and hyphens. The implementation must not use a colon or other
restricted sheet-name characters.

The name must be generated from the reporting window rather than the execution
date. If a worksheet with the same name already exists, the script must reuse
it after verifying that it belongs to the same stored Phantom container/run.
It must not create a suffix such as `(1)` because that would make retries
non-idempotent and could create duplicate weekly data.

Use a closed reporting period rather than calculating “the last seven days”
from the trigger time. The recommended first convention is calendar
Sunday–Saturday in the configured reporting timezone. The Phantom run should
start after that Saturday has ended, for example shortly after Sunday 00:15,
so the worksheet named `04 - 10 Oct 2025` represents the complete period.

Running at Saturday 12:59 PM cannot produce a complete Sunday–Saturday week:
posts published between 12:59 PM and midnight on Saturday do not exist yet.
If the business requires the trigger to run at Saturday 12:59 PM, it must be
defined as a partial/current-period run or as a rolling window, not as a
complete weekly report.

The chosen week boundary must be centralized in one date-window helper and
used for worksheet naming, Phantom date parameters, duplicate detection, and
logging. To protect against provider delays and late-arriving records, each
run should use a small overlap with the previous period where the Phantom
filter supports it, then deduplicate by a stable post URL or provider post ID.
An optional recovery trigger should re-fetch the most recent closed period and
upsert missing rows. This is necessary because no schedule can guarantee
complete historical coverage if PhantomBuster or LinkedIn returns delayed
results.

The weekly worksheet contains:

1. All source columns imported from PhantomBuster's CSV, preserving the raw
   values.
2. Any normalized fields needed for matching and diagnostics.
3. A final `content_summary` column appended after the last source column.

The first row is the header row. Every imported post occupies one row. If a
Phantom result contains an error or malformed item, preserve it in the weekly
sheet where possible and record a visible processing status/error column rather
than silently dropping it.

Recommended pipeline columns are:

```text
content_summary
processing_status
processing_error
processed_at
```

Only `content_summary` is required for the first business release; the status
columns are strongly recommended because Apps Script executions can be retried
or exceed runtime quotas.

## 3. End-to-end workflow

```text
customer_info
      |
      | scheduled Apps Script trigger
      v
PhantomAutomation.gs
      |
      | POST /api/v2/agents/launch
      | x-phantombuster-key
      v
PhantomBuster agent
      |
      | completed run: CSV download link from result API
      v
PhantomAutomation.gs
      |
      | create worksheet, then import CSV
      v
04 - 10 Oct 2025 worksheet
      |
      | SummarizationAutomation.gs reads unsummarized rows
      v
Gemini API
      |
      | structured response, ThinkingConfig LOW
      v
content_summary column in the same weekly worksheet
```

The Phantom script must not invoke Gemini. The summarization script must not
launch Phantom. This separation allows either stage to be rerun without
starting another scrape.

## 4. Implementation phases

### Phase 0: Confirm external contracts and decisions

1. Confirm the Phantom agent ID, API base URL, authentication header, result
   retrieval endpoint, and completion response format. The currently tested
   launch request uses the agent ID only. For per-run customer data, prefer
   the single-use `bonusArgument`, which PhantomBuster merges with the saved
   agent argument without changing the saved configuration.
2. Confirm the exact LinkedIn Activity Extractor argument schema from its JSON
   setup/API view. The supplied configuration uses `spreadsheetUrl`,
   `columnName`, `activitiesToScrape`, `onlyRetrieveActivitiesAfterDate`,
   `dateAfter`, `numberOfLinesPerLaunch`, `numberMaxOfPosts`, `csvName`,
   `sessionCookie`, and `userAgent`.
3. Configure and verify PhantomBuster Persistent session separately. The
   Session key belongs in the Phantom's Advanced settings and must match the
   key used by the connected LinkedIn browser session; it is not an Apps
   Script launch argument.
4. Confirm the PhantomBuster result response field containing the completed CSV
   download link and its expiry/access requirements.
5. Confirm the reporting timezone and choose the closed reporting period
   convention, preferably Sunday–Saturday.
6. Confirm the maximum expected row count so Gemini calls can be batched within
   Apps Script execution and URL fetch quotas.
7. Confirm the Gemini model and API endpoint that support structured output and
   `thinkingConfig`.
8. Confirm the acceptable trigger-time tolerance because Apps Script time-based
   triggers are approximate rather than exact to the configured minute.

Deliverable: a short configuration table in the new scripts and this plan
updated with the final external API choices.

### Phase 1: Create shared Apps Script configuration and helpers

Implement small, testable helpers in `apps_scripts/` for:

- reading required Script Properties;
- validating and normalizing `customer_info`;
- calculating the selected reporting window;
- sanitizing and truncating worksheet names only when required by Sheets;
- creating or reusing a unique weekly worksheet before CSV import;
- importing and parsing the Phantom CSV;
- reading headers and rows as objects;
- finding the `content_summary` column;
- escaping/logging errors without exposing secrets.

Required Script Properties:

```text
PHANTOMBUSTER_API_KEY
PHANTOMBUSTER_AGENT_ID
GEMINI_API_KEY
GEMINI_MODEL
REPORTING_TIMEZONE
WEEK_START_DAY
SCHEDULE_TIMEZONE
SCHEDULE_DAY
SCHEDULE_TIME
ENABLE_MANUAL_TEST_MENU=false
```

The PhantomBuster key and Gemini key must never be hardcoded, returned in
alerts, or written to logs.

Apps Script does not use the repository `.env` file at runtime. These values
must be stored as Apps Script Project Settings > Script Properties. The
`GEMINI_MODEL` property is read in the same way as the scheduling properties.
`SCHEDULE_TIMEZONE` controls date calculations and trigger creation,
`SCHEDULE_DAY` identifies the weekday, and `SCHEDULE_TIME` defines the
requested local trigger time using the `HH:mm` format.

The script should expose a `configureTriggers()` function that removes and
recreates only this project's managed triggers using those properties. The
trigger builder should validate `SCHEDULE_TIME` and use the configured
timezone, weekday, and parsed hour/minute.
Apps Script time-driven triggers are approximate: `nearMinute(59)` means
approximately that minute, not a hard real-time guarantee. The plan should
therefore use a recovery trigger and store the actual execution timestamp.
If exact 12:59 execution is mandatory, an external scheduler is required.

Example configuration for a complete Sunday–Saturday report:

```text
SCHEDULE_TIMEZONE=Australia/Brisbane
SCHEDULE_DAY=SUNDAY
SCHEDULE_TIME=00:15
```

Example configuration for the user's proposed Saturday trigger:

```text
SCHEDULE_TIMEZONE=Australia/Brisbane
SCHEDULE_DAY=SATURDAY
SCHEDULE_TIME=12:59
```

The second configuration is valid as a trigger setting, but it must be treated
as a partial/current-period collection or rolling window. It must not be
recorded as a complete Sunday–Saturday worksheet unless a later reconciliation
run collects the remaining Saturday data.

### Phase 2: Implement Phantom automation

Implement `PhantomAutomation.gs` in this order:

1. Read and validate `customer_info`.
2. Compute the most recent closed reporting window in `SCHEDULE_TIMEZONE`.
   Do not use the current partial day as a completed weekly period.
3. Build the Phantom agent launch payload from the configured agent ID. If the
   customer list is supplied by Apps Script, use the workbook containing
   `customer_info` as the extractor's input spreadsheet and send the
   spreadsheet/date overrides through `bonusArgument`. Use the persistent
   `argument` only for stable agent configuration; use `bonusArgument` for
   values that belong to the current weekly run.
4. Call:

   ```http
   POST https://api.phantombuster.com/api/v2/agents/launch
   Content-Type: application/json
   x-phantombuster-key: <Script Property>
   ```

   with this JSON body:

   ```json
   {
     "id": "3698329298804919"
   }
   ```

   The agent ID must come from the `PHANTOMBUSTER_AGENT_ID` Script Property,
   and the API key must come from `PHANTOMBUSTER_API_KEY`.
   The preferred dynamic form for this Activity Extractor is:

   ```json
   {
     "id": "3698329298804919",
     "bonusArgument": {
       "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/<WORKBOOK_ID>/edit",
       "columnName": "linkedin_profile_url",
       "activitiesToScrape": ["Post"],
       "onlyRetrieveActivitiesAfterDate": true,
       "dateAfter": "10-01-2026",
       "numberOfLinesPerLaunch": 10,
       "numberMaxOfPosts": 20,
       "csvName": "result"
     }
   }
   ```

   PhantomBuster merges this one-time object with the saved agent argument,
   and the resulting effective configuration is available to the agent through
   `buster.argument`. The extractor then reads the profile URLs from the
   configured spreadsheet column; Apps Script does not send a
   `customerProfiles` array because that is not part of this extractor's
   documented input schema.

   `spreadsheetUrl` must point to a workbook that PhantomBuster can access, and
   `columnName` must exactly match the header in the input sheet. The
   `customer_info` sheet must therefore be available according to the
   extractor's access requirements and contain the `linkedin_profile_url`
   header.

   `numberOfLinesPerLaunch` and `numberMaxOfPosts` are provider-side limits,
   not guarantees of complete weekly coverage. Before production, verify that
   `numberOfLinesPerLaunch` covers all configured customer rows or implement
   controlled batching, and verify that `numberMaxOfPosts` is high enough for
   the selected reporting period. A value of `20` must not be treated as
   “retrieve every post” unless the extractor documentation confirms that
   behavior.

   Keep `sessionCookie` and `userAgent` in the saved Phantom configuration or
   inject them from protected Script Properties only if the API workflow
   requires it. Never commit or log either value. `bonusArgument` must not
   contain the Phantom API key or Gemini API key.

   The Persistent session `Session key` is different from the
   `PHANTOMBUSTER_API_KEY`. It identifies PhantomBuster's stored browser-data
   slot and should normally remain configured on the Phantom side. Do not add
   it to the Apps Script payload unless PhantomBuster's API explicitly requires
   a launch-level persisted-volume field for this agent.

   Configure PhantomBuster File management as **Create new files** for the
   weekly-tab design. Each completed launch should produce a separate result
   file that Apps Script imports into the worksheet for that reporting period.
   Because this mode reprocesses the configured input from the beginning on
   every launch, `dateAfter`, post limits, and Apps Script deduplication remain
   necessary.

   Set PhantomBuster's **Number of folders to keep** to `53` for this weekly
   workflow. This retains approximately one year of result folders, including
   an extra week for calendar variation and recovery. Configure this value in
   PhantomBuster's File management settings; it is not an Apps Script property
   and is not sent in the launch request. This setting is file retention only;
   it does not prevent duplicate LinkedIn posts.

   **Combine files** is useful for a cumulative Phantom output, but it can
   return historical rows again and make a weekly import look duplicated.
   **Delete previous files** is not recommended because it removes prior
   result files and does not provide application-level duplicate protection.

5. Validate HTTP status and response JSON. Store the returned run/launch ID in
   a lightweight control sheet or Script Properties so a retry does not launch
   the same run unintentionally.
6. Poll the documented Phantom status endpoint with bounded retries across
   separate time-based executions.
7. When the run is complete, retrieve and validate the CSV download link.
8. Create the deterministic weekly worksheet before importing any CSV data. If
   the sheet already exists for the same completed container, reuse it.
9. Import the CSV into the worksheet. Prefer the Google Sheets `IMPORTDATA`
   formula only when the CSV URL is publicly readable and formula recalculation
   can be verified. Otherwise, fetch the CSV with `UrlFetchApp.fetch`, parse it
   with `Utilities.parseCsv`, and write the values with one batched
   `setValues` call.
10. Append `content_summary`, status, error, and timestamp headers after the
    final raw source column.
11. Mark the import complete only after the imported range has the expected
    headers and row count.
12. Deduplicate imported rows in Apps Script before writing or updating the
    weekly worksheet. Phantom's file setting controls result-file storage; it
    does not prove that two launches will never return the same LinkedIn post.

The script must distinguish launch failure, timeout, missing or expired CSV
link, CSV download failure, empty result, provider error rows, and successful
zero-post results. Re-running a completed launch must reuse the existing weekly
worksheet instead of creating a second duplicate tab.

Duplicate prevention must exist in both layers, with Apps Script as the
authoritative layer:

1. PhantomBuster: use **Create new files** so each launch has a separate input
   file and does not append prior result files by default.
2. Apps Script: calculate a stable post key, preferably the normalized
   `postUrl` or provider post ID. If no stable ID exists, use a documented
   fallback such as normalized profile URL + post date + normalized post
   content hash.
3. Apps Script: ignore duplicate keys within one CSV and upsert the same key
   when a recovery run imports the same post again.
4. Apps Script: use the reporting-period worksheet name plus the stable post
   key to make retries and overlap reconciliation idempotent.

`Combine files` does not make the data semantically unique; it only controls
whether Phantom appends output to an existing result file. `Delete previous
files` does not make data unique either and can destroy recovery history.

### Phase 3: Implement Gemini content summarization

Implement `SummarizationAutomation.gs` in this order:

1. Locate the target weekly worksheet, either from the current run control
   record or from an explicit menu action. The worksheet must already exist
   because the Phantom CSV import stage creates it first.
2. Validate that the sheet has source rows and a `content_summary` column.
3. Select only rows with non-empty post content and an empty
   `content_summary`. Do not summarize rows already completed unless an
   explicit force-resummarize action is added later.
4. Build bounded Gemini batches with a stable row/index identifier.
5. Call the Gemini REST API using `UrlFetchApp.fetch`.
6. Configure structured JSON output and set the model's thinking configuration
   to `LOW` using the exact request shape supported by the selected Gemini API
   version.
7. Require one summary object per submitted row. Each object should contain:

   ```json
   {
     "row_id": 12,
     "sentences": ["...", "..."]
   }
   ```

8. Validate that:
   - every submitted row has exactly one response;
   - `row_id` values are unique and match the batch;
   - `sentences` contains one to three complete sentence strings;
   - no sentence is silently truncated locally;
   - empty or fabricated summaries are rejected.
9. Join validated sentences with spaces and write results to the exact target
   rows using one batched range update.
10. Record per-row failure status and error text for invalid model output or
    transport errors. Retry transient API failures with a small bounded retry
    count; do not retry indefinitely.
11. Continue with the next batch when safe, while returning a final execution
    summary showing processed, skipped, and failed rows.

The prompt must treat LinkedIn content as untrusted data, ignore instructions
inside the post, use only explicit facts, preserve important names/numbers, and
prefer a complete one-sentence summary over cutting a longer response.

### Phase 4: Automate production execution and add temporary test controls

Automation is the production behavior; no human should be required to launch
scraping, import results, or start summarization.

Create the production triggers and handoff in this order:

1. `configureTriggers`: reads `SCHEDULE_TIMEZONE`, `SCHEDULE_DAY`, and
   `SCHEDULE_TIME`, then validates the `HH:mm` value and creates the managed
   weekly trigger. For a complete Sunday–Saturday report, configure it for a
   time after Saturday ends, such as Sunday 00:15 in the reporting timezone.
2. `schedulePhantomRun`: the managed weekly time-based trigger launches
   PhantomBuster for the most recent closed reporting period.
3. `pollPhantomRun`: detects that the Phantom run has completed, retrieves the
   CSV download link, and imports the result into the deterministic weekly
   worksheet.
4. `summarizeImportedWeek`: starts automatically after a successful import,
   either directly from the completion flow or through a short-interval
   time-based trigger that detects imported but unsummarized worksheets.
5. `retryIncompleteWork`: a bounded recovery trigger finds stored launch
   records, incomplete imports, and failed summary rows without launching a
   duplicate Phantom run.

`retryIncompleteWork` should also re-fetch the latest closed reporting period
when configured, using the same worksheet name and stable post key. This
overlap/reconciliation pass is the mechanism that repairs late provider data
without creating duplicate rows.

The production workflow must be idempotent and must not depend on the
spreadsheet menu, a user alert, or an open browser session.

During development and integration testing, add a temporary spreadsheet menu
with exactly two manual actions:

```text
LinkedIn Automation (Testing)
├── Phantom Data Scraping
└── Content Summarization
```

`Phantom Data Scraping` must execute the same launch/import path used by the
production trigger. `Content Summarization` must execute the same
summarization path used by the production handoff and process the latest
imported weekly worksheet. The manual actions must not contain separate
business logic or bypass validation, locking, idempotency, or error handling.

Guard the temporary menu with a Script Property:

```text
ENABLE_MANUAL_TEST_MENU=true
```

When the property is not exactly `true`, do not add the testing menu in
`onOpen`. Before production rollout, set it to `false` or remove the property
and reinstall/refresh the spreadsheet menu. The scheduled triggers must remain
available regardless of this flag.

All manual and scheduled entry points must acquire a script lock. A second
invocation while a run is active must fail clearly rather than launching
duplicate Phantom jobs, importing the same result twice, or overwriting a
weekly worksheet.

### Phase 5: Verify automation before disabling manual controls

Use the two temporary buttons to validate the workflow in a test workbook:

1. Click `Phantom Data Scraping` and confirm that the agent launches, the
   result is imported, and the weekly worksheet is created.
2. Click `Content Summarization` and confirm that unsummarized rows receive
   validated `content_summary` values.
3. Repeat both actions and confirm that no duplicate launch, worksheet, row,
   or summary is created.
4. Confirm the scheduled trigger can perform the same two stages without user
   interaction.
5. Test timeout, provider errors, empty results, invalid Gemini responses, and
   overlapping executions.
6. Inspect execution logs and stored control state for one complete weekly
   cycle.
7. Set `ENABLE_MANUAL_TEST_MENU=false`, refresh the spreadsheet, and verify
   that the testing menu is hidden while scheduled automation still works.

The manual controls are a testing aid only and must not become a second
production workflow.

### Phase 6: Defer weekly synthesis

Do not implement the former `weekly_summary` tab or multi-post company
synthesis in this release. Reserve the future column name
`weekly_summarize` and define its input as all summarized posts for one
customer within one weekly worksheet. Implement it only after the raw import
and per-post summary flow is stable.

## 5. Error handling and idempotency

The implementation must make failures visible and rerunnable:

| Failure | Required behavior |
|---|---|
| Missing Script Property | Stop before external calls and show the property name |
| Phantom launch non-2xx | Record response body without secrets; do not create a result sheet |
| Phantom timeout | Preserve launch ID and allow polling/import retry |
| Empty valid result | Create a weekly sheet with headers and zero data rows |
| Malformed result row | Preserve diagnostics and continue only when row alignment is safe |
| Gemini transient failure | Retry the batch a bounded number of times |
| Gemini invalid schema | Mark affected rows failed; never fabricate or truncate |
| Sheets quota/transient failure | Stop with a retryable error and preserve control state |
| Duplicate schedule/manual run | Reuse launch ID or existing weekly sheet |

Use deterministic keys such as `week_start + week_end + source post URL` when
available. If Phantom does not provide a stable post URL, document and test the
fallback key. The system must not claim that weekly coverage is complete until
the boundary and overlap strategy are confirmed.

## 6. Testing plan

### 6.1 Static and helper tests

Test helper functions independently with Apps Script-compatible JavaScript or
the repository's chosen local test runner:

- required Script Property validation;
- `customer_info` header and row validation;
- profile URL normalization and duplicate removal;
- Sunday–Saturday or Monday–Sunday boundary calculations;
- worksheet names such as `04 - 10 Oct 2025`;
- worksheet-name sanitization and collision handling;
- raw header plus appended pipeline header construction;
- row/index mapping for batched summary writes.

### 6.2 Mocked Phantom API tests

Mock `UrlFetchApp.fetch` and verify:

1. The launch request uses `POST`, JSON content type, the
   `x-phantombuster-key` header, and the configured agent ID.
2. The API key is never included in logs or user-facing errors.
3. Non-2xx responses stop processing with an explicit error.
4. When dynamic input mode is enabled, the request includes validated
   `bonusArgument.spreadsheetUrl`, the exact `columnName`, the selected
   activity/date settings, and no secrets.
5. The ID-only mode remains supported for agents that use their saved input
   configuration.
6. The returned container/launch ID is stored and reused during polling
   retries.
7. A completed response containing a CSV link is validated before import.
8. The weekly worksheet is created before the CSV import starts.
9. A CSV URL is either imported through verified `IMPORTDATA` behavior or
   fetched, parsed, and written by Apps Script.
10. Duplicate post keys within one CSV are removed before writing.
11. Running the same completed result twice reuses the same weekly sheet and
    does not create duplicate post rows.
12. Missing, expired, empty, and invalid CSV responses remain distinguishable.

### 6.3 Mocked Gemini tests

Mock Gemini responses and verify:

1. The request includes the structured response configuration.
2. The request includes `thinkingConfig` set to `LOW` according to the selected
   API contract.
3. One-to-three sentence arrays are accepted and joined without modification.
4. Four-sentence, empty, missing, duplicate-row, and out-of-range responses are
   rejected.
5. Invalid output is retried once or according to the configured bounded policy.
6. A permanently invalid batch writes visible failure status instead of
   silently dropping or truncating content.
7. Only unsummarized rows are sent by a normal run.
8. Summaries are written to the correct worksheet rows, even when batches are
   processed out of order.

### 6.4 Mocked Sheets tests

Verify:

- `customer_info` is never overwritten;
- weekly sheets are created with the expected name;
- raw columns are preserved in their original order;
- `content_summary` is the first appended summary column;
- duplicate post keys are removed within a CSV and across recovery imports;
- reruns do not duplicate rows or worksheets;
- partial failures preserve successful summaries and mark failed rows;
- a zero-post week still has a usable worksheet.

### 6.5 Manual integration test

Use a test spreadsheet, a test Phantom agent, and a small set of profiles:

1. Set all Script Properties with test credentials.
2. Set `ENABLE_MANUAL_TEST_MENU=true` and refresh the spreadsheet.
3. Run `Phantom Data Scraping` from the temporary testing menu.
4. Confirm the Phantom API request and returned launch ID.
5. Confirm completion polling retrieves the CSV link, creates one weekly
   worksheet, and imports the CSV.
6. Confirm the worksheet contains raw fields and appended
   `content_summary`.
7. Run `Content Summarization` from the temporary testing menu and verify
   Gemini is called with low thinking.
8. Verify each valid post receives a summary in the same row.
9. Add a post containing an instruction such as “ignore previous
   instructions”; confirm the output summarizes it as content rather than
   following it.
10. Force an invalid Gemini response and confirm visible row-level errors.
11. Re-run both testing actions; confirm no duplicate worksheet, rows, or
    summaries are created.
12. Test an empty Phantom result and a provider error response.
13. Test lock behavior by starting overlapping executions.
14. Set `ENABLE_MANUAL_TEST_MENU=false`, refresh the spreadsheet, and confirm
    the testing menu is hidden.

### 6.6 Acceptance criteria

The change is complete only when:

- no file under `cloud_function/` is modified;
- `apps_scripts/` contains the two separated Apps Script implementations;
- scheduled automation can launch Phantom through the documented API without
  human interaction;
- the temporary `Phantom Data Scraping` and `Content Summarization` actions can
  exercise the same production paths during testing;
- a completed result creates the correct weekly worksheet;
- raw data and `content_summary` coexist in that worksheet;
- Gemini requests use `ThinkingConfig` `LOW`;
- valid summaries are written without local hard truncation;
- failures remain visible and rerunnable;
- automated mocks and the manual end-to-end test pass;
- the final week-boundary decision is documented before production scheduling.

## 7. Deployment and rollout sequence

1. Create the `apps_scripts/` folder and import the two scripts into a test
   spreadsheet-bound Apps Script project.
2. Configure Script Properties with test values only.
3. Add helper and mocked API tests before enabling any trigger.
4. Enable `ENABLE_MANUAL_TEST_MENU=true` and validate the raw weekly worksheet
   with `Phantom Data Scraping`.
5. Validate row alignment and `LOW` thinking with `Content Summarization`.
6. Enable the summarization trigger only after the manual two-step test is
   reliable.
7. Enable the weekly Phantom trigger after duplicate protection is verified.
8. Monitor execution logs, quotas, failed rows, and worksheet creation for at
   least one complete reporting cycle.
9. Set `ENABLE_MANUAL_TEST_MENU=false` and confirm the testing menu is hidden.
10. Document the final week boundary, retry behavior, and recovery procedure.
11. Enable production credentials and triggers only after the test workbook
    passes all acceptance criteria.
