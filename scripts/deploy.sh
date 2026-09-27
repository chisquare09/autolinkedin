#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID}"
: "${REGION:=australia-southeast1}"
: "${SERVICE_NAME:=linkedin-automation}"
: "${SERVICE_ACCOUNT:=linkedin-automation-runtime}"
: "${PUBSUB_TOPIC:?Set PUBSUB_TOPIC}"
: "${PUBSUB_SUBSCRIPTION:?Set PUBSUB_SUBSCRIPTION}"
: "${OUTPUT_SPREADSHEET_ID:?Set OUTPUT_SPREADSHEET_ID}"
: "${GEMINI_API_KEY_SECRET:=GEMINI_API_KEY}"
: "${WEBHOOK_BEARER_TOKEN_SECRET:=WEBHOOK_BEARER_TOKEN}"

if [[ "$SERVICE_ACCOUNT" != *@*.iam.gserviceaccount.com ]]; then
  SERVICE_ACCOUNT="${SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com"
fi

gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --service-account "$SERVICE_ACCOUNT" \
  --set-env-vars "PUBSUB_TOPIC=$PUBSUB_TOPIC,OUTPUT_SPREADSHEET_ID=$OUTPUT_SPREADSHEET_ID,REPORTING_TIMEZONE=Australia/Brisbane,GEMINI_MODEL_NAME=gemini-2.5-flash,WEBHOOK_AUTH_MODE=bearer" \
  --set-secrets "GEMINI_API_KEY=$GEMINI_API_KEY_SECRET:latest,WEBHOOK_BEARER_TOKEN=$WEBHOOK_BEARER_TOKEN_SECRET:latest" \
  --cpu-throttling \
  --memory 1Gi \
  --cpu 1 \
  --timeout 300 \
  --allow-unauthenticated

SERVICE_URL="$(gcloud run services describe "$SERVICE_NAME" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --format='value(status.url)')"

gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:$SERVICE_ACCOUNT" \
  --role roles/run.invoker

gcloud pubsub subscriptions update "$PUBSUB_SUBSCRIPTION" \
  --push-endpoint="${SERVICE_URL}/pubsub" \
  --push-auth-service-account="$SERVICE_ACCOUNT" \
  --push-auth-token-audience="$SERVICE_URL"

printf 'Webhook endpoint: %s/webhook\nPub/Sub worker endpoint: %s/pubsub\n' \
  "$SERVICE_URL" "$SERVICE_URL"
