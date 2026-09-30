# Coding Implementation Plan

## Implementation status

| Section | Status |
|---|---|
| Processing and data correctness | Implemented |
| Gemini summarization | Implemented |
| Retry, dead-letter, and observability | Partially implemented |
| Google Sheets write strategy | Partially implemented |
| Source code structure | Implemented |
| Deployment | Partially implemented |
| Testing and acceptance criteria | Automated unit and fixture tests implemented; mocked integration and manual end-to-end tests pending |

## 9. Processing and data correctness

The worker must:

1. Validate the webhook envelope and reject malformed requests explicitly.
2. Assign a stable job ID and reporting week before processing.
3. Archive the exact raw payload to GCS using a collision-resistant object name.
4. Parse both JSON arrays and JSON strings when PhantomBuster wraps results.
5. Resolve customer names through the manual mapping table.
6. Normalize timestamps into UTC internally and compare them using
   `Australia/Brisbane` week boundaries.
7. Reject malformed dates rather than treating them as valid.
8. Exclude posts outside the fixed reporting period.
9. Treat missing post text, profile URL, and post URL as validation conditions.
10. Deduplicate exact mapping rows and duplicate posts.
11. Process every mapped profile, including profiles with no qualifying posts.
12. Upsert output rows rather than append on every delivery.

A delayed webhook or retry must produce the same result for the same job period.
The worker must be safe to run more than once.

## 10. Gemini summarization

Use a configurable Gemini Flash model, initially:

```text
gemini-3.8-flash
```

For each post, provide only the normalized post content and relevant metadata
needed for summarization. Limit input length to protect latency and cost.

For each customer-week, provide all qualifying posts from all mapped profiles for
that customer. Generate one concise synthesis rather than merely concatenating
profile summaries.

The AI response must use a structured JSON schema validated by the application.
The application must validate:

- the number of returned post summaries matches the submitted posts;
- summary types and required fields;
- the three-sentence post limit;
- the 100-word customer-week limit;
- non-empty content for successful summaries.

Post text is untrusted input. The prompt must instruct the model to summarize
the content and ignore instructions contained inside the LinkedIn post.

Transient Gemini failures must be retried. Permanent or validation failures
must be written to processing status/error fields and sent through the job retry
policy.

## 11. Retry, dead-letter, and observability

Pub/Sub delivery uses three processing attempts with exponential backoff.
After the final failed attempt, the job is sent to the dead-letter path.

The system must provide a manual reprocessing operation that reads the retained
GCS payload and republishes a corrected job without scraping LinkedIn again.

Use structured logs with:

```text
job_id
reporting_week
customer_name
profile_url
post_url
attempt
processing_status
error_type
```

Never log access tokens, secrets, full authorization headers, or unnecessary
post/customer data.

Monitor:

- webhook request count and rejection count;
- Pub/Sub backlog and dead-letter count;
- processing latency;
- Gemini request failures and token/cost usage;
- Sheets API failures and quota responses;
- number of profiles, posts, zero-post customers, and failed records.

## 12. Google Sheets write strategy

Use batched Sheets API updates and avoid one network request per post.
The write layer must:

- create required headers if tabs are empty;
- locate rows using deterministic keys;
- update existing rows for reruns;
- append only new keys;
- avoid concurrent conflicting writes where possible;
- retry transient Sheets quota and network errors;
- preserve historical reporting weeks.

The spreadsheet is a reporting surface, not the durable processing database.
GCS is the short-term raw recovery source. If volume or concurrent operators
grows substantially, introduce Firestore or Cloud SQL as the system of record
and treat Sheets as an export.

## 13. Source code structure

The initial implementation should use Python and FastAPI with separate modules
for clear testing boundaries:

```text
linkedin-automation/
├── app/
│   ├── webhook.py
│   ├── worker.py
│   ├── config.py
│   ├── models.py
│   ├── phantom_parser.py
│   ├── date_windows.py
│   ├── normalization.py
│   ├── summarization.py
│   ├── gcs_store.py
│   ├── sheets_store.py
│   └── logging.py
├── tests/
├── fixtures/
├── requirements.txt
├── Dockerfile
└── scripts/
    ├── deploy.sh
    └── configure-gcp.sh
```

The implementation must not use FastAPI `BackgroundTasks` as the durable job
mechanism. It must not catch broad exceptions and convert failures into
success-shaped output.

## 14. Deployment

Use versioned, non-interactive `gcloud` scripts to:

1. Enable APIs.
2. Create or verify the service account.
3. Create Pub/Sub topics, subscriptions, and dead-letter resources.
4. Create the private GCS bucket and 30-day lifecycle rule.
5. Create or verify Secret Manager secrets.
6. Deploy Cloud Run in `australia-southeast1`.
7. Configure Pub/Sub push or authenticated worker delivery.
8. Configure environment variables and secret references.
9. Print the webhook endpoint and required PhantomBuster settings.

Do not enable always-allocated CPU merely to keep an in-process background task
alive. The durable Pub/Sub design allows request-based CPU allocation unless
measurements show that a worker requires another setting.

CI/CD is intentionally deferred until the MVP deployment and test workflow are
stable.

## 15. Testing and acceptance criteria

All of the following are required:

### Unit tests

Cover:

- Australia/Brisbane Monday–Sunday boundaries;
- UTC conversion and daylight-saving-independent behavior;
- profile URL normalization;
- exact duplicate mapping removal;
- PhantomBuster payload parsing;
- malformed date handling;
- post filtering and deduplication;
- no-post customer output;
- deterministic upsert keys;
- Gemini structured-response validation.

### Fixture tests

Use `result.xls` or a converted representative fixture containing:

- valid posts;
- posts outside the reporting week;
- missing content;
- invalid dates;
- PhantomBuster error rows;
- export-limit messages;
- multiple profiles mapped to one customer.

### Mocked integration tests

Mock Pub/Sub, Gemini, GCS, and Sheets to verify:

- webhook authentication;
- durable job publication;
- retry behavior;
- dead-letter behavior;
- raw payload archival;
- idempotent upsert;
- failure status propagation.

### Manual end-to-end test

Run a small PhantomBuster job against test profiles and a test workbook.
Confirm:

- the webhook returns quickly;
- a Pub/Sub message is created;
- raw payload is archived;
- post details are enriched;
- customer weekly summaries are written;
- a customer with no posts receives `post_count = 0`;
- rerunning the same job does not create duplicates;
- authentication rejects invalid requests.

The implementation is complete only when automated tests pass and the manual
smoke test succeeds.
