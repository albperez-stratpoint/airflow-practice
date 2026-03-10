"""Build golden customer records and crosswalk from Splink clusters (scenario §8 survivorship)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import pandas as pd

from mdm.normalize_raw import (
    ADDRESS_COLUMN,
    CITY_COLUMN,
    COUNTRY_COLUMN,
    EMAIL_COLUMN,
    FULL_NAME_COLUMN,
    PHONE_COLUMN,
    SOURCE_RECORD_ID_COLUMN,
    SOURCE_SYSTEM_COLUMN,
)
from mdm.splink_settings import UNIQUE_ID_COLUMN

logger = logging.getLogger(__name__)

# Survivorship priority (scenario §8).
SOURCE_FOR_EMAIL = "CRM"
SOURCE_FOR_PHONE = "BILLING"

# Output column names (scenario §4 mdm_customers).
GOLDEN_ID_COLUMN = "mdm_customer_id"
GOLDEN_NAME_COLUMN = "golden_name"
GOLDEN_EMAIL_COLUMN = "golden_email"
GOLDEN_PHONE_COLUMN = "golden_phone"
GOLDEN_ADDRESS_COLUMN = "golden_address"
GOLDEN_CITY_COLUMN = "golden_city"
GOLDEN_COUNTRY_COLUMN = "golden_country"


def _completeness(row: pd.Series) -> int:
    """Score for 'most complete' address: length of address + city + country (non-null)."""
    addr = str(row.get(ADDRESS_COLUMN, "") or "").strip()
    city = str(row.get(CITY_COLUMN, "") or "").strip()
    country = str(row.get(COUNTRY_COLUMN, "") or "").strip()
    return len(addr) + len(city) + len(country)


def _pick_golden_name(cluster_rows: pd.DataFrame) -> str | None:
    """Survivorship: choose longest name (scenario §8)."""
    names = cluster_rows[FULL_NAME_COLUMN].dropna().astype(str).str.strip()
    names = names[names != ""]
    if names.empty:
        return None
    return max(names.tolist(), key=len)


def _pick_golden_email(cluster_rows: pd.DataFrame) -> str | None:
    """Survivorship: prioritize CRM (scenario §8)."""
    if SOURCE_SYSTEM_COLUMN not in cluster_rows.columns:
        return (
            cluster_rows[EMAIL_COLUMN].dropna().iloc[0]
            if cluster_rows[EMAIL_COLUMN].notna().any()
            else None
        )
    crm = cluster_rows[
        cluster_rows[SOURCE_SYSTEM_COLUMN].astype(str).str.upper() == SOURCE_FOR_EMAIL
    ]
    if not crm.empty and crm[EMAIL_COLUMN].notna().any():
        val = crm[EMAIL_COLUMN].dropna().iloc[0]
        if str(val).strip():
            return str(val).strip()
    val = cluster_rows[EMAIL_COLUMN].dropna()
    return str(val.iloc[0]).strip() if len(val) else None


def _pick_golden_phone(cluster_rows: pd.DataFrame) -> str | None:
    """Survivorship: prioritize Billing (scenario §8)."""
    if SOURCE_SYSTEM_COLUMN not in cluster_rows.columns:
        return (
            cluster_rows[PHONE_COLUMN].dropna().iloc[0]
            if cluster_rows[PHONE_COLUMN].notna().any()
            else None
        )
    billing = cluster_rows[
        cluster_rows[SOURCE_SYSTEM_COLUMN].astype(str).str.upper() == SOURCE_FOR_PHONE
    ]
    if not billing.empty and billing[PHONE_COLUMN].notna().any():
        val = billing[PHONE_COLUMN].dropna().iloc[0]
        if str(val).strip():
            return str(val).strip()
    val = cluster_rows[PHONE_COLUMN].dropna()
    return str(val.iloc[0]).strip() if len(val) else None


def _pick_golden_address(cluster_rows: pd.DataFrame) -> tuple[str | None, str | None, str | None]:
    """Survivorship: most complete value (address, city, country).
    Returns (address, city, country)."""
    if cluster_rows.empty:
        return (None, None, None)
    idx = cluster_rows.apply(_completeness, axis=1).idxmax()
    row = cluster_rows.loc[idx]
    addr = row.get(ADDRESS_COLUMN)
    city = row.get(CITY_COLUMN)
    country = row.get(COUNTRY_COLUMN)
    if pd.isna(addr) or str(addr).strip() == "":
        addr = None
    else:
        addr = str(addr).strip()
    if pd.isna(city) or str(city).strip() == "":
        city = None
    else:
        city = str(city).strip()
    if pd.isna(country) or str(country).strip() == "":
        country = None
    else:
        country = str(country).strip()
    return (addr, city, country)


def build_golden_records_and_crosswalk(
    staging_df: pd.DataFrame,
    clusters_df: pd.DataFrame,
    cluster_id_column: str = "cluster_id",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """From staging and cluster assignments, build mdm_customers and mdm_customer_crosswalk.

    Survivorship (scenario §8): golden_name = longest name, golden_email = prefer CRM,
    golden_phone = prefer Billing, golden_address/city/country = most complete.

    Returns:
        (customers, crosswalk) where customers have mdm_customer_id, golden_*;
        crosswalk has mdm_customer_id, source_system, source_record_id (unprefixed).
    """
    id_col = UNIQUE_ID_COLUMN
    if id_col not in staging_df.columns:
        id_col = SOURCE_RECORD_ID_COLUMN

    customers: list[dict[str, Any]] = []
    crosswalk: list[dict[str, Any]] = []

    for cluster_id, group in clusters_df.groupby(cluster_id_column, sort=False):
        ids_in_cluster = group[id_col].tolist()
        mask = staging_df[id_col].isin(ids_in_cluster)
        cluster_rows = staging_df.loc[mask]

        mdm_id = f"MDM{uuid.uuid4().hex[:8].upper()}"

        golden_name = _pick_golden_name(cluster_rows)
        golden_email = _pick_golden_email(cluster_rows)
        golden_phone = _pick_golden_phone(cluster_rows)
        golden_address, golden_city, golden_country = _pick_golden_address(cluster_rows)

        customers.append(
            {
                GOLDEN_ID_COLUMN: mdm_id,
                GOLDEN_NAME_COLUMN: golden_name,
                GOLDEN_EMAIL_COLUMN: golden_email,
                GOLDEN_PHONE_COLUMN: golden_phone,
                GOLDEN_ADDRESS_COLUMN: golden_address,
                GOLDEN_CITY_COLUMN: golden_city,
                GOLDEN_COUNTRY_COLUMN: golden_country,
            }
        )

        for _, row in cluster_rows.iterrows():
            source_system = row.get(SOURCE_SYSTEM_COLUMN, "")
            source_record_id = str(row.get(SOURCE_RECORD_ID_COLUMN, ""))
            # Store without prefix for crosswalk
            # (e.g. CRM:CRM00001 -> source_system=CRM, source_record_id=CRM00001)
            if ":" in source_record_id:
                _sys, _id = source_record_id.split(":", 1)
                source_system = _sys
                source_record_id = _id
            crosswalk.append(
                {
                    GOLDEN_ID_COLUMN: mdm_id,
                    "source_system": source_system,
                    "source_record_id": source_record_id,
                }
            )

    logger.info(
        "Built %d golden customers and %d crosswalk rows",
        len(customers),
        len(crosswalk),
    )
    return customers, crosswalk
