from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from airflow.decorators import task
from airflow.models import Variable
from airflow.operators.python import get_current_context
from airflow.providers.postgres.hooks.postgres import PostgresHook

from airflow import DAG
from mdm.deduplicate import run_entity_deduplication

logger = logging.getLogger(__name__)

# Sources under data/raw/{source}/%Y/%m/%Y%m%d.csv (must match scripts/generate.py).
RAW_SOURCES = ("crm", "ticketing", "support", "billing", "marketing")

# Expected CSV header (order and names); must match scripts/generate.py CSV_COLUMNS.
EXPECTED_RAW_HEADERS = (
    "entity_id",
    "source_system",
    "source_record_id",
    "full_name",
    "email",
    "address",
    "phone",
    "created_at",
)
EXPECTED_HEADER_LINE = ",".join(EXPECTED_RAW_HEADERS)

STAGING_TABLE = "dwh.entity_staging"
MASTER_TABLE = "dwh.entity_master"

# Base path for raw data inside the Airflow containers.
# Matches docker-compose.yaml volume: "./data:/opt/airflow/data".
# Can be overridden via Airflow Variable "raw_data_base_path" if needed.
DEFAULT_RAW_BASE = "/opt/airflow/data/raw"


def _raw_base_path() -> Path:
    base = Variable.get("raw_data_base_path", default_var=DEFAULT_RAW_BASE)
    return Path(base)


def _partition_path(base: Path, source: str, logical_date: datetime) -> Path:
    """Path to CSV for given source and logical date: base/{source}/%Y/%m/%Y%m%d.csv."""
    y = logical_date.strftime("%Y")
    m = logical_date.strftime("%m")
    d = logical_date.strftime("%Y%m%d")
    return base / source / y / m / f"{d}.csv"


with DAG(
    dag_id="raw_mdm_reconcile",
    start_date=datetime(2024, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["raw", "mdm", "splink", "reconcile"],
) as dag:

    @task
    def validate_raw_headers() -> str:
        """Check that each source has a CSV for the logical date with expected headers."""
        context = get_current_context()
        logical_date = context["logical_date"]
        base = _raw_base_path()

        errors: list[str] = []
        for source in RAW_SOURCES:
            path = _partition_path(base, source, logical_date)
            try:
                exists = path.exists()
            except PermissionError as exc:  # pragma: no cover - environment specific
                raise PermissionError(
                    f"Airflow worker cannot access raw path {path!s}. "
                    "Check Docker volume mounts and host filesystem permissions "
                    "(for example Docker Desktop file access to this directory)."
                ) from exc

            if not exists:
                errors.append(f"Missing: {path}")
                continue

            try:
                with path.open(encoding="utf-8") as f:
                    first_line = f.readline().strip()
            except PermissionError as exc:  # pragma: no cover - environment specific
                raise PermissionError(
                    f"Airflow worker cannot read file {path!s}. "
                    "Ensure the container user has read permission on this path."
                ) from exc

            if first_line != EXPECTED_HEADER_LINE:
                errors.append(
                    f"{source}: header mismatch at {path}. "
                    f"Expected: {EXPECTED_HEADER_LINE!r}, got: {first_line!r}"
                )

        if errors:
            raise ValueError("Header validation failed:\n" + "\n".join(errors))

        logger.info(
            "Headers validated for %d sources at %s",
            len(RAW_SOURCES),
            logical_date.strftime("%Y-%m-%d"),
        )
        return f"Validated {len(RAW_SOURCES)} sources"

    @task
    def create_staging_and_master_tables() -> str:
        """Create dwh.entity_staging and dwh.entity_master if not exist."""
        hook = PostgresHook(postgres_conn_id="postgres_dwh")
        hook.run("CREATE SCHEMA IF NOT EXISTS dwh")

        hook.run(f"DROP TABLE IF EXISTS {STAGING_TABLE}")
        staging_sql = f"""
        CREATE TABLE {STAGING_TABLE} (
            entity_id TEXT,
            source_system TEXT,
            source_record_id TEXT,
            full_name TEXT,
            email TEXT,
            address TEXT,
            phone TEXT,
            created_at TIMESTAMP
        );
        """
        hook.run(staging_sql)

        master_sql = f"""
        CREATE TABLE IF NOT EXISTS {MASTER_TABLE} (
            master_entity_id UUID PRIMARY KEY,
            full_name TEXT,
            email TEXT,
            address TEXT,
            source_count INT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """
        hook.run(master_sql)
        logger.info("Tables %s and %s ready", STAGING_TABLE, MASTER_TABLE)
        return f"Created {STAGING_TABLE}, ensured {MASTER_TABLE}"

    @task
    def load_raw_to_staging() -> str:
        """Load all source CSVs for the logical date into staging."""
        context = get_current_context()
        logical_date = context["logical_date"]
        base = _raw_base_path()

        dfs: list[pd.DataFrame] = []
        for source in RAW_SOURCES:
            path = _partition_path(base, source, logical_date)
            if not path.exists():
                logger.warning("Skipping missing file: %s", path)
                continue
            df = pd.read_csv(
                path,
                dtype={
                    "entity_id": str,
                    "source_system": str,
                    "source_record_id": str,
                    "full_name": str,
                    "email": str,
                    "address": str,
                    "phone": str,
                },
                parse_dates=["created_at"],
            )
            dfs.append(df)

        if not dfs:
            raise FileNotFoundError(
                f"No raw files found for {logical_date.strftime('%Y-%m-%d')} under {base}"
            )

        combined = pd.concat(dfs, ignore_index=True)
        hook = PostgresHook(postgres_conn_id="postgres_dwh")
        conn = hook.get_conn()
        cursor = conn.cursor()

        buffer = io.StringIO()
        combined.to_csv(buffer, index=False, header=False, na_rep="\\N")
        buffer.seek(0)
        columns_str = ", ".join(EXPECTED_RAW_HEADERS)
        cursor.copy_expert(
            f"COPY {STAGING_TABLE} ({columns_str}) FROM STDIN WITH (FORMAT csv, NULL '\\N')",
            buffer,
        )
        conn.commit()
        cursor.close()
        conn.close()

        logger.info("Loaded %d rows into %s", len(combined), STAGING_TABLE)
        return f"Loaded {len(combined)} rows into {STAGING_TABLE}"

    @task
    def run_splink_and_persist_master() -> str:
        """Read staging, run Splink entity deduplication, persist to master table."""
        hook = PostgresHook(postgres_conn_id="postgres_dwh")
        staging_df = hook.get_pandas_df(f"SELECT * FROM {STAGING_TABLE}")

        if staging_df.empty:
            logger.warning("Staging table is empty; skipping deduplication.")
            return "No staging data to deduplicate"

        # Splink expects source_record_id, full_name, email, address (others ignored).
        required = ["source_record_id", "full_name", "email", "address"]
        missing = [c for c in required if c not in staging_df.columns]
        if missing:
            raise ValueError(
                f"Staging missing columns: {missing}. Present: {list(staging_df.columns)}"
            )

        master_records = run_entity_deduplication(staging_df)

        conn = hook.get_conn()
        cursor = conn.cursor()
        cursor.execute(f"TRUNCATE TABLE {MASTER_TABLE}")

        insert_sql = f"""
        INSERT INTO {MASTER_TABLE}
            (master_entity_id, full_name, email, address, source_count)
        VALUES (%s, %s, %s, %s, %s)
        """
        for rec in master_records:
            cursor.execute(
                insert_sql,
                (
                    str(rec["master_entity_id"]),
                    str(rec["full_name"]) if rec["full_name"] is not None else None,
                    str(rec["email"]) if rec["email"] is not None else None,
                    str(rec["address"]) if rec["address"] is not None else None,
                    int(rec["source_count"]),
                ),
            )
        conn.commit()
        cursor.close()
        conn.close()

        logger.info("Persisted %d master records to %s", len(master_records), MASTER_TABLE)
        return f"Persisted {len(master_records)} records to {MASTER_TABLE}"

    (
        validate_raw_headers()
        >> create_staging_and_master_tables()
        >> load_raw_to_staging()
        >> run_splink_and_persist_master()
    )
