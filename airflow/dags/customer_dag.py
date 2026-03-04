"""E-commerce customer MDM pipeline: staging -> Splink deduplication -> master table."""

from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from airflow.decorators import task
from airflow.providers.postgres.hooks.postgres import PostgresHook

from airflow import DAG
from mdm.deduplicate import run_deduplication

logger = logging.getLogger(__name__)

CSV_PATH = Path("/opt/airflow/data/raw/olist_customers_dataset.csv")
STAGING_TABLE = "dwh.ecommerce_customer_staging"
MASTER_TABLE = "dwh.ecommerce_customer_master"

# Default source system when loading from Olist CSV (per instructions: MDM simulation).
SOURCE_SYSTEM_OLIST = "olist"

# CSV column -> staging table column mapping.
CSV_TO_STAGING_COLUMNS = {
    "customer_zip_code_prefix": "zip_code_prefix",
    "customer_city": "city",
    "customer_state": "state",
}
STAGING_COLUMN_ORDER = (
    "source_system",
    "customer_id",
    "customer_unique_id",
    "zip_code_prefix",
    "city",
    "state",
)

# Optional CSV-style column names in staging (if table was created from CSV headers).
STAGING_COLUMN_ALIASES = {
    "customer_zip_code_prefix": "zip_code_prefix",
    "customer_city": "city",
    "customer_state": "state",
}


with DAG(
    dag_id="customer_pipeline_simple",
    start_date=datetime(2024, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["customer", "ecommerce", "mdm"],
) as dag:

    @task
    def create_staging_table() -> str:
        """Create staging table per instructions (source_system, customer_id, ...)."""
        logger.info("Creating schema and staging table %s", STAGING_TABLE)
        hook = PostgresHook(postgres_conn_id="postgres_dwh")
        hook.run("CREATE SCHEMA IF NOT EXISTS dwh")
        hook.run(f"DROP TABLE IF EXISTS {STAGING_TABLE}")
        create_sql = f"""
        CREATE TABLE {STAGING_TABLE} (
            source_system TEXT,
            customer_id TEXT,
            customer_unique_id TEXT,
            zip_code_prefix INTEGER,
            city TEXT,
            state TEXT
        );
        """
        hook.run(create_sql)
        logger.info("Table %s created successfully", STAGING_TABLE)
        return f"Table {STAGING_TABLE} created"

    @task
    def load_csv_to_staging() -> str:
        """Load CSV into Postgres using COPY. Maps CSV columns to staging schema."""
        logger.info("Reading CSV from %s", CSV_PATH)
        if not CSV_PATH.exists():
            raise FileNotFoundError(f"CSV not found: {CSV_PATH}")

        df = pd.read_csv(
            CSV_PATH,
            dtype={
                "customer_id": str,
                "customer_unique_id": str,
                "customer_zip_code_prefix": "Int64",
                "customer_city": str,
                "customer_state": str,
            },
        )
        df = df.rename(columns=CSV_TO_STAGING_COLUMNS)
        df.insert(0, "source_system", SOURCE_SYSTEM_OLIST)
        df = df[list(STAGING_COLUMN_ORDER)]

        hook = PostgresHook(postgres_conn_id="postgres_dwh")
        conn = hook.get_conn()
        cursor = conn.cursor()
        logger.info("Copying %d rows into %s", len(df), STAGING_TABLE)
        buffer = io.StringIO()
        df.to_csv(buffer, index=False, header=False, na_rep="\\N")
        buffer.seek(0)
        columns_str = ", ".join(STAGING_COLUMN_ORDER)
        cursor.copy_expert(
            f"COPY {STAGING_TABLE} ({columns_str}) FROM STDIN WITH (FORMAT csv, NULL '\\N')",
            buffer,
        )
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("Loaded %d rows from %s into %s", len(df), CSV_PATH, STAGING_TABLE)
        return f"Loaded {len(df)} rows into {STAGING_TABLE}"

    @task
    def create_master_table() -> str:
        """Create customer master table per instructions."""
        logger.info("Creating master table %s", MASTER_TABLE)
        create_sql = f"""
        CREATE TABLE IF NOT EXISTS {MASTER_TABLE} (
            master_customer_id UUID PRIMARY KEY,
            customer_unique_id TEXT,
            zip_code_prefix INTEGER,
            city TEXT,
            state TEXT,
            source_count INT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """
        hook = PostgresHook(postgres_conn_id="postgres_dwh")
        hook.run(create_sql)
        logger.info("Master table %s ready", MASTER_TABLE)
        return f"Table {MASTER_TABLE} created"

    @task
    def run_deduplication_and_persist() -> str:
        """Read staging, run Splink deduplication, persist master records to Postgres."""
        hook = PostgresHook(postgres_conn_id="postgres_dwh")
        logger.info("Reading staging data from %s", STAGING_TABLE)
        staging_df = hook.get_pandas_df(f"SELECT * FROM {STAGING_TABLE}")

        if staging_df.empty:
            logger.warning("Staging table is empty; skipping deduplication.")
            return "No staging data to deduplicate"

        logger.info("Staging row count: %d", len(staging_df))

        # Normalize column names: support both canonical (zip_code_prefix, city, state)
        # and CSV-style (customer_zip_code_prefix, customer_city, customer_state).
        rename_map = {
            src: dest
            for src, dest in STAGING_COLUMN_ALIASES.items()
            if src in staging_df.columns and dest not in staging_df.columns
        }
        if rename_map:
            staging_df = staging_df.rename(columns=rename_map)
            logger.debug("Renamed columns: %s", rename_map)

        required_columns = [
            "customer_id",
            "customer_unique_id",
            "zip_code_prefix",
            "city",
            "state",
        ]
        missing = [c for c in required_columns if c not in staging_df.columns]
        if missing:
            raise ValueError(
                f"Staging table {STAGING_TABLE} missing required columns: {missing}. "
                f"Present: {list(staging_df.columns)}"
            )
        staging_df = staging_df[required_columns]

        logger.info("Running Splink deduplication on %d rows", len(staging_df))
        master_records = run_deduplication(staging_df)
        logger.info("Deduplication returned %d master records", len(master_records))

        schema, table_name = MASTER_TABLE.split(".")
        conn = hook.get_conn()
        cursor = conn.cursor()

        # Idempotent: truncate master then insert this run's results.
        logger.info("Truncating %s and inserting %d records", MASTER_TABLE, len(master_records))
        cursor.execute(f"TRUNCATE TABLE {MASTER_TABLE}")

        insert_sql = f"""
        INSERT INTO {MASTER_TABLE}
            (master_customer_id, customer_unique_id, zip_code_prefix, city, state, source_count)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        for rec in master_records:
            # Convert numpy types to native Python so psycopg2 can adapt them.
            cursor.execute(
                insert_sql,
                (
                    str(rec["master_customer_id"]),
                    str(rec["customer_unique_id"]),
                    int(rec["zip_code_prefix"]) if rec["zip_code_prefix"] is not None else None,
                    str(rec["city"]) if rec["city"] is not None else None,
                    str(rec["state"]) if rec["state"] is not None else None,
                    int(rec["source_count"]),
                ),
            )
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("Persisted %d master records to %s", len(master_records), MASTER_TABLE)
        return f"Persisted {len(master_records)} master records to {MASTER_TABLE}"

    # Pipeline: create tables -> load CSV -> create master table -> deduplicate and persist.
    (
        create_staging_table()
        >> load_csv_to_staging()
        >> create_master_table()
        >> run_deduplication_and_persist()
    )
