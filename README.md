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

### 4. Add AIRFLOW_UID to .env file

```bash
echo -e "AIRFLOW_UID=$(id -u)" >> .env
```

### 5. Start Airflow

```bash
docker compose up -d
```

### 6. Access Airflow UI

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
