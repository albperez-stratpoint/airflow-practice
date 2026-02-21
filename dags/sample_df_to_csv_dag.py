from __future__ import annotations

from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator

from pipelines.df_to_csv import write_sample_df_to_csv


def _run() -> str:
    return write_sample_df_to_csv("/opt/airflow/logs/sample_df_to_csv/output.csv")


with DAG(
    dag_id="sample_df_to_csv",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
) as dag:
    PythonOperator(
        task_id="write_csv",
        python_callable=_run,
    )
