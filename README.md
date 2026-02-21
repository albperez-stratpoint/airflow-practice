## Installation 

1. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

2. Create virtual environment and set python version

```bash
uv venv --python 3.12
```

3. Install dependencies

```bash
uv add apache-airflow==2.8.3
```

4. Export requirements to requirements.txt

```bash
uv export --format requirements.txt --output-file requirements.txt
```

5. Get official docker-compose file for Airflow 2.8.3 and optionally set `AIRFLOW__CORE__LOAD_EXAMPLES: 'false'`

```bash
curl -LfO 'https://airflow.apache.org/docs/apache-airflow/2.8.3/docker-compose.yaml'
```

6. Add AIRFLOW_UID to .env file

```bash
echo -e "AIRFLOW_UID=$(id -u)" >> .env
```

7. Start Airflow

```bash
docker compose up -d
```

8. Login to Airflow UI

```bash
http://localhost:8080
```

Default credentials:
- Username: airflow
- Password: airflow

9. Create dags.

## TODO

- [ ] Create dags.
- [ ] Separate logic from dags into `pipelines/` directory. 
- [ ] Make `pipelines/` installable as a package
