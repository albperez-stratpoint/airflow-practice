"""DAG: Ingest CRM/Billing/Support raw CSVs, run Splink deduplication, write golden records.

Reads from data/raw/{crm,billing,support}/%Y/%m/%Y%m%d.csv (from generate_mdm_synthetic.py),
normalizes to a single staging table, runs Splink with MDM settings, applies survivorship
(scenario §8), and writes dwh.mdm_customers and dwh.mdm_customer_crosswalk.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from airflow.decorators import task
from airflow.models import Variable
from airflow.operators.python import get_current_context
from airflow.providers.postgres.hooks.postgres import PostgresHook

from airflow import DAG
from mdm.deduplicate_mdm import run_mdm_deduplication
from mdm.normalize_raw import normalize_raw_to_staging

logger = logging.getLogger(__name__)

# Sources and paths (must match scripts/generate_mdm_synthetic.py).
MDM_RAW_SOURCES = ("crm", "billing", "support")
DEFAULT_RAW_BASE = "/opt/airflow/data/raw"

# Expected CSV columns per source (order matters for validation).
EXPECTED_CRM_HEADERS = (
    "crm_contact_id",
    "first_name",
    "last_name",
    "email",
    "phone",
    "address",
    "city",
    "country",
    "created_date",
)
EXPECTED_BILLING_HEADERS = (
    "billing_customer_id",
    "account_name",
    "billing_email",
    "phone",
    "billing_address",
    "city",
    "country",
    "plan_type",
    "account_start_date",
)
EXPECTED_SUPPORT_HEADERS = (
    "support_user_id",
    "name",
    "email",
    "phone",
    "signup_date",
)

MDM_CUSTOMERS_TABLE = "dwh.mdm_customers"
MDM_CROSSWALK_TABLE = "dwh.mdm_customer_crosswalk"


def _raw_base_path() -> Path:
    base = Variable.get("raw_data_base_path", default_var=DEFAULT_RAW_BASE)
    return Path(base)


def _partition_path(base: Path, source: str, logical_date: datetime) -> Path:
    y = logical_date.strftime("%Y")
    m = logical_date.strftime("%m")
    d = logical_date.strftime("%Y%m%d")
    return base / source / y / m / f"{d}.csv"


@task
def validate_mdm_raw_headers() -> str:
    """Ensure each source has a CSV for the logical date with expected headers
    (generate_mdm_synthetic.py)."""
    context = get_current_context()
    logical_date = context["logical_date"]
    base = _raw_base_path()

    expected = {
        "crm": ",".join(EXPECTED_CRM_HEADERS),
        "billing": ",".join(EXPECTED_BILLING_HEADERS),
        "support": ",".join(EXPECTED_SUPPORT_HEADERS),
    }
    errors: list[str] = []
    for source in MDM_RAW_SOURCES:
        path = _partition_path(base, source, logical_date)
        if not path.exists():
            errors.append(f"Missing: {path}")
            continue
        with path.open(encoding="utf-8") as f:
            first_line = f.readline().strip()
        if first_line != expected[source]:
            errors.append(
                f"{source}: header mismatch at {path}. "
                f"Expected: {expected[source]!r}, got: {first_line!r}"
            )
    if errors:
        raise ValueError("MDM raw header validation failed:\n" + "\n".join(errors))
    logger.info(
        "MDM headers validated for %s at %s",
        ", ".join(MDM_RAW_SOURCES),
        logical_date.strftime("%Y-%m-%d"),
    )
    return f"Validated {len(MDM_RAW_SOURCES)} sources"


@task
def create_mdm_tables() -> str:
    """Create dwh.mdm_customers and dwh.mdm_customer_crosswalk if not exist."""
    hook = PostgresHook(postgres_conn_id="postgres_dwh")
    hook.run("CREATE SCHEMA IF NOT EXISTS dwh")

    hook.run(f"""
    CREATE TABLE IF NOT EXISTS {MDM_CUSTOMERS_TABLE} (
        mdm_customer_id TEXT PRIMARY KEY,
        golden_name TEXT,
        golden_email TEXT,
        golden_phone TEXT,
        golden_address TEXT,
        golden_city TEXT,
        golden_country TEXT
    )
    """)
    hook.run(f"""
    CREATE TABLE IF NOT EXISTS {MDM_CROSSWALK_TABLE} (
        mdm_customer_id TEXT NOT NULL,
        source_system TEXT NOT NULL,
        source_record_id TEXT NOT NULL,
        PRIMARY KEY (source_system, source_record_id)
    )
    """)
    logger.info("Tables %s and %s ready", MDM_CUSTOMERS_TABLE, MDM_CROSSWALK_TABLE)
    return f"Created {MDM_CUSTOMERS_TABLE}, {MDM_CROSSWALK_TABLE}"


@task
def load_raw_normalize_and_deduplicate() -> str:
    """Load CRM/Billing/Support CSVs, normalize, run Splink, persist golden records."""
    context = get_current_context()
    logical_date = context["logical_date"]
    base = _raw_base_path()

    crm_path = _partition_path(base, "crm", logical_date)
    billing_path = _partition_path(base, "billing", logical_date)
    support_path = _partition_path(base, "support", logical_date)

    crm_df = pd.read_csv(crm_path, dtype=str, keep_default_na=True)
    billing_df = pd.read_csv(billing_path, dtype=str, keep_default_na=True)
    support_df = pd.read_csv(support_path, dtype=str, keep_default_na=True)
    staging_df = normalize_raw_to_staging(
        crm_df=crm_df,
        billing_df=billing_df,
        support_df=support_df,
    )

    if staging_df.empty:
        logger.warning("Normalized staging is empty; nothing to deduplicate.")
        return "No staging data"

    customers, crosswalk = run_mdm_deduplication(staging_df)

    hook = PostgresHook(postgres_conn_id="postgres_dwh")
    conn = hook.get_conn()
    cursor = conn.cursor()

    cursor.execute(f"TRUNCATE TABLE {MDM_CUSTOMERS_TABLE}")
    cursor.execute(f"TRUNCATE TABLE {MDM_CROSSWALK_TABLE}")

    for rec in customers:
        cursor.execute(
            f"""
            INSERT INTO {MDM_CUSTOMERS_TABLE}
                (mdm_customer_id, golden_name, golden_email, golden_phone,
                 golden_address, golden_city, golden_country)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                rec["mdm_customer_id"],
                rec.get("golden_name"),
                rec.get("golden_email"),
                rec.get("golden_phone"),
                rec.get("golden_address"),
                rec.get("golden_city"),
                rec.get("golden_country"),
            ),
        )
    for rec in crosswalk:
        cursor.execute(
            f"""
            INSERT INTO {MDM_CROSSWALK_TABLE}
                (mdm_customer_id, source_system, source_record_id)
            VALUES (%s, %s, %s)
            """,
            (
                rec["mdm_customer_id"],
                rec["source_system"],
                rec["source_record_id"],
            ),
        )
    conn.commit()
    cursor.close()
    conn.close()

    logger.info(
        "Persisted %d golden customers and %d crosswalk rows",
        len(customers),
        len(crosswalk),
    )
    return f"Persisted {len(customers)} customers, {len(crosswalk)} crosswalk rows"


with DAG(
    dag_id="mdm_golden_records",
    start_date=datetime(2024, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["mdm", "splink", "golden-record", "deduplication"],
) as dag:
    (validate_mdm_raw_headers() >> create_mdm_tables() >> load_raw_normalize_and_deduplicate())
