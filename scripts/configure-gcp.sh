#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID}"
: "${REGION:=australia-southeast1}"
: "${SERVICE_ACCOUNT:?Set SERVICE_ACCOUNT}"
: "${PUBSUB_TOPIC:=linkedin-automation-jobs}"
: "${PUBSUB_SUBSCRIPTION:=linkedin-automation-worker}"
: "${DLQ_TOPIC:=linkedin-automation-dead-letter}"
: "${BUCKET_NAME:?Set BUCKET_NAME}"

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com pubsub.googleapis.com storage.googleapis.com secretmanager.googleapis.com sheets.googleapis.com drive.googleapis.com
gcloud pubsub topics create "$PUBSUB_TOPIC" 2>/dev/null || true
gcloud pubsub topics create "$DLQ_TOPIC" 2>/dev/null || true
gcloud pubsub subscriptions create "$PUBSUB_SUBSCRIPTION" \
  --topic="$PUBSUB_TOPIC" \
  --dead-letter-topic="$DLQ_TOPIC" \
  --max-delivery-attempts=3 2>/dev/null || true
gcloud pubsub subscriptions update "$PUBSUB_SUBSCRIPTION" \
  --dead-letter-topic="$DLQ_TOPIC" \
  --max-delivery-attempts=3
gcloud storage buckets create "gs://$BUCKET_NAME" --location="$REGION" --uniform-bucket-level-access 2>/dev/null || true
cat > /tmp/gcs-lifecycle.json <<'JSON'
{"rule":[{"action":{"type":"Delete"},"condition":{"age":30}}]}
JSON
gcloud storage buckets update "gs://$BUCKET_NAME" --lifecycle-file=/tmp/gcs-lifecycle.json
rm -f /tmp/gcs-lifecycle.json
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SERVICE_ACCOUNT" --role="roles/storage.objectCreator"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SERVICE_ACCOUNT" --role="roles/pubsub.subscriber"
