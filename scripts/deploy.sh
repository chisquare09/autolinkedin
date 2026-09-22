#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID}"
: "${REGION:=australia-southeast1}"
: "${SERVICE_NAME:=linkedin-automation}"
: "${SERVICE_ACCOUNT:?Set SERVICE_ACCOUNT}"
: "${PUBSUB_TOPIC:?Set PUBSUB_TOPIC}"
: "${GCS_BUCKET_NAME:?Set GCS_BUCKET_NAME}"
: "${OUTPUT_SPREADSHEET_ID:?Set OUTPUT_SPREADSHEET_ID}"

gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --service-account "$SERVICE_ACCOUNT" \
  --set-env-vars "PUBSUB_TOPIC=$PUBSUB_TOPIC,GCS_BUCKET_NAME=$GCS_BUCKET_NAME,OUTPUT_SPREADSHEET_ID=$OUTPUT_SPREADSHEET_ID,REPORTING_TIMEZONE=Australia/Brisbane,GEMINI_MODEL_NAME=gemini-2.5-flash" \
  --cpu-throttling \
  --memory 1Gi \
  --cpu 1 \
  --timeout 300 \
  --allow-unauthenticated
