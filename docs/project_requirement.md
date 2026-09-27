# LinkedIn Activity Tracker and AI Summarization

## 1. Objective

Automate the weekly review of LinkedIn activity for customer profiles:

1. PhantomBuster retrieves posts for each mapped LinkedIn profile.
2. Google Cloud receives and queues the scraping result for asynchronous processing.
3. Cloud Run validates, normalizes, deduplicates, and summarizes the posts with Gemini.
4. The application writes all retained mapping, enriched post, and customer-level
   weekly summary data to one Google Sheets workbook.

The reporting period is a deterministic calendar week:

```text
Monday 00:00:00 through Sunday 23:59:59
Timezone: Australia/Brisbane (fixed AEST, UTC+10)
```

The system must use the reporting period stored on the job rather than calculating
“the previous seven days” during processing or retry.

## 2. Confirmed decisions

| Area | Decision |
|---|---|
| Asynchronous processing | Google Cloud Pub/Sub |
| Reporting timezone | `Australia/Brisbane` |
| Reporting period | Monday through Sunday |
| Customer identity | Customer name, as supplied by the mapping sheet |
| Profile mapping | Explicit manual mapping |
| Profiles per customer | Multiple profiles are supported |
| Mapping columns | `customer_name`, `linkedin_profile_url` |
| Exact duplicate mappings | Automatically deduplicate |
| Input sheet access | Public view link for PhantomBuster |
| PhantomBuster retrieval | Exact weekly date range where supported |
| Output workbook | Same workbook as the mapping sheet |
| Output tabs | `customer_info`, `post_details`, `weekly_summary` |
| Output history | Retain historical weeks |
| Reruns | Upsert existing results, never blindly append duplicates |
| Application data storage | Google Sheets only; no GCS or other database |
| Retry policy | Three attempts with exponential backoff |
| Failed jobs | Dead-letter handling and manual reprocessing by republishing the Pub/Sub payload |
| AI language | English |
| AI tone | Executive-neutral |
| Per-post summary | Maximum three sentences |
| Customer weekly summary | Maximum 100 words |
| Gemini model | Configurable; initial value `gemini-2.5-flash` |
| GCP region | `australia-southeast1` |
| Deployment | Versioned `gcloud` scripts |
| CI/CD | Deferred |
| Completion validation | Unit, fixture, mocked integration, and manual tests |

## 3. Google Sheets workbook

The operator maintains one workbook with these three tabs.

### 3.1 `customer_info`

Required columns:

```text
customer_name
linkedin_profile_url
```

Each row maps one LinkedIn profile to one customer. A customer with multiple
profiles appears in multiple rows. The same customer name with different profile
URLs is valid.

Exact duplicate pairs are deduplicated before a scraping job is created. Profile
URLs must be normalized for matching, including protocol, trailing slash, query
parameters, and known LinkedIn URL formatting differences.

The workbook is publicly viewable because PhantomBuster currently uses a public
sheet link. It must contain only the two required mapping fields and no internal
notes, credentials, or sensitive data.

Customer names are the chosen business identifier. The implementation should
document that renaming a customer creates a new logical identity unless a future
stable customer ID column is introduced.

### 3.2 Post Details

This tab preserves the PhantomBuster export fields and adds pipeline fields.
The source export currently contains fields such as:

```text
profileUrl
postUrl
error
timestamp
imgUrl
type
postContent
likeCount
commentCount
repostCount
postDate
action
authorUrl
viewCount
postTimestamp
videoUrl
sharedPostUrl
sharedJobUrl
```

The implementation must tolerate missing or additional source columns.

Added fields:

```text
customer_name
week_start
week_end
content_summary
processing_status
processing_error
processed_at
```

There is one row per qualifying post. `content_summary` is the English,
executive-neutral summary of that post and is limited to three sentences.
`processing_status` is normally `processed`; failed or malformed records must
be visible rather than silently omitted.

The post-detail identity for idempotent upsert is based on:

```text
customer_name + normalized_profile_url + post_url
```

If PhantomBuster does not provide a stable post URL, the implementation must use
the best available stable post identifier and document the fallback. A post may
be associated with more than one weekly run, but the reporting week fields must
always reflect the job that produced the row.

### 3.3 Customer Weekly Summary

There is one row per customer and reporting week, including customers whose
qualifying post count is zero.

Required fields:

```text
customer_name
week_start
week_end
post_count
weekly_synthesis
processed_at
processing_status
processing_error
```

`weekly_synthesis` is generated from all qualifying posts from all mapped profiles
belonging to that customer. It is in English, executive-neutral, and limited to
100 words.

The customer-week upsert key is:

```text
customer_name + week_start
```

For a customer with no qualifying posts, write `post_count = 0` and a clear
no-activity summary. Do not confuse zero activity with a scraping or processing
failure.

## 4. End-to-end architecture

```text
`customer_info` tab
        |
        v
PhantomBuster weekly date-range run
        |
        v
Authenticated Cloud Run webhook receiver
        |
        +-- validate request and payload envelope
        +-- determine the reporting week
        +-- publish the payload and job metadata as a Pub/Sub job
        +-- return a fast 2xx response
                         |
                         v
                 Cloud Run worker
        1. Validate the complete payload schema
        2. Load and validate the mapping rows from Google Sheets
        3. Normalize profile URLs and deduplicate mappings
        4. Normalize PhantomBuster post fields
        5. Apply the fixed Australia/Brisbane week window
        6. Deduplicate posts
        7. Generate post-level summaries with Gemini
        8. Generate customer-level weekly summaries with Gemini
        9. Upsert both output tabs in Google Sheets
       10. Record metrics and final processing status in logs and Sheets
```

The webhook must not perform the full scrape processing synchronously and must
not rely on FastAPI `BackgroundTasks`. Cloud Run instances can restart or scale
down after the HTTP response, so Pub/Sub is the durable handoff.

The receiver and worker may initially be deployed as one Cloud Run service with
separate endpoints or handlers. The code should keep transport, processing,
storage, AI, and Sheets responsibilities separated so the worker can later be
deployed independently.

## 5. PhantomBuster integration

Configure the PhantomBuster workflow to:

1. Read the public URL of the workbook’s `customer_info` tab.
2. Run once per week after the reporting period closes.
3. Retrieve posts using the exact Monday–Sunday date range where the selected
   Phantom supports date filtering.
4. Export JSON to the webhook.
5. Trigger the webhook after the run completes.

The implementation must verify the actual PhantomBuster webhook schema. It must
not assume that fields such as `resultObject`, `profileUrl`, `postContent`, or
`timestamp` are always present. The sample `result.xls` contains an `error`
field and an “Export limit reached” message; these conditions must be detected
and reported.

If the selected Phantom cannot retrieve an exact date range, the integration
must retrieve enough pages to reach the week-start cutoff and then apply the
local reporting-window filter. A fixed maximum such as 15 posts must not be
described as a guarantee of complete weekly coverage.

There is no application-level customer or post cap. Provider quotas, request
size limits, pagination limits, Gemini limits, Sheets quotas, and cost controls
must still be handled explicitly and monitored.

## 6. Webhook authentication

The Cloud Run webhook is publicly reachable but must reject unauthenticated
requests.

Preferred configuration:

```http
Authorization: Bearer <token>
```

The bearer token is a long random value stored in Secret Manager and injected
into Cloud Run. It must not be committed to source code or logged.

If PhantomBuster supports custom webhook headers, configure the bearer header.
If it does not, use a secret query parameter as a fallback with:

- URL redaction in application and proxy logs;
- rate limiting;
- secret rotation;
- constant-time comparison;
- rejection of missing or invalid credentials.

The implementation should confirm which option is supported by the selected
PhantomBuster configuration before deployment.

## 7. Cloud resources and permissions

Deploy the following resources in `australia-southeast1`:

- Cloud Run service for the webhook and worker;
- Pub/Sub topic and subscription;
- Pub/Sub dead-letter topic/subscription;
- Secret Manager secrets;
- one runtime service account;
- one Google Sheets workbook.

Enable the required APIs:

- Cloud Run;
- Cloud Build;
- Pub/Sub;
- Secret Manager;
- Google Sheets;
- Google Drive;
- Cloud Logging and Monitoring.

Use a runtime service account with least-privilege access:

- access only the required Secret Manager secrets;
- publish/consume the required Pub/Sub resources;
- update the configured Google Sheets workbook.

Share the workbook with the runtime service account as an editor. Do not use
downloaded service-account JSON keys.

## 8. Secret and configuration values

Configuration must be separated from source code. Expected values include:

```text
OUTPUT_SPREADSHEET_ID
PUBSUB_TOPIC
PUBSUB_SUBSCRIPTION
GEMINI_MODEL_NAME=gemini-2.5-flash
WEBHOOK_AUTH_MODE
WEBHOOK_BEARER_TOKEN or WEBHOOK_SECRET
REPORTING_TIMEZONE=Australia/Brisbane
```

Store credentials and authentication secrets in Secret Manager. Non-secret
configuration may be supplied as Cloud Run environment variables.

Google Sheets is the only application data store. The Pub/Sub message may carry
the webhook payload and job metadata required for processing, but no raw payload
is archived in GCS or another storage service. Pub/Sub retention and
dead-letter handling must be configured according to the recovery window needed
by the deployment.
