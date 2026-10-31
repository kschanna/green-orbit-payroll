# GCP deployment

Green Orbit deploys two Cloud Run services from one image:

- `green-orbit-payroll`: public web application, connected to Cloud SQL.
- `green-orbit-document-listener`: private, single-instance Pub/Sub listener with always-allocated CPU.

Database migrations run as the `green-orbit-payroll-migrate` Cloud Run job before either service is updated.

## Required resources

- Artifact Registry repository `green-orbit-payroll` in `australia-southeast2`.
- Cloud SQL PostgreSQL instance `green-orbit-postgres` and database `green_orbit_payroll`.
- Database user `green_orbit_app`.
- GCS bucket `green-orbit-payroll-demo-dev-worker-documents`.
- Pub/Sub subscription `green-orbit-dev-document-processing-local` receiving GCS object events.
- Document AI processor in `australia-southeast1`.
- Runtime service account `green-orbit-app@green-orbit-payroll-demo.iam.gserviceaccount.com`.
- GitHub Actions Workload Identity Federation and deployer service account already referenced by `.github/workflows/ci.yml`.

## Secrets

The runtime reads these Secret Manager secrets:

| Secret | Environment variable |
|---|---|
| `green-orbit-db-password` | `DB_PASSWORD` |
| `green-orbit-session-secret` | `SESSION_SECRET` |
| `green-orbit-tfn-key` | `GREEN_ORBIT_TFN_KEY` |
| `green-orbit-gemini-api-key` | `GEMINI_API_KEY` |

Never place secret values in GitHub variables, workflow YAML, container images, or committed `.env` files.

## Optional Vertex AI payroll planning

The payroll agent uses an approved deterministic plan by default. To enable its
bounded Vertex AI planning rationale, grant the Cloud Run runtime service
account permission to invoke the selected Vertex model and configure:

- `VERTEX_AI_PLANNING_ENABLED=true`
- `VERTEX_AI_PLANNING_MODEL` with an available Vertex model ID
- `GOOGLE_CLOUD_LOCATION` for the selected model region

No additional API key is required in Cloud Run. The application uses the
attached runtime service account through Application Default Credentials. The
model receives assignment and period identifiers only; it cannot change the
approved workflow steps or execute financial actions.

After authenticating the Google Cloud CLI, synchronise the local application secrets without printing them:

```bash
gcloud auth login
PROJECT_ID=green-orbit-payroll-demo ./scripts/prepare_gcp.sh
```

The database password secret is intentionally not sourced from `.env`; create or rotate it independently.

## GitHub configuration

Set the GitHub Actions repository variable `DOCUMENT_AI_PROCESSOR_ID`. Confirm the Workload Identity provider and deployer service account in the workflow match the target project.

Push to `main` to run tests, build and push the image, apply migrations, deploy the web and listener services, and verify web health and the Gemini secret binding.

## Production verification

1. Open `/health` and confirm HTTP 200.
2. Sign in as an administrator and worker.
3. Send one message through each AI assistant.
4. Upload a non-sensitive test PDF and confirm it reaches `ready_for_review`.
5. Generate a test payroll, payslip and invoice.
6. Confirm Cloud Run logs contain no secret values or personal payroll data.
7. Configure budgets, error alerts, database backups, point-in-time recovery, and a custom domain before onboarding real workers.
