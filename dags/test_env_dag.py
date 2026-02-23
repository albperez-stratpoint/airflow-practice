from __future__ import annotations

from datetime import datetime

from airflow.decorators import task
from airflow.models.dag import DAG
from airflow.models.variable import Variable
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="test_env_dag",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
    tags=["test"],
) as dag:

    @task
    def test_python_callable():
        var = Variable.get("my_dag_var")
        print(f"Variable.get('my_dag_var'): {var}")
        return var

    bash_use_variable_good = BashOperator(
        task_id="bash_use_variable_good",
        bash_command="""
            echo variable my_dag_var={{ ti.xcom_pull(task_ids='test_python_callable') }}
        """,
    )

    test_python_callable() >> bash_use_variable_good
