from __future__ import annotations

# Unique row identifier for Splink (source_record_id is globally unique across sources).
UNIQUE_ID_COLUMN = "source_record_id"

# Columns used in comparisons (must exist in staging dataframe).
FULL_NAME_COLUMN = "full_name"
EMAIL_COLUMN = "email"
ADDRESS_COLUMN = "address"
PHONE_COLUMN = "phone"

# Optional: last N digits of phone for blocking (set on normalized staging before Splink).
PHONE_SUFFIX_COLUMN = "phone_suffix"

# Blocking: first N chars to reduce comparison space (avoids OOM).
EMAIL_PREFIX_BLOCKING_CHARS = 3  # Wider = more pairs compared (catches more noisy dupes).
NAME_PREFIX_BLOCKING_CHARS = 3
# Address prefix: so records with same/similar address get compared even when name/email differ.
ADDRESS_PREFIX_BLOCKING_CHARS = 12
# Last N digits of phone for blocking (normalize to digits in staging).
PHONE_SUFFIX_DIGITS = 7

# Jaro-Winkler similarity threshold for "likely same entity" (handles typos from generate.py).
JARO_WINKLER_THRESHOLD = 0.82


def _blocking_rule_email_prefix(chars: int | None = None) -> str:
    """Block on first N chars of email so records with similar email prefix are compared."""
    n = chars if chars is not None else EMAIL_PREFIX_BLOCKING_CHARS
    return (
        f"substr(lower(trim(l.{EMAIL_COLUMN})), 1, {n}) = "
        f"substr(lower(trim(r.{EMAIL_COLUMN})), 1, {n})"
    )


def _blocking_rule_name_prefix(chars: int | None = None) -> str:
    """Block on first N chars of name to compare pairs that share name prefix
    (e.g. same first letter)."""
    n = chars if chars is not None else NAME_PREFIX_BLOCKING_CHARS
    return (
        f"substr(lower(trim(l.{FULL_NAME_COLUMN})), 1, {n}) = "
        f"substr(lower(trim(r.{FULL_NAME_COLUMN})), 1, {n})"
    )


def _blocking_rule_address_prefix(chars: int | None = None) -> str:
    """Block on first N chars of address so same-address records are compared
    (catches AAmanda vs Amanda)."""
    n = chars if chars is not None else ADDRESS_PREFIX_BLOCKING_CHARS
    return (
        f"substr(lower(trim(l.{ADDRESS_COLUMN})), 1, {n}) = "
        f"substr(lower(trim(r.{ADDRESS_COLUMN})), 1, {n})"
    )


def _blocking_rule_phone_suffix() -> str:
    """Block on last N digits of phone (phone_suffix column set in staging)."""
    return (
        f"l.{PHONE_SUFFIX_COLUMN} = r.{PHONE_SUFFIX_COLUMN} AND "
        f"l.{PHONE_SUFFIX_COLUMN} IS NOT NULL AND l.{PHONE_SUFFIX_COLUMN} != ''"
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


def _comparison_phone() -> dict:
    """Comparison levels for phone: null, exact, fuzzy (Jaro-Winkler), else."""
    return {
        "output_column_name": PHONE_COLUMN,
        "comparison_levels": [
            {
                "sql_condition": f"{PHONE_COLUMN}_l IS NULL OR {PHONE_COLUMN}_r IS NULL",
                "label_for_charts": "null",
                "is_null_level": True,
            },
            {
                "sql_condition": (f"lower(trim({PHONE_COLUMN}_l)) = lower(trim({PHONE_COLUMN}_r))"),
                "label_for_charts": "exact_match",
                "m_probability": 0.92,
                "u_probability": 0.03,
            },
            {
                "sql_condition": _jaro_winkler_condition(PHONE_COLUMN),
                "label_for_charts": "jaro_winkler_match",
                "m_probability": 0.75,
                "u_probability": 0.08,
            },
            {
                "sql_condition": "ELSE",
                "label_for_charts": "else",
                "m_probability": 0.05,
                "u_probability": 0.95,
            },
        ],
    }


def get_splink_settings() -> dict:
    """Return Splink settings for entity deduplication (full_name, email, address).

    Blocking on email prefix, name prefix, and address prefix so same-address
    records (e.g. AAmanda vs Amanda) are compared. Comparisons: exact, Jaro-Winkler
    fuzzy (typos), else. DuckDB SQL dialect.
    """
    return {
        "link_type": "dedupe_only",
        "unique_id_column_name": UNIQUE_ID_COLUMN,
        "sql_dialect": "duckdb",
        "blocking_rules_to_generate_predictions": [
            _blocking_rule_email_prefix(),
            _blocking_rule_name_prefix(),
            _blocking_rule_address_prefix(),
        ],
        "comparisons": [
            _comparison_full_name(),
            _comparison_email(),
            _comparison_address(),
        ],
    }


# Stricter blocking for MDM (60k+ rows): longer prefixes to reduce candidate pairs and avoid OOM.
MDM_EMAIL_PREFIX_CHARS = 8
MDM_NAME_PREFIX_CHARS = 5
MDM_ADDRESS_PREFIX_CHARS = 18


def get_splink_settings_mdm() -> dict:
    """Return Splink settings for MDM pipeline (full_name, email, phone, address).

    Same as get_splink_settings but adds phone comparison and phone_suffix blocking.
    Expects staging to have phone_suffix column (last N digits of phone).
    Uses only email (8-char prefix) + phone_suffix blocking to minimise candidate
    pairs and avoid OOM; name/address are still compared within blocks.
    """
    return {
        "link_type": "dedupe_only",
        "unique_id_column_name": UNIQUE_ID_COLUMN,
        "sql_dialect": "duckdb",
        "blocking_rules_to_generate_predictions": [
            _blocking_rule_email_prefix(MDM_EMAIL_PREFIX_CHARS),
            _blocking_rule_phone_suffix(),
        ],
        "comparisons": [
            _comparison_full_name(),
            _comparison_email(),
            _comparison_phone(),
            _comparison_address(),
        ],
    }
