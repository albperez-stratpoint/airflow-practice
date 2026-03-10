## AWS MWAA Deployment Guide

This document describes how to deploy this project to **Amazon Managed Workflows for Apache Airflow (MWAA)** and how to make the **synthetic raw data** available to MWAA from **Amazon S3**.

The instructions assume you already have:

- An AWS account
- The AWS CLI configured (`aws sts get-caller-identity` succeeds)
- Permissions to create **S3 buckets**, **MWAA environments**, **IAM roles**, and (optionally) **RDS/Aurora** databases

---

## 1. High-level architecture

- **MWAA environment**
  - Runs Apache Airflow (managed control plane + workers)
  - Uses an S3 bucket/prefix as the **DAGs and plugins source**
- **S3 bucket**
  - Stores:
    - Airflow DAGs and the **`mdm`** package (under the DAGs folder so workers can `import mdm`)
    - Airflow plugins
    - `requirements.txt` for Python dependencies (pandas, splink, psycopg2, etc.)
    - **Synthetic raw data** under a `data/raw/` prefix
- **Postgres DWH**
  - A Postgres-compatible database (RDS or Aurora) reachable from the MWAA VPC
  - Connection configured in Airflow as `postgres_dwh`

Suggested S3 layout (you can adjust names/prefixes as needed):

```text
s3://<mwaa_bucket>/<dags_prefix>/
├── dags/
│   ├── mdm_golden_dag.py
│   └── mdm/                 # Package imported by the DAG (upload entire mdm/ here)
│       ├── __init__.py
│       ├── deduplicate_mdm.py
│       ├── normalize_raw.py
│       └── ...
├── plugins/
│   └── ...
├── requirements/
│   └── requirements.txt
└── data/
    └── raw/
        ├── crm/
        ├── billing/
        └── support/
```

The **data layout** under `data/raw/` should match what `scripts/generate_mdm_synthetic.py` produces locally.

---

## 2. Upload the `mdm` package with your DAGs

The DAG imports `mdm` (e.g. `from mdm.deduplicate_mdm import run_mdm_deduplication`). MWAA syncs only the **DAGs folder** to workers, so the `mdm` package must live **inside** that folder. Upload the repo’s `mdm/` directory under the same S3 prefix as your DAGs:

```bash
# After uploading airflow/dags/ to s3://<mwaa_bucket>/<dags_prefix>/dags/
# also upload mdm/ into dags/mdm/ so workers get /usr/local/airflow/dags/mdm/
aws s3 sync \
  mdm/ \
  s3://<mwaa_bucket>/<dags_prefix>/dags/mdm/
```

Workers will then have `/usr/local/airflow/dags/mdm/` on disk and `from mdm.xxx` will resolve. No separate wheel is required.

---

## 3. Prepare raw data for S3

In local development, raw data is generated under `data/raw`. For MWAA we keep the **same folder structure**, but store it in S3 so the files are synced into the MWAA workers.

### 3.1 Generate data locally

From the project root:

```bash
uv run python scripts/generate_mdm_synthetic.py --output-dir data/raw --date 20250306 --days 2
```

This produces a layout like:

```text
data/raw/
├── crm/
│   └── 2025/03/20250306.csv
├── billing/
│   └── 2025/03/20250306.csv
└── support/
    └── 2025/03/20250306.csv
```

### 3.2 Upload raw data to the MWAA S3 bucket

Assuming:

- S3 bucket: `s3://<mwaa_bucket>`
- DAGs prefix: `<dags_prefix>` (for example, `airflow`)

Sync your local raw data so that it lands under `data/raw/` inside the DAGs prefix:

```bash
aws s3 sync \
  data/raw/ \
  s3://<mwaa_bucket>/<dags_prefix>/data/raw/
```

On MWAA workers, these files will appear under:

```text
/usr/local/airflow/dags/data/raw/
```

The MDM DAG uses an Airflow **Variable** called `raw_data_base_path` with a default of `/opt/airflow/data/raw`. In MWAA we override this to point at the synced location:

- Key: `raw_data_base_path`
- Value: `/usr/local/airflow/dags/data/raw`

You will create this variable after the environment is up (see section 6).

---

## 4. Upload DAGs, plugins, wheel, and requirements to S3

Pick an S3 bucket and prefix for MWAA, for example:

- Bucket: `mwaa-airflow-practice-<account>-<region>`
- DAGs prefix: `airflow`

Create the base folder structure:

```bash
aws s3api put-object --bucket <mwaa_bucket> --key <dags_prefix>/
aws s3api put-object --bucket <mwaa_bucket> --key <dags_prefix>/dags/
aws s3api put-object --bucket <mwaa_bucket> --key <dags_prefix>/plugins/
aws s3api put-object --bucket <mwaa_bucket> --key <dags_prefix>/requirements/
```

### 4.1 Upload DAGs and the `mdm` package

```bash
aws s3 sync \
  airflow/dags/ \
  s3://<mwaa_bucket>/<dags_prefix>/dags/

aws s3 sync \
  mdm/ \
  s3://<mwaa_bucket>/<dags_prefix>/dags/mdm/
```

### 4.2 Upload plugins (optional)

If you add custom plugins under `airflow/plugins`:

```bash
aws s3 sync \
  airflow/plugins/ \
  s3://<mwaa_bucket>/<dags_prefix>/plugins/
```

### 4.3 Upload `requirements.txt`

Re-use the existing `requirements.txt` (or create a slimmer one specifically for MWAA if you prefer). Upload it under a dedicated `requirements/` prefix:

```bash
aws s3 cp \
  requirements.txt \
  s3://<mwaa_bucket>/<dags_prefix>/requirements/requirements.txt
```

Use a `requirements.txt` that includes the project’s runtime dependencies (e.g. from `uv export --format requirements-txt`, or a slimmer file with pandas, splink, psycopg2-binary, etc.). MWAA will install them at environment build/update time.

---

## 5. Create the MWAA environment

Use the AWS console or Infrastructure as Code (CloudFormation, CDK, Terraform) to create an MWAA environment.

Key parameters:

- **S3 bucket**: `s3://<mwaa_bucket>`
- **DAGs folder**: `<dags_prefix>/dags`
- **Plugins folder**: `<dags_prefix>/plugins` (optional)
- **Requirements file**: `<dags_prefix>/requirements/requirements.txt`
- **Execution role**: IAM role with:
  - Read access to `s3://<mwaa_bucket>/<dags_prefix>/...`
  - Network access to your Postgres DWH (through attached security groups)

Choose an Apache Airflow version and Python version that are supported by MWAA in your region. Refer to the official AWS documentation for the latest supported combinations.

---

## 6. Configure connections and variables in MWAA

After the environment is created and in a **Available** state, open the Airflow UI from the MWAA console and configure:

### 6.1 Postgres DWH connection

Create a connection named `postgres_dwh`:

- **Conn Id**: `postgres_dwh`
- **Conn Type**: `Postgres`
- **Host**: `<your-rds-endpoint>`
- **Schema**: `dwh`
- **Login**: `dwh_user`
- **Password**: `dwh_pass`
- **Port**: `5432`

Adjust values for your actual DWH. The DAG expects this connection ID for `PostgresHook(postgres_conn_id="postgres_dwh")`.

### 6.2 Raw data base path variable

Create the Airflow Variable that tells the DAG where raw CSVs live on the worker filesystem:

- **Key**: `raw_data_base_path`
- **Value**: `/usr/local/airflow/dags/data/raw`

This mirrors how the data is synced from `s3://<mwaa_bucket>/<dags_prefix>/data/raw/`.

---

## 7. Verify the MDM DAG on MWAA

Once MWAA finishes installing dependencies and parsing DAGs:

1. Open the Airflow UI.
2. Confirm that the `mdm_golden_records` DAG is listed.
3. Ensure that for at least one logical date (for example, `2025-03-06`) you have uploaded:
   - `crm/2025/03/20250306.csv`
   - `billing/2025/03/20250306.csv`
   - `support/2025/03/20250306.csv`
   under `data/raw/` in S3.
4. Trigger the DAG manually for that date (set the logical date in the UI or backfill).
5. Monitor the tasks:
   - `validate_mdm_raw_headers`
   - `create_mdm_tables`
   - `load_raw_normalize_and_deduplicate`

If everything is wired correctly, the DAG will:

- Read CSVs from `/usr/local/airflow/dags/data/raw/...`
- Normalize them into a staging representation
- Run Splink deduplication
- Write golden records into `dwh.mdm_customers` and crosswalk rows into `dwh.mdm_customer_crosswalk`

---

## 8. Updating code and data

When you change DAGs, the `mdm` package, plugins, or raw data:

- **DAGs / mdm**:
  - Re-sync `airflow/dags/` and `mdm/` to `s3://<mwaa_bucket>/<dags_prefix>/dags/` and `.../dags/mdm/`.
- **Plugins**:
  - Re-sync `airflow/plugins/` to the S3 plugins prefix.
- **Raw data**:
  - Regenerate with `scripts/generate_mdm_synthetic.py`
  - Re-sync `data/raw/` to `s3://<mwaa_bucket>/<dags_prefix>/data/raw/`

MWAA will pick up new DAGs automatically; dependency and data changes will take effect on subsequent runs once the environment has finished installing updated requirements.
