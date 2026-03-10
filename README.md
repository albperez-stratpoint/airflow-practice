# Airflow Practice

A local development setup for Apache Airflow with a clean separation between DAGs and pipeline logic. Designed for seamless deployment to AWS MWAA (Managed Workflows for Apache Airflow).

## Overview

This project demonstrates a production-ready Airflow project structure:

- **`dags/`** - Contains Airflow DAG definitions (orchestration layer)
- **`pipelines/`** - Contains reusable pipeline logic (business logic layer), packaged as a Python module

## Development vs Deployment

| Environment | `pipelines/` Setup |
|-------------|-------------------|
| **Local Dev** | Mounted as volume + added to `PYTHONPATH` via docker-compose |
| **AWS MWAA** | Built as wheel from `pyproject.toml` and installed via `requirements.txt` |

## Prerequisites

- Docker and Docker Compose
- [uv](https://github.com/astral-sh/uv) for Python package management (optional, for local development)

## Quick Start

### 1. Install uv (optional)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Create virtual environment and set Python version

```bash
uv venv --python 3.8.18
```

### 3. Get official docker-compose file for Airflow 2.8.3

> Note: This repo already includes a compose file at `local/docker-compose.yaml`.  
> The following step is only needed if you want to refresh it from upstream.

```bash
curl -LfO 'https://airflow.apache.org/docs/apache-airflow/2.8.3/docker-compose.yaml'
mv docker-compose.yaml local/docker-compose.yaml
```

Optionally set `AIRFLOW__CORE__LOAD_EXAMPLES: 'false'` in the compose file to disable example DAGs.

We will also use a custom image so we need to do the following in `local/docker-compose.yaml` (already applied in this repo):

```yaml
# Comment this
# image: ${AIRFLOW_IMAGE_NAME:-apache/airflow:2.8.3}

# Uncomment/ensure this block exists
build:
  context: ..
  dockerfile: local/Dockerfile
```

We do this since we need to add additional dependencies, though we could populate `    _PIP_ADDITIONAL_REQUIREMENTS: ${_PIP_ADDITIONAL_REQUIREMENTS:-}`.

### 4. Import dependencies to `requirements.txt` which is used in `Dockerfile`.

```bash
uv export --format requirements-txt > requirements.txt
```

### 5. Add AIRFLOW_UID to .env file

```bash
echo -e "AIRFLOW_UID=$(id -u)" >> .env
```

### 6. Start Airflow

From the project root:

```bash
make up
```

Or manually:

```bash
docker compose --env-file .env -f local/docker-compose.yaml up -d
```

### 7. Reuse postgres service for data warehouse

Create a separate `dwh` database and schema so the DAG can create staging tables.

**Option A – Run the setup script (recommended)**

With the stack running (`make up`), from the project root:

```bash
make setup-dwh
```

This runs `scripts/setup_dwh.sh`, which executes the SQL below inside the postgres container. Ensure `.env` contains the DWH connection (see end of step).

**Option B – Run the SQL manually**

Connect to the existing PostgreSQL container and run the statements yourself:

```bash
docker compose -f local/docker-compose.yaml exec postgres psql -U airflow -d airflow
```

Then in the `psql` prompt:

```sql
-- 1. Create a separate database for the DWH
CREATE DATABASE dwh;

-- 2. Create a dedicated DWH user
CREATE USER dwh_user WITH PASSWORD 'dwh_pass';

-- 3. Grant all privileges on the new database to the DWH user
GRANT ALL PRIVILEGES ON DATABASE dwh TO dwh_user;

-- 4. Connect to the DWH database
\c dwh

-- 5. Create a dedicated schema (optional but recommended)
CREATE SCHEMA dwh AUTHORIZATION dwh_user;

-- 6. Grant privileges on the schema
GRANT USAGE ON SCHEMA dwh TO dwh_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA dwh TO dwh_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA dwh GRANT ALL ON TABLES TO dwh_user;

-- 7. Verify the schema
\dn
```

Ensure `.env` contains the DWH connection (database `dwh`):

```bash
AIRFLOW_CONN_POSTGRES_DWH=postgresql://dwh_user:dwh_pass@postgres:5432/dwh?options=-csearch_path%3Ddwh
```

### 8. Access Airflow UI

Open http://localhost:8080 in your browser.

**Default credentials:**
- Username: `airflow`
- Password: `airflow`

### 9. Run the MDM DAG and verify master data

The **raw_mdm_reconcile** DAG reads partitioned raw CSVs for a given **logical date** and writes deduplicated master records to the DWH. You can run it in two ways:

**Option A – Backfill for a specific date (recommended when you already have data)**

Use when raw files already exist for a date (e.g. you ran `scripts/generate.py` for that day):

```bash
# Run the DAG for a single date (use a date you have data for)
docker compose -f local/docker-compose.yaml exec airflow-scheduler airflow dags backfill raw_mdm_reconcile -s 2025-01-06 -e 2025-01-06
```

**Option B – Trigger the DAG manually**

If you trigger the DAG from the Airflow UI, the logical date is **today**. Ensure raw data for **today** exists first:

```bash
# Generate data for today so the DAG finds files under data/raw/<source>/YYYY/MM/YYYYMMDD.csv
uv run python scripts/generate.py --date $(date +%Y%m%d) --days 1
```

Then trigger **raw_mdm_reconcile** in the UI. If you don’t generate data for the run date, the `validate_raw_headers` task will fail with “Missing: …”.

**Verify master data via Docker exec**

Connect to Postgres and inspect the DWH schema and tables:

```bash
# 1. Open a psql session in the postgres container (connects to the dwh database)
docker compose -f local/docker-compose.yaml exec postgres psql -U dwh_user -d dwh
```

In the `psql` prompt:

```sql
-- 2. List tables in the dwh schema
\dt dwh.*

-- 3. Row counts for staging and master
SELECT 'entity_staging' AS table_name, count(*) FROM dwh.entity_staging
UNION ALL
SELECT 'entity_master', count(*) FROM dwh.entity_master;

-- 4. Sample master records
SELECT master_entity_id, full_name, email, address, source_count, created_at
FROM dwh.entity_master
LIMIT 10;
```

Exit with `\q`.

**One-liner from the host (no interactive psql):**

```bash
docker compose -f local/docker-compose.yaml exec postgres psql -U dwh_user -d dwh -c "\dt dwh.*"
docker compose -f local/docker-compose.yaml exec postgres psql -U dwh_user -d dwh -c "SELECT count(*) FROM dwh.entity_master;"
```

You can also use the helper script from the project root: `./scripts/check_dwh_psql.sh` (ensure `PGUSER`/`PGDATABASE` match your setup, or adjust the script to use `dwh_user` and `dwh` if you use the separate DWH database).

## Makefile targets

Run from the project root. Compose commands use `--env-file .env -f local/docker-compose.yaml`.

| Target | Description |
|--------|-------------|
| `make up` | Start the Airflow stack in the background |
| `make down` | Stop the stack |
| `make build` | Build Docker images |
| `make logs` | Stream logs from all services |
| `make ps` | List running services |
| `make setup-dwh` | Create DWH database, user, and schema (step 7) |
| `make psql` | Open psql in postgres container (airflow DB) |
| `make lint` | Run ruff (imports, format, fix) |

## Project Structure

```
.
├── airflow/
│   ├── dags/                 # Airflow DAG definitions
│   │   ├── raw_mdm_dag.py    # Raw → staging → Splink → master (MDM)
│   │   ├── sample_df_to_csv_dag.py
│   │   └── test_env_dag.py
│   └── plugins/              # Custom Airflow plugins (optional)
├── mdm/                      # Splink deduplication and settings
│   ├── deduplicate.py
│   └── splink_settings.py
├── scripts/                  # CLI and utility scripts
│   ├── setup_dwh.sh          # Create DWH database/user/schema (make setup-dwh)
│   ├── check_dwh_psql.sh     # Verify staging/master via docker exec
│   └── generate.py           # Synthetic entity-resolution data generator
├── src/                      # Application code (if needed)
├── pipelines/                # Reusable pipeline logic (Python package)
│   ├── __init__.py
│   └── df_to_csv.py
├── pyproject.toml            # Package definition for pipelines
└── local/
    ├── docker-compose.yaml   # Local Airflow stack
    └── Dockerfile            # Custom Airflow image
```

## Scripts

### DWH setup (`scripts/setup_dwh.sh`)

Creates the `dwh` database, `dwh_user`, and `dwh` schema in the postgres container (Quick Start step 7). Run with:

```bash
make setup-dwh
```

Requires the stack to be up (`make up`). After running, ensure `.env` contains `AIRFLOW_CONN_POSTGRES_DWH=postgresql://dwh_user:dwh_pass@postgres:5432/dwh?options=-csearch_path%3Ddwh`.

### Synthetic data generator (`scripts/generate.py`)

Generates synthetic customer-like data for **entity resolution** across multiple source systems. Output is written as partitioned CSVs with intentional noise (typos, transpositions, extra characters) in name, email, and address so you can test matching and deduplication (e.g. with Splink).

**Usage**

```bash
uv run python scripts/generate.py [OPTIONS]
```

| Option | Default | Description |
|--------|--------|-------------|
| `--output-dir` | `data/raw` | Base directory for partition folders |
| `--date` | today | Start date (`YYYYMMDD`) |
| `--days` | `2` | Number of consecutive days (partitions) to generate |
| `--sources` | `crm,ticketing,support,billing,marketing` | Comma-separated source system names |
| `--num-entities` | `200` | Number of canonical entities to generate |
| `--noise` | `0.25` | Probability of noise per field (0–1) |
| `--master-source` | `crm` | Source that **owns** address updates across days |
| `--master-change-prob` | `0.3` | Daily probability that the master source changes an entity’s address |
| `--seed` | — | Random seed for reproducible runs |
| `-v`, `--verbose` | — | Enable verbose logging |

**Examples**

```bash
# Default: 200 entities, 5 sources, today’s date
uv run python scripts/generate.py

# Smaller run with fixed seed and specific date
uv run python scripts/generate.py --num-entities 50 --seed 42 --date 20250306

# Custom sources and higher noise
uv run python scripts/generate.py --sources "crm,zendesk,stripe" --noise 0.4
```

## Raw data (synthetic entity-resolution)

Data produced by `scripts/generate.py` is written under **partitioned paths** so that one file per source per day is produced. You typically run the generator **once** over a small date range (e.g. 2–7 days) to create a realistic history.

### Folder structure

```
<output-dir>/
└── <source>/
    └── %Y/
        └── %m/
            └── %Y%m%d.csv
```

Example with `--output-dir data/raw` and date `20250306`:

```
data/raw/
├── crm/
│   └── 2025/
│       └── 03/
│           └── 20250306.csv
├── ticketing/
│   └── 2025/
│       └── 03/
│           └── 20250306.csv
├── support/
│   └── 2025/
│       └── 03/
│           └── 20250306.csv
├── billing/
│   └── 2025/
│       └── 03/
│           └── 20250306.csv
└── marketing/
    └── 2025/
        └── 03/
            └── 20250306.csv
```

### CSV schema

| Column | Description |
|--------|-------------|
| `entity_id` | Canonical entity ID (same person across sources); use as ground truth for entity resolution. |
| `source_system` | Source system name (e.g. `crm`, `ticketing`). |
| `source_record_id` | Unique record ID within that source and date. |
| `full_name` | Full name; may contain noise (deletions, transpositions, extra chars). |
| `email` | Email; may contain noise. |
| `address` | Single-line address; may contain noise. |
| `phone` | Phone number (no noise applied). |
| `created_at` | ISO timestamp; use the **latest** per `entity_id` (and optionally per `source_system`) as the current/master record. |

### Noise applied

To simulate real-world data quality, the script applies (with configurable probability) to **name**, **email**, and **address** only:

- **Deletion** – one random character removed.
- **Transposition** – two adjacent characters swapped.
- **Insertion** – one extra character (duplicate or keyboard-neighbor typo).

The same logical entity can appear in multiple sources with different noise, so you can validate that entity resolution correctly links records across systems.

For the configured **master source** (default: `crm`), some entities will have **multiple address versions** within the same partition file (different `created_at` and sometimes different `address` values). This lets you model scenarios like:

- An old address for a customer (e.g. *Nicole Burton*) being updated multiple times.
- Many historical addresses in the raw data, while downstream logic **always picks the latest `created_at`** from the master source as the authoritative address.

## Local Development

The `pipelines/` directory is mounted as a volume at `/opt/airflow/pipelines` in the containers, and the `PYTHONPATH` is configured to make the package discoverable. This allows you to edit pipeline code and see changes immediately without rebuilding images.

### Linting

Before committing changes, run the linter to ensure code quality:

```bash
make lint
```

This runs `ruff` to check and auto-fix imports, format code, and fix linting issues.

A linting check is also enforced in CI on every push and pull request.

## AWS MWAA Deployment (NOT YET TESTED)

For production deployment to AWS MWAA:

1. Build the `pipelines` package as a wheel:
   ```bash
   uv build --wheel
   ```

2. Upload the generated wheel (in `dist/`) to your MWAA S3 bucket

3. Add the wheel to your `requirements.txt`:
   ```
   --find-links /usr/local/airflow/dags/wheels
   pipelines==0.1.0
   ```
