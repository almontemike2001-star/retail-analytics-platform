# Google Cloud / BigQuery setup (macOS)

BeanFlow never uses service-account key files. Every developer authenticates with **their own** Google
account through Application Default Credentials (ADC). The credentials file lives in your home directory
(`~/.config/gcloud/`), outside the repository, and `.gitignore` blocks common credential file names.

## 1. Project and billing

1. Create (or pick) a GCP project, e.g. `beanflow-dev-<yourname>`.
2. Attach a billing account and create a **budget alert** (e.g. USD 5/month).
   Do not rely on the BigQuery sandbox: it expires tables after 60 days and would silently delete Bronze history.
3. Enable the BigQuery API: `gcloud services enable bigquery.googleapis.com`

## 2. Install and log in

```bash
brew install --cask google-cloud-sdk          # provides gcloud
gcloud auth login                             # your user account (browser)
gcloud config set project <PROJECT_ID>
gcloud auth application-default login         # ADC used by the Python client (browser)
gcloud auth application-default set-quota-project <PROJECT_ID>
```

## 3. Permissions

Your account needs on the project:

- **BigQuery Job User** (`roles/bigquery.jobUser`): run load and query jobs
- **BigQuery Data Editor** (`roles/bigquery.dataEditor`): create the datasets and tables, write data
  (can later be narrowed to the `raw_pos` and `dq_audit` datasets)

Project owners already have both.

## 4. Configure the repository

In `.env` (not committed):

```
GCP_PROJECT_ID=<PROJECT_ID>
BQ_LOCATION=asia-southeast1
BQ_RAW_DATASET=raw_pos
BQ_AUDIT_DATASET=dq_audit
```

Do **not** set `GOOGLE_APPLICATION_CREDENTIALS`; ADC finds your login automatically.

## 5. Verify

```bash
gcloud auth application-default print-access-token >/dev/null && echo "ADC ok"
.venv/bin/python -m beanflow_ingest.cli init      # creates raw_pos + dq_audit in asia-southeast1
.venv/bin/python -m beanflow_ingest.cli check
```

`asia-southeast1` (Singapore) is used for every dataset. A dataset's location cannot be changed later, and
queries cannot join datasets in different locations.

## Optional: service-account impersonation (least privilege, still no keys)

Not required for the first smoke test. Once things work, you can run the pipeline as a dedicated service
account without downloading a key:

```bash
gcloud iam service-accounts create beanflow-ingest --display-name "BeanFlow ingestion"
gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member "serviceAccount:beanflow-ingest@<PROJECT_ID>.iam.gserviceaccount.com" --role roles/bigquery.jobUser
gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member "serviceAccount:beanflow-ingest@<PROJECT_ID>.iam.gserviceaccount.com" --role roles/bigquery.dataEditor
gcloud iam service-accounts add-iam-policy-binding \
  beanflow-ingest@<PROJECT_ID>.iam.gserviceaccount.com \
  --member "user:<you@example.com>" --role roles/iam.serviceAccountTokenCreator
gcloud auth application-default login \
  --impersonate-service-account=beanflow-ingest@<PROJECT_ID>.iam.gserviceaccount.com
```

## Cost notes

- Data reaches BigQuery only through **load jobs** (free); no streaming inserts.
- Reconciliation reads load-job statistics; `check` and `reconcile --full` run small queries capped at
  1 GB billed (`max_query_bytes` in `ingestion/config/tables.yml`).
- The DEV dataset (90 days) is a few tens of MB.
