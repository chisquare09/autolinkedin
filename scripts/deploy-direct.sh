#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID}"
: "${OUTPUT_SPREADSHEET_ID:?Set OUTPUT_SPREADSHEET_ID}"
: "${WEBHOOK_BEARER_TOKEN_SECRET:=WEBHOOK_BEARER_TOKEN}"
: "${GEMINI_API_KEY_SECRET:=GEMINI_API_KEY}"
: "${REGION:=australia-southeast1}"
: "${SERVICE_NAME:=linkedin-automation-direct}"

gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --set-env-vars "OUTPUT_SPREADSHEET_ID=$OUTPUT_SPREADSHEET_ID,PROCESSING_MODE=direct,REPORTING_TIMEZONE=Australia/Brisbane,GEMINI_MODEL_NAME=gemini-2.5-flash,WEBHOOK_AUTH_MODE=bearer" \
  --set-secrets "GEMINI_API_KEY=$GEMINI_API_KEY_SECRET:latest,WEBHOOK_BEARER_TOKEN=$WEBHOOK_BEARER_TOKEN_SECRET:latest" \
  --memory 1Gi \
  --cpu 1 \
  --timeout 300 \
  --allow-unauthenticated

gcloud run services describe "$SERVICE_NAME" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --format='value(status.url)'
