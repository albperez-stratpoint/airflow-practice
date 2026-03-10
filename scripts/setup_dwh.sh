#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

COMPOSE_FLAGS=${COMPOSE_FLAGS:---env-file .env -f local/docker-compose.yaml}
COMPOSE_CMD="docker compose ${COMPOSE_FLAGS}"

echo "Setting up DWH database and schema in postgres container..."

${COMPOSE_CMD} exec -T postgres psql -U airflow -d airflow <<'SQL'
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
SQL

echo "DWH database, user, and schema created. Remember to set AIRFLOW_CONN_POSTGRES_DWH in .env."

