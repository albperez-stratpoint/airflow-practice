"""Run Splink deduplication on MDM normalized staging and produce golden records + crosswalk."""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

import pandas as pd
from splink import DuckDBAPI, Linker

from mdm.golden_record import build_golden_records_and_crosswalk
from mdm.splink_settings import (
    UNIQUE_ID_COLUMN,
    get_splink_settings_mdm,
)

logger = logging.getLogger(__name__)

DEFAULT_MATCH_PROBABILITY_THRESHOLD = 0.4
U_ESTIMATION_MAX_PAIRS = 50_000


def run_mdm_deduplication(
    staging_df: pd.DataFrame,
    match_probability_threshold: float = DEFAULT_MATCH_PROBABILITY_THRESHOLD,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run Splink on MDM staging; return (mdm_customers, mdm_customer_crosswalk).

    Expects staging_df with columns: source_record_id (or source_system + source_record_id
    combined as unique id), source_system, full_name, email, phone, address, city, country,
    source_created_at, phone_suffix.

    Returns:
        (customers, crosswalk) for dwh.mdm_customers and dwh.mdm_customer_crosswalk.
    """
    if staging_df.empty:
        logger.warning("MDM staging is empty; returning empty customers and crosswalk.")
        return [], []

    # Splink expects unique_id_column_name; we use source_record_id (already globally unique).
    num_staging = len(staging_df)
    logger.info(
        "Starting MDM deduplication: %d staging rows, match_threshold=%.2f",
        num_staging,
        match_probability_threshold,
    )

    settings = get_splink_settings_mdm()
    db_api = DuckDBAPI()
    linker = Linker(staging_df, settings, db_api=db_api)
    logger.info("Linker created with DuckDB backend (MDM settings)")

    linker.training.estimate_u_using_random_sampling(max_pairs=U_ESTIMATION_MAX_PAIRS)
    logger.info("U probabilities estimated (max_pairs=%d)", U_ESTIMATION_MAX_PAIRS)

    predictions = linker.inference.predict(threshold_match_probability=match_probability_threshold)
    count_df = linker.misc.query_sql(f"SELECT COUNT(*) AS n FROM {predictions.physical_name}")
    num_pairs = int(count_df["n"].iloc[0])
    logger.info("Pairwise predictions generated: %d pairs", num_pairs)

    cluster_id_col = "cluster_id"
    if num_pairs == 0:
        logger.info(
            "No pairs above threshold; treating each of %d rows as singleton cluster",
            num_staging,
        )
        clusters_df = staging_df[[UNIQUE_ID_COLUMN]].copy()
        clusters_df[cluster_id_col] = range(num_staging)
    else:
        clusters_sdf = linker.clustering.cluster_pairwise_predictions_at_threshold(
            predictions, threshold_match_probability=match_probability_threshold
        )
        clusters_df = clusters_sdf.as_pandas_dataframe()
        if "cluster_id" not in clusters_df.columns:
            other_cols = [c for c in clusters_df.columns if c != UNIQUE_ID_COLUMN]
            cluster_id_col = other_cols[0] if other_cols else "cluster_id"
        logger.info("Clustering completed: %d cluster assignments", len(clusters_df))

        all_ids = staging_df[UNIQUE_ID_COLUMN].drop_duplicates()
        if len(clusters_df) < len(all_ids):
            clustered_ids = set(clusters_df[UNIQUE_ID_COLUMN])
            singleton_ids = all_ids[~all_ids.isin(clustered_ids)]
            num_singletons = len(singleton_ids)
            logger.info("Adding %d singletons not in clustering result", num_singletons)
            next_id = int(clusters_df[cluster_id_col].max()) + 1
            singletons_df = pd.DataFrame(
                {
                    UNIQUE_ID_COLUMN: singleton_ids,
                    cluster_id_col: range(next_id, next_id + len(singleton_ids)),
                }
            )
            clusters_df = pd.concat([clusters_df, singletons_df], ignore_index=True)

    customers, crosswalk = build_golden_records_and_crosswalk(
        staging_df, clusters_df, cluster_id_column=cluster_id_col
    )
    cw_counts = Counter(cw["mdm_customer_id"] for cw in crosswalk)
    num_merged = sum(1 for _, count in cw_counts.items() if count > 1)
    logger.info(
        "MDM deduplication complete: %d golden customers (%d with multiple source records)",
        len(customers),
        num_merged,
    )
    return customers, crosswalk
