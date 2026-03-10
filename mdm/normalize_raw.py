"""Normalize CRM, Billing, and Support raw DataFrames into a single staging table for Splink."""

from __future__ import annotations

import logging
import re

import pandas as pd

from mdm.splink_settings import PHONE_SUFFIX_COLUMN, PHONE_SUFFIX_DIGITS

logger = logging.getLogger(__name__)

# Normalized column names (must match Splink and golden-record expectations).
SOURCE_SYSTEM_COLUMN = "source_system"
SOURCE_RECORD_ID_COLUMN = "source_record_id"
FULL_NAME_COLUMN = "full_name"
EMAIL_COLUMN = "email"
PHONE_COLUMN = "phone"
ADDRESS_COLUMN = "address"
CITY_COLUMN = "city"
COUNTRY_COLUMN = "country"
SOURCE_CREATED_AT_COLUMN = "source_created_at"

SOURCE_CRM = "CRM"
SOURCE_BILLING = "BILLING"
SOURCE_SUPPORT = "SUPPORT"

NORMALIZED_COLUMNS = (
    SOURCE_SYSTEM_COLUMN,
    SOURCE_RECORD_ID_COLUMN,
    FULL_NAME_COLUMN,
    EMAIL_COLUMN,
    PHONE_COLUMN,
    ADDRESS_COLUMN,
    CITY_COLUMN,
    COUNTRY_COLUMN,
    SOURCE_CREATED_AT_COLUMN,
    PHONE_SUFFIX_COLUMN,
)


def _digits_only(value: str | None) -> str:
    """Return digits from string; empty if null or no digits."""
    if value is None or not isinstance(value, str):
        return ""
    return re.sub(r"[^0-9]", "", value)


def _phone_suffix(phone: str | None, num_digits: int = PHONE_SUFFIX_DIGITS) -> str | None:
    """Last num_digits of phone; None if fewer digits."""
    digits = _digits_only(phone)
    if len(digits) < num_digits:
        return None
    return digits[-num_digits:]


def _normalize_crm(df: pd.DataFrame) -> pd.DataFrame:
    """Map crm_contacts schema to normalized staging rows."""
    if df.empty:
        return pd.DataFrame(columns=list(NORMALIZED_COLUMNS))
    full_name = (df["first_name"].fillna("") + " " + df["last_name"].fillna("")).str.strip()
    address = df["address"].fillna("")
    created = pd.to_datetime(df["created_date"], errors="coerce")
    out = pd.DataFrame(
        {
            SOURCE_SYSTEM_COLUMN: SOURCE_CRM,
            SOURCE_RECORD_ID_COLUMN: df["crm_contact_id"].astype(str),
            FULL_NAME_COLUMN: full_name,
            EMAIL_COLUMN: df["email"].fillna("").replace("", None),
            PHONE_COLUMN: df["phone"].fillna("").replace("", None),
            ADDRESS_COLUMN: address,
            CITY_COLUMN: df["city"].fillna("").replace("", None),
            COUNTRY_COLUMN: df["country"].fillna("").replace("", None),
            SOURCE_CREATED_AT_COLUMN: created,
        }
    )
    out[PHONE_SUFFIX_COLUMN] = out[PHONE_COLUMN].apply(_phone_suffix)
    return out


def _normalize_billing(df: pd.DataFrame) -> pd.DataFrame:
    """Map billing_accounts schema to normalized staging rows."""
    if df.empty:
        return pd.DataFrame(columns=list(NORMALIZED_COLUMNS))
    created = pd.to_datetime(df["account_start_date"], errors="coerce")
    out = pd.DataFrame(
        {
            SOURCE_SYSTEM_COLUMN: SOURCE_BILLING,
            SOURCE_RECORD_ID_COLUMN: df["billing_customer_id"].astype(str),
            FULL_NAME_COLUMN: df["account_name"].fillna("").astype(str).str.strip(),
            EMAIL_COLUMN: df["billing_email"].fillna("").replace("", None),
            PHONE_COLUMN: df["phone"].fillna("").replace("", None),
            ADDRESS_COLUMN: df["billing_address"].fillna(""),
            CITY_COLUMN: df["city"].fillna("").replace("", None),
            COUNTRY_COLUMN: df["country"].fillna("").replace("", None),
            SOURCE_CREATED_AT_COLUMN: created,
        }
    )
    out[PHONE_SUFFIX_COLUMN] = out[PHONE_COLUMN].apply(_phone_suffix)
    return out


def _normalize_support(df: pd.DataFrame) -> pd.DataFrame:
    """Map support_users schema to normalized staging rows."""
    if df.empty:
        return pd.DataFrame(columns=list(NORMALIZED_COLUMNS))
    created = pd.to_datetime(df["signup_date"], errors="coerce")
    out = pd.DataFrame(
        {
            SOURCE_SYSTEM_COLUMN: SOURCE_SUPPORT,
            SOURCE_RECORD_ID_COLUMN: df["support_user_id"].astype(str),
            FULL_NAME_COLUMN: df["name"].fillna("").astype(str).str.strip(),
            EMAIL_COLUMN: df["email"].fillna("").replace("", None),
            PHONE_COLUMN: df["phone"].fillna("").replace("", None),
            ADDRESS_COLUMN: "",
            CITY_COLUMN: None,
            COUNTRY_COLUMN: None,
            SOURCE_CREATED_AT_COLUMN: created,
        }
    )
    out[PHONE_SUFFIX_COLUMN] = out[PHONE_COLUMN].apply(_phone_suffix)
    return out


def normalize_raw_to_staging(
    crm_df: pd.DataFrame | None = None,
    billing_df: pd.DataFrame | None = None,
    support_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a single staging DataFrame from CRM, Billing, and Support raw tables.

    Each input DataFrame must have the schema produced by generate_mdm_synthetic.py
    (crm_contacts, billing_accounts, support_users). Returns a DataFrame with
    source_system, source_record_id, full_name, email, phone, address, city, country,
    source_created_at, phone_suffix for Splink and survivorship.
    """
    parts: list[pd.DataFrame] = []
    if crm_df is not None and not crm_df.empty:
        parts.append(_normalize_crm(crm_df))
    if billing_df is not None and not billing_df.empty:
        parts.append(_normalize_billing(billing_df))
    if support_df is not None and not support_df.empty:
        parts.append(_normalize_support(support_df))

    if not parts:
        return pd.DataFrame(columns=list(NORMALIZED_COLUMNS))

    combined = pd.concat(parts, ignore_index=True)
    # Ensure source_record_id is globally unique (prefix by source if needed).
    combined[SOURCE_RECORD_ID_COLUMN] = (
        combined[SOURCE_SYSTEM_COLUMN].str.upper() + ":" + combined[SOURCE_RECORD_ID_COLUMN]
    )
    logger.info(
        "Normalized staging: %d rows (CRM=%d, Billing=%d, Support=%d)",
        len(combined),
        len(parts[0]) if len(parts) > 0 else 0,
        len(parts[1]) if len(parts) > 1 else 0,
        len(parts[2]) if len(parts) > 2 else 0,
    )
    return combined
