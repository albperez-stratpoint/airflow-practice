"""Splink settings for customer deduplication (DuckDB backend)."""

from __future__ import annotations

# Unique row identifier for Splink (order-level id from staging).
UNIQUE_ID_COLUMN = "customer_id"

# Columns used in comparisons (must exist in staging dataframe).
CUSTOMER_UNIQUE_ID_COLUMN = "customer_unique_id"
CITY_COLUMN = "city"
STATE_COLUMN = "state"
ZIP_COLUMN = "zip_code_prefix"

# Number of leading digits of zip used in blocking (reduces comparison space and memory).
# 0 = full zip match (smallest blocks); 2 = first 2 digits; etc.
ZIP_PREFIX_BLOCKING_DIGITS = 0


def _blocking_rule_state_zip() -> str:
    """Blocking rule: state + zip (full zip if ZIP_PREFIX_BLOCKING_DIGITS is 0, else prefix)."""
    if ZIP_PREFIX_BLOCKING_DIGITS <= 0:
        return f"l.{STATE_COLUMN} = r.{STATE_COLUMN} AND l.{ZIP_COLUMN} = r.{ZIP_COLUMN}"
    return (
        f"l.{STATE_COLUMN} = r.{STATE_COLUMN} AND "
        f"substr(l.{ZIP_COLUMN}::VARCHAR, 1, {ZIP_PREFIX_BLOCKING_DIGITS}) = "
        f"substr(r.{ZIP_COLUMN}::VARCHAR, 1, {ZIP_PREFIX_BLOCKING_DIGITS})"
    )


def get_splink_settings() -> dict:
    """Return Splink settings dict for probabilistic customer deduplication.

    Blocking on state reduces comparison space. Comparisons on customer_unique_id,
    city, and state (per instructions). DuckDB SQL dialect.
    """
    return {
        "link_type": "dedupe_only",
        "unique_id_column_name": UNIQUE_ID_COLUMN,
        "sql_dialect": "duckdb",
        "blocking_rules_to_generate_predictions": [
            # Block on state + zip (full or prefix) to keep blocks small (avoids OOM).
            _blocking_rule_state_zip(),
        ],
        "comparisons": [
            {
                "output_column_name": CUSTOMER_UNIQUE_ID_COLUMN,
                "comparison_levels": [
                    {
                        "sql_condition": (
                            f"{CUSTOMER_UNIQUE_ID_COLUMN}_l IS NULL OR "
                            f"{CUSTOMER_UNIQUE_ID_COLUMN}_r IS NULL"
                        ),
                        "label_for_charts": "null",
                        "is_null_level": True,
                    },
                    {
                        "sql_condition": (
                            f"{CUSTOMER_UNIQUE_ID_COLUMN}_l = {CUSTOMER_UNIQUE_ID_COLUMN}_r"
                        ),
                        "label_for_charts": "exact_match",
                        "m_probability": 0.9,
                        "u_probability": 0.01,
                    },
                    {
                        "sql_condition": "ELSE",
                        "label_for_charts": "else",
                        "m_probability": 0.1,
                        "u_probability": 0.99,
                    },
                ],
            },
            {
                "output_column_name": CITY_COLUMN,
                "comparison_levels": [
                    {
                        "sql_condition": f"{CITY_COLUMN}_l IS NULL OR {CITY_COLUMN}_r IS NULL",
                        "label_for_charts": "null",
                        "is_null_level": True,
                    },
                    {
                        "sql_condition": (
                            f"lower(trim({CITY_COLUMN}_l)) = lower(trim({CITY_COLUMN}_r))"
                        ),
                        "label_for_charts": "exact_match",
                        "m_probability": 0.85,
                        "u_probability": 0.1,
                    },
                    {
                        "sql_condition": "ELSE",
                        "label_for_charts": "else",
                        "m_probability": 0.15,
                        "u_probability": 0.9,
                    },
                ],
            },
            {
                "output_column_name": STATE_COLUMN,
                "comparison_levels": [
                    {
                        "sql_condition": f"{STATE_COLUMN}_l IS NULL OR {STATE_COLUMN}_r IS NULL",
                        "label_for_charts": "null",
                        "is_null_level": True,
                    },
                    {
                        "sql_condition": (
                            f"upper(trim({STATE_COLUMN}_l)) = upper(trim({STATE_COLUMN}_r))"
                        ),
                        "label_for_charts": "exact_match",
                        "m_probability": 0.95,
                        "u_probability": 0.05,
                    },
                    {
                        "sql_condition": "ELSE",
                        "label_for_charts": "else",
                        "m_probability": 0.05,
                        "u_probability": 0.95,
                    },
                ],
            },
        ],
    }
