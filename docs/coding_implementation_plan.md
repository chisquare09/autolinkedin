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
3. Include the webhook payload and job metadata in the Pub/Sub message so the
   worker has everything needed for asynchronous processing and retry.
4. Parse both JSON arrays and JSON strings when PhantomBuster wraps results.
5. Resolve customer names through the manual mapping table in Google Sheets.
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
gemini-2.5-flash
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

The system must provide a manual reprocessing operation that republishes the
retained Pub/Sub payload, or accepts the same payload again, without scraping
LinkedIn again. No separate raw-payload archive is required.

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

Google Sheets is the only application data store and is the system of record for
the mapping, post-detail, and weekly-summary data. Because the expected volume
is small, do not add GCS, Firestore, Cloud SQL, or another persistence layer.
Pub/Sub is used only for asynchronous delivery, retry, and dead-letter
handling; its message retention must cover the operational recovery window.

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
4. Create or verify Secret Manager secrets.
5. Deploy Cloud Run in `australia-southeast1`.
6. Configure Pub/Sub push or authenticated worker delivery and message
   retention for the recovery window.
7. Configure environment variables and secret references.
8. Print the webhook endpoint and required PhantomBuster settings.

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

Mock Pub/Sub, Gemini, and Sheets to verify:

- webhook authentication;
- durable job publication;
- retry behavior;
- dead-letter behavior;
- payload and job metadata are present in the Pub/Sub message;
- idempotent upsert;
- failure status propagation.

### Manual end-to-end test

Run a small PhantomBuster job against test profiles and a test workbook.
Confirm:

- the webhook returns quickly;
- a Pub/Sub message is created;
- a failed delivery can be reprocessed from the retained Pub/Sub payload;
- post details are enriched;
- customer weekly summaries are written;
- a customer with no posts receives `post_count = 0`;
- rerunning the same job does not create duplicates;
- authentication rejects invalid requests.

The implementation is complete only when automated tests pass and the manual
smoke test succeeds.

## 16. Integration

Integration must be completed incrementally. GitHub is the source-code
repository; it is not part of the runtime data path. The initial deployment can
be performed from a local checkout with `gcloud run deploy --source .`.
Automated GitHub-to-Cloud-Run deployment is deferred with CI/CD.

### 16.1 Runtime data flow

The components connect as follows:

```text
Google Sheets: customer_info
        |
        | Public view URL
        v
PhantomBuster
        | HTTPS POST /webhook
        v
Cloud Run webhook
        | Publish payload and job metadata
        v
Pub/Sub topic and subscription
        | Authenticated push
        v
Cloud Run worker: /pubsub
        | Read mappings and write results
        +--> Google Sheets: post_details, weekly_summary
        |
        +--> Gemini API: generate validated summaries
```

Google Sheets is the only application data store. Pub/Sub is used only for
asynchronous delivery, retry, and dead-letter handling. Gemini only generates
summaries; it does not receive webhooks or store application data.

### 16.2 Integration prerequisites

Before deployment:

1. Remove all remaining GCS dependencies from the application, deployment
   scripts, dependencies, and configuration. The worker must not archive raw
   payloads in GCS.
2. Create or select a Google Cloud project with billing enabled.
3. Use `australia-southeast1` as the default Cloud Run region.
4. Create one runtime service account for Cloud Run.
5. Create one Google Sheets workbook with a `customer_info` tab containing:

   ```text
   customer_name
   linkedin_profile_url
   ```

6. Share the workbook with the runtime service account as an editor.
7. Keep the `customer_info` tab publicly viewable for PhantomBuster, and do not
   put credentials, secrets, or internal notes in that tab.

### 16.3 Google Cloud services and permissions

Enable the required APIs:

- Cloud Run;
- Cloud Build;
- Pub/Sub;
- Secret Manager;
- Google Sheets;
- Google Drive;
- Cloud Logging and Monitoring.

Create:

- one Cloud Run service;
- one Pub/Sub processing topic and subscription;
- one Pub/Sub dead-letter topic and subscription;
- Secret Manager secrets for the Gemini API key and webhook credential.

Grant the runtime service account only the permissions required to publish and
consume the configured Pub/Sub resources and access the configured secrets.
Use Application Default Credentials in Cloud Run; do not use downloaded service
account key files.

### 16.4 Secrets and runtime configuration

Store the following as Secret Manager secrets:

```text
GEMINI_API_KEY
WEBHOOK_BEARER_TOKEN
```

Configure the following as Cloud Run environment variables or equivalent
non-secret settings:

```text
OUTPUT_SPREADSHEET_ID
PUBSUB_TOPIC
PUBSUB_SUBSCRIPTION
GEMINI_MODEL_NAME=gemini-2.5-flash
REPORTING_TIMEZONE=Australia/Brisbane
WEBHOOK_AUTH_MODE=bearer
```

The Gemini request path is:

```text
Cloud Run worker -> Gemini API -> validated summary response
```

The API key and bearer token must never be committed, printed, or written to
application logs.

### 16.5 Deployment sequence

Complete and verify each step before continuing:

1. Run the local unit and fixture tests.
2. Run the local service and verify `GET /health`.
3. Deploy the Cloud Run service from the repository checkout.
4. Verify the deployed `/health` endpoint.
5. Create the Pub/Sub topic, worker subscription, dead-letter resources, and
   authenticated push delivery to the deployed `/pubsub` endpoint.
6. Store secrets and attach them to the Cloud Run service.
7. Confirm the service can read and update the workbook.
8. Send an invalid webhook request and verify `401 Unauthorized`.
9. Send a valid representative PhantomBuster payload to `/webhook` and verify
   that it returns quickly and publishes a Pub/Sub message.
10. Verify the worker receives the message, calls Gemini, and upserts
    `post_details` and `weekly_summary`.
11. Repeat the same payload and verify that deterministic upsert keys prevent
    duplicate rows.
12. Test a zero-post customer, malformed records, and a failed delivery.
13. Confirm Pub/Sub retry and dead-letter behavior.

### 16.6 PhantomBuster configuration

Configure PhantomBuster only after the Cloud Run webhook and Pub/Sub worker have
passed the representative payload test:

1. Set the input URL to the public `customer_info` sheet.
2. Configure the weekly LinkedIn scraping workflow and exact Monday-Sunday
   date range where supported.
3. Configure JSON export.
4. Configure the completion webhook:

   ```text
   https://<cloud-run-hostname>/webhook
   ```

5. Configure the bearer token using PhantomBuster's supported custom header
   mechanism. Use the documented query-secret fallback only if custom headers
   are unavailable.
6. Run a small test job against test profiles before enabling the weekly
   schedule.

The expected production flow is:

```text
PhantomBuster -> POST /webhook -> Pub/Sub -> POST /pubsub
-> Gemini -> Google Sheets
```
