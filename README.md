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

```bash
curl -LfO 'https://airflow.apache.org/docs/apache-airflow/2.8.3/docker-compose.yaml'
```

Optionally set `AIRFLOW__CORE__LOAD_EXAMPLES: 'false'` in the compose file to disable example DAGs.

We will also use custom image so we need do the follow:

```yaml
# Comment this
# image: ${AIRFLOW_IMAGE_NAME:-apache/airflow:2.8.3}

# Uncomment this
build: .
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

```bash
docker compose up -d
```

### 7. Reuse postgres service for data warehouse

```bash
--0. Connect to the existing PostgreSQL container
docker-compose exec postgres psql -U airflow

-- 1. Create a separate database for the DWH (optional; you can also use 'airflow' DB)
CREATE DATABASE dwh;

-- 2. Create a dedicated DWH user
CREATE USER dwh_user WITH PASSWORD 'dwh_pass';

-- 3. Grant all privileges on the new database to the DWH user
GRANT ALL PRIVILEGES ON DATABASE dwh TO dwh_user;

-- 4. Connect to the DWH database
\c dwh

-- 5. Create a dedicated schema (optional but recommended)
CREATE SCHEMA dwh_schema AUTHORIZATION dwh_user;

-- 6. Grant privileges on the schema
GRANT USAGE ON SCHEMA dwh_schema TO dwh_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA dwh_schema TO dwh_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA dwh_schema GRANT ALL ON TABLES TO dwh_user;

-- 7. Verify the schema
\dn
```

### 8. Access Airflow UI

Open http://localhost:8080 in your browser.

**Default credentials:**
- Username: `airflow`
- Password: `airflow`

## Project Structure

```
.
├── dags/                     # Airflow DAG definitions
│   └── sample_df_to_csv_dag.py
├── pipelines/                # Reusable pipeline logic (Python package)
│   ├── __init__.py
│   └── df_to_csv.py
├── pyproject.toml            # Package definition for pipelines
└── docker-compose.yaml       # Local Airflow stack
```

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
