"""Shared utilities for MDM pipeline."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Staging column names (Postgres) -> Splink/settings names.
STAGING_TO_SPLINK_COLUMNS = {
    "customer_id": "customer_id",
    "customer_unique_id": "customer_unique_id",
    "zip_code_prefix": "zip_code_prefix",
    "city": "city",
    "state": "state",
}
