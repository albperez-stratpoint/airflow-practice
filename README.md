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

5. Get official docker-compose file for Airflow 2.8.3

```bash
curl -LfO 'https://airflow.apache.org/docs/apache-airflow/2.8.3/docker-compose.yaml'
```
