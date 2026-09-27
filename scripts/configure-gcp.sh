#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID}"
: "${REGION:=australia-southeast1}"
: "${SERVICE_ACCOUNT:=linkedin-automation-runtime}"
: "${PUBSUB_TOPIC:=linkedin-automation-jobs}"
: "${PUBSUB_SUBSCRIPTION:=linkedin-automation-worker}"
: "${DLQ_TOPIC:=linkedin-automation-dead-letter}"
: "${DLQ_SUBSCRIPTION:=${PUBSUB_SUBSCRIPTION}-dead-letter}"
: "${MAX_DELIVERY_ATTEMPTS:=3}"
: "${MESSAGE_RETENTION_DURATION:=604800s}"

gcloud config set project "$PROJECT_ID"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com pubsub.googleapis.com secretmanager.googleapis.com sheets.googleapis.com drive.googleapis.com logging.googleapis.com monitoring.googleapis.com
gcloud iam service-accounts create "$SERVICE_ACCOUNT" --project="$PROJECT_ID" 2>/dev/null || true
gcloud pubsub topics create "$PUBSUB_TOPIC" 2>/dev/null || true
gcloud pubsub topics create "$DLQ_TOPIC" 2>/dev/null || true
gcloud pubsub subscriptions create "$PUBSUB_SUBSCRIPTION" \
  --topic="$PUBSUB_TOPIC" \
  --dead-letter-topic="$DLQ_TOPIC" \
  --max-delivery-attempts="$MAX_DELIVERY_ATTEMPTS" \
  --message-retention-duration="$MESSAGE_RETENTION_DURATION" 2>/dev/null || \
gcloud pubsub subscriptions update "$PUBSUB_SUBSCRIPTION" \
  --dead-letter-topic="$DLQ_TOPIC" \
  --max-delivery-attempts="$MAX_DELIVERY_ATTEMPTS" \
  --message-retention-duration="$MESSAGE_RETENTION_DURATION"
gcloud pubsub subscriptions create "$DLQ_SUBSCRIPTION" \
  --topic="$DLQ_TOPIC" \
  --message-retention-duration="$MESSAGE_RETENTION_DURATION" 2>/dev/null || true
gcloud secrets create GEMINI_API_KEY 2>/dev/null || true
gcloud secrets create WEBHOOK_BEARER_TOKEN 2>/dev/null || true
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" --role="roles/pubsub.subscriber"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com" --role="roles/pubsub.publisher"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com" --role="roles/pubsub.subscriber"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" --role="roles/secretmanager.secretAccessor"
