from __future__ import annotations

from datetime import datetime
from pathlib import Path

from airflow import DAG
from airflow.decorators import task
from airflow.providers.postgres.hooks.postgres import PostgresHook

CSV_PATH = Path("/opt/airflow/data/raw/olist_customers_dataset.csv")
TABLE_NAME = "ecommerce_customer_staging"

with DAG(
    dag_id="customer_pipeline_simple",
    start_date=datetime(2024, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["customer", "ecommerce"],
) as dag:

    @task
    def create_table():
        """Create the staging table (fixed schema)."""
        create_sql = f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            customer_id TEXT,
            customer_unique_id TEXT,
            customer_zip_code_prefix TEXT,
            customer_city TEXT,
            customer_state TEXT
        );
        """
        postgres_hook = PostgresHook(postgres_conn_id="postgres_dwh")
        postgres_hook.run(create_sql)
        return f"Table {TABLE_NAME} created"

    @task
    def load_csv():
        """Load CSV into Postgres using COPY."""
        postgres_hook = PostgresHook(postgres_conn_id="postgres_dwh")
        conn = postgres_hook.get_conn()
        cursor = conn.cursor()

        copy_sql = f"""
        COPY {TABLE_NAME} (
            customer_id, 
            customer_unique_id, 
            customer_zip_code_prefix, 
            customer_city, 
        customer_state)
        FROM STDIN WITH CSV HEADER DELIMITER ',';
        """

        with open(CSV_PATH, "r", encoding="utf-8") as f:
            cursor.copy_expert(sql=copy_sql, file=f)

        conn.commit()
        cursor.close()
        return f"Loaded {CSV_PATH.name} into {TABLE_NAME}"

    @task
    def process_data():
        """Count customers by state."""
        postgres_hook = PostgresHook(postgres_conn_id="postgres_dwh")
        result_sql = f"""
        SELECT customer_state, COUNT(*) as customer_count
        FROM {TABLE_NAME}
        GROUP BY customer_state
        ORDER BY customer_count DESC;
        """
        results = postgres_hook.get_records(result_sql)
        for state, count in results:
            print(f"{state}: {count}")
        return results

    # Task dependencies
    create_table() >> load_csv() >> process_data()
