"""Splink settings for entity deduplication (full_name, email, address) with DuckDB backend."""

from __future__ import annotations

# Unique row identifier for Splink (source_record_id is globally unique across sources).
UNIQUE_ID_COLUMN = "source_record_id"

# Columns used in comparisons (must exist in staging dataframe).
FULL_NAME_COLUMN = "full_name"
EMAIL_COLUMN = "email"
ADDRESS_COLUMN = "address"

# Blocking: first N chars to reduce comparison space (avoids OOM).
EMAIL_PREFIX_BLOCKING_CHARS = 2  # Wider = more pairs compared (catches more noisy dupes).
NAME_PREFIX_BLOCKING_CHARS = 2

# Jaro-Winkler similarity threshold for "likely same entity" (handles typos from generate.py).
JARO_WINKLER_THRESHOLD = 0.82


def _blocking_rule_email_prefix() -> str:
    """Block on first N chars of email so records with similar email prefix are compared."""
    return (
        f"substr(lower(trim(l.{EMAIL_COLUMN})), 1, {EMAIL_PREFIX_BLOCKING_CHARS}) = "
        f"substr(lower(trim(r.{EMAIL_COLUMN})), 1, {EMAIL_PREFIX_BLOCKING_CHARS})"
    )


def _blocking_rule_name_prefix() -> str:
    """Block on first N chars of name to compare pairs that share name prefix (e.g. same first letter)."""
    return (
        f"substr(lower(trim(l.{FULL_NAME_COLUMN})), 1, {NAME_PREFIX_BLOCKING_CHARS}) = "
        f"substr(lower(trim(r.{FULL_NAME_COLUMN})), 1, {NAME_PREFIX_BLOCKING_CHARS})"
    )


def _jaro_winkler_condition(column: str, threshold: float = JARO_WINKLER_THRESHOLD) -> str:
    """DuckDB: true when Jaro-Winkler similarity of trimmed lowercased values >= threshold."""
    return (
        f"jaro_winkler_similarity(lower(trim({column}_l)), lower(trim({column}_r))) >= {threshold}"
    )


def _comparison_full_name() -> dict:
    """Comparison levels for full_name: null, exact, fuzzy (Jaro-Winkler), else."""
    return {
        "output_column_name": FULL_NAME_COLUMN,
        "comparison_levels": [
            {
                "sql_condition": (f"{FULL_NAME_COLUMN}_l IS NULL OR {FULL_NAME_COLUMN}_r IS NULL"),
                "label_for_charts": "null",
                "is_null_level": True,
            },
            {
                "sql_condition": (
                    f"lower(trim({FULL_NAME_COLUMN}_l)) = lower(trim({FULL_NAME_COLUMN}_r))"
                ),
                "label_for_charts": "exact_match",
                "m_probability": 0.9,
                "u_probability": 0.08,
            },
            {
                "sql_condition": _jaro_winkler_condition(FULL_NAME_COLUMN),
                "label_for_charts": "jaro_winkler_match",
                "m_probability": 0.75,
                "u_probability": 0.12,
            },
            {
                "sql_condition": "ELSE",
                "label_for_charts": "else",
                "m_probability": 0.1,
                "u_probability": 0.9,
            },
        ],
    }


def _comparison_email() -> dict:
    """Comparison levels for email: null, exact, fuzzy (Jaro-Winkler), else."""
    return {
        "output_column_name": EMAIL_COLUMN,
        "comparison_levels": [
            {
                "sql_condition": f"{EMAIL_COLUMN}_l IS NULL OR {EMAIL_COLUMN}_r IS NULL",
                "label_for_charts": "null",
                "is_null_level": True,
            },
            {
                "sql_condition": (f"lower(trim({EMAIL_COLUMN}_l)) = lower(trim({EMAIL_COLUMN}_r))"),
                "label_for_charts": "exact_match",
                "m_probability": 0.95,
                "u_probability": 0.02,
            },
            {
                "sql_condition": _jaro_winkler_condition(EMAIL_COLUMN),
                "label_for_charts": "jaro_winkler_match",
                "m_probability": 0.8,
                "u_probability": 0.05,
            },
            {
                "sql_condition": "ELSE",
                "label_for_charts": "else",
                "m_probability": 0.05,
                "u_probability": 0.98,
            },
        ],
    }


def _comparison_address() -> dict:
    """Comparison levels for address: null, exact, fuzzy (Jaro-Winkler), else."""
    return {
        "output_column_name": ADDRESS_COLUMN,
        "comparison_levels": [
            {
                "sql_condition": (f"{ADDRESS_COLUMN}_l IS NULL OR {ADDRESS_COLUMN}_r IS NULL"),
                "label_for_charts": "null",
                "is_null_level": True,
            },
            {
                "sql_condition": (
                    f"lower(trim({ADDRESS_COLUMN}_l)) = lower(trim({ADDRESS_COLUMN}_r))"
                ),
                "label_for_charts": "exact_match",
                "m_probability": 0.85,
                "u_probability": 0.12,
            },
            {
                "sql_condition": _jaro_winkler_condition(ADDRESS_COLUMN),
                "label_for_charts": "jaro_winkler_match",
                "m_probability": 0.7,
                "u_probability": 0.18,
            },
            {
                "sql_condition": "ELSE",
                "label_for_charts": "else",
                "m_probability": 0.15,
                "u_probability": 0.85,
            },
        ],
    }


def get_splink_settings() -> dict:
    """Return Splink settings for entity deduplication (full_name, email, address).

    Blocking on email prefix and name prefix. Comparisons: exact, Jaro-Winkler
    fuzzy (typos), else. DuckDB SQL dialect.
    """
    return {
        "link_type": "dedupe_only",
        "unique_id_column_name": UNIQUE_ID_COLUMN,
        "sql_dialect": "duckdb",
        "blocking_rules_to_generate_predictions": [
            _blocking_rule_email_prefix(),
            _blocking_rule_name_prefix(),
        ],
        "comparisons": [
            _comparison_full_name(),
            _comparison_email(),
            _comparison_address(),
        ],
    }
