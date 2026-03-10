COMPOSE := --env-file .env -f local/docker-compose.yaml

lint:
	uv run ruff check --select I --fix .
	uv run ruff format .
	uv run ruff check . --fix

# Local Airflow stack (run from project root)
up:
	docker compose $(COMPOSE) up -d
down:
	docker compose $(COMPOSE) down
build:
	docker compose $(COMPOSE) build
logs:
	docker compose $(COMPOSE) logs -f
ps:
	docker compose $(COMPOSE) ps

# Backfill
backfill:
	docker compose $(COMPOSE) exec airflow-scheduler airflow dags backfill mdm_golden_records -s 2025-01-01 -e 2025-01-01

# Postgres

psql:
	docker compose $(COMPOSE) exec postgres psql -U dwh_user -d dwh

setup-dwh:
	bash scripts/setup_dwh.sh