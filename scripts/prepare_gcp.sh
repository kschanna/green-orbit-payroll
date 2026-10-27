#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-green-orbit-payroll-demo}"
REGION="${REGION:-australia-southeast2}"
REPOSITORY="${REPOSITORY:-green-orbit-payroll}"
RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT:-green-orbit-app@${PROJECT_ID}.iam.gserviceaccount.com}"
ENV_FILE="${ENV_FILE:-.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE" >&2
  exit 1
fi

if [[ -z "$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null)" ]]; then
  echo "No active gcloud account. Run: gcloud auth login" >&2
  exit 1
fi

gcloud config set project "$PROJECT_ID" >/dev/null
gcloud services enable \
  artifactregistry.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com \
  sqladmin.googleapis.com \
  storage.googleapis.com \
  pubsub.googleapis.com \
  documentai.googleapis.com

if ! gcloud artifacts repositories describe "$REPOSITORY" --location "$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$REPOSITORY" \
    --location "$REGION" --repository-format docker
fi

if ! gcloud iam service-accounts describe "$RUNTIME_SERVICE_ACCOUNT" >/dev/null 2>&1; then
  gcloud iam service-accounts create green-orbit-app \
    --display-name="Green Orbit runtime"
fi

for role in roles/cloudsql.client roles/storage.objectAdmin roles/pubsub.subscriber roles/documentai.apiUser; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
    --role="$role" --condition=None >/dev/null
done

read_env() {
  awk -F= -v key="$1" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$ENV_FILE"
}

sync_secret() {
  local env_name="$1" secret_name="$2" value
  value="$(read_env "$env_name")"
  if [[ -z "$value" || "$value" == replace-* ]]; then
    echo "Missing production value for $env_name in $ENV_FILE" >&2
    exit 1
  fi
  if ! gcloud secrets describe "$secret_name" >/dev/null 2>&1; then
    gcloud secrets create "$secret_name" --replication-policy=automatic
  fi
  printf '%s' "$value" | gcloud secrets versions add "$secret_name" --data-file=- >/dev/null
  gcloud secrets add-iam-policy-binding "$secret_name" \
    --member="serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
    --role=roles/secretmanager.secretAccessor >/dev/null
  echo "Updated Secret Manager secret: $secret_name"
}

sync_secret GEMINI_API_KEY green-orbit-gemini-api-key
sync_secret SESSION_SECRET green-orbit-session-secret
sync_secret GREEN_ORBIT_TFN_KEY green-orbit-tfn-key

echo "GCP base resources and application secrets are ready."
echo "Verify green-orbit-db-password and the Cloud SQL, bucket, Pub/Sub, and Document AI resource names before deploying."
