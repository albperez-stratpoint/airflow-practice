# Airflow Practice

A local development setup for Apache Airflow with a clean separation between DAGs and pipeline logic. Designed for seamless deployment to AWS MWAA (Managed Workflows for Apache Airflow).

## Overview

This project demonstrates a production-ready Airflow project structure:

- **`airflow/dags/`** – Airflow DAG definitions (orchestration)
- **`mdm/`** – Reusable MDM logic (normalize, Splink deduplication, golden records)

## Development vs Deployment

| Environment | `mdm/` setup |
|-------------|---------------|
| **Local Dev** | Mounted at `/opt/airflow/mdm` and on `PYTHONPATH` via docker-compose |
| **AWS MWAA** | Upload `mdm/` into the DAGs prefix so workers can import it (see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)) |

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

The **mdm_golden_records** DAG reads partitioned raw CSVs (CRM, Billing, Support) for a given **logical date** and writes deduplicated golden records to the DWH. You can run it in two ways:

**Option A – Backfill for a specific date (recommended when you already have data)**

Use when raw files already exist for a date (e.g. you ran `scripts/generate_mdm_synthetic.py` for that day):

```bash
# Run the DAG for a single date (use a date you have data for)
docker compose -f local/docker-compose.yaml exec airflow-scheduler airflow dags backfill mdm_golden_records -s 2025-01-06 -e 2025-01-06
```

**Option B – Trigger the DAG manually**

If you trigger the DAG from the Airflow UI, the logical date is **today**. Ensure raw data for **today** exists first:

```bash
# Generate data for today so the DAG finds files under data/raw/<source>/YYYY/MM/YYYYMMDD.csv
uv run python scripts/generate_mdm_synthetic.py --date $(date +%Y%m%d) --days 1
```

Then trigger **mdm_golden_records** in the UI. If you don’t generate data for the run date, the `validate_mdm_raw_headers` task will fail with “Missing: …”.

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

-- 3. Row counts for golden and crosswalk
SELECT 'mdm_customers' AS table_name, count(*) FROM dwh.mdm_customers
UNION ALL
SELECT 'mdm_customer_crosswalk', count(*) FROM dwh.mdm_customer_crosswalk;

-- 4. Sample golden records
SELECT mdm_customer_id, golden_name, golden_email, golden_address
FROM dwh.mdm_customers
LIMIT 10;
```

Exit with `\q`.

**One-liner from the host (no interactive psql):**

```bash
docker compose -f local/docker-compose.yaml exec postgres psql -U dwh_user -d dwh -c "\dt dwh.*"
docker compose -f local/docker-compose.yaml exec postgres psql -U dwh_user -d dwh -c "SELECT count(*) FROM dwh.mdm_customers;"
```

You can run similar queries from the host using `docker compose ... exec postgres psql` as in the one-liners above.

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
│   │   └── mdm_golden_dag.py # CRM/Billing/Support → normalize → Splink → golden records
│   └── plugins/              # Custom Airflow plugins (optional)
├── mdm/                      # MDM business logic (Splink, normalize, golden record)
│   ├── deduplicate_mdm.py
│   ├── normalize_raw.py
│   ├── golden_record.py
│   └── splink_settings.py
├── scripts/
│   ├── setup_dwh.sh          # Create DWH database/user/schema (make setup-dwh)
│   └── generate_mdm_synthetic.py  # Synthetic CRM/Billing/Support CSVs per docs/SCENARIO.md
├── pyproject.toml            # Dependencies (pandas, splink, psycopg2, etc.)
├── docs/
│   ├── DEPLOYMENT.md         # AWS MWAA deployment guide
│   └── SCENARIO.md           # MDM synthetic dataset specification
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

### Synthetic data generator (`scripts/generate_mdm_synthetic.py`)

Generates synthetic CRM, Billing, and Support CSVs per [docs/SCENARIO.md](docs/SCENARIO.md) for MDM (entity resolution, golden records). Output: `data/raw/{crm,billing,support}/%Y/%m/%Y%m%d.csv`.

**Usage**

```bash
uv run python scripts/generate_mdm_synthetic.py [OPTIONS]
```

See the script `--help` for options (e.g. `--output-dir`, `--date`, `--days`). Defaults produce ~20k CRM, ~15k Billing, ~25k Support rows with duplicates and anomalies.

## Raw data (MDM synthetic)

Data produced by `scripts/generate_mdm_synthetic.py` is written under **partitioned paths** per source (CRM, Billing, Support). Schema and anomalies are defined in [docs/SCENARIO.md](docs/SCENARIO.md).

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
│   └── 2025/03/20250306.csv
├── billing/
│   └── 2025/03/20250306.csv
└── support/
    └── 2025/03/20250306.csv
```

Column sets match the DAG’s expected headers (see `mdm_golden_dag.py` and docs/SCENARIO.md). The DAG validates headers and then normalizes, deduplicates with Splink, and writes `dwh.mdm_customers` and `dwh.mdm_customer_crosswalk`.

## Local Development

The `mdm/` directory is mounted at `/opt/airflow/mdm` in the containers and is on `PYTHONPATH`, so you can edit code in `mdm/` and see changes without rebuilding images.

### Linting

Before committing changes, run the linter to ensure code quality:

```bash
make lint
```

This runs `ruff` to check and auto-fix imports, format code, and fix linting issues.

A linting check is also enforced in CI on every push and pull request.

## AWS MWAA Deployment

For a step-by-step guide to deploying this project to **AWS MWAA** (including how to upload the synthetic raw data to S3 and wire it into the `mdm_golden_records` DAG), see **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.
