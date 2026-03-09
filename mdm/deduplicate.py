from __future__ import annotations

import logging
import uuid
from typing import Any

import pandas as pd
from splink import DuckDBAPI, Linker

from mdm.splink_settings import (
    ADDRESS_COLUMN,
    EMAIL_COLUMN,
    FULL_NAME_COLUMN,
    UNIQUE_ID_COLUMN,
    get_splink_settings,
)

logger = logging.getLogger(__name__)

# Lower threshold = more pairs clustered (fewer master records). 0.4 balances recall vs false merges.
DEFAULT_MATCH_PROBABILITY_THRESHOLD = 0.4
U_ESTIMATION_MAX_PAIRS = 100_000


def run_entity_deduplication(
    staging_df: pd.DataFrame,
    match_probability_threshold: float = DEFAULT_MATCH_PROBABILITY_THRESHOLD,
) -> list[dict[str, Any]]:
    """Run Splink deduplication on entity staging and return master records.

    Args:
        staging_df: DataFrame with columns source_record_id, full_name, email, address
            (and optionally source_system, entity_id, phone, created_at).
        match_probability_threshold: Pairs with match_probability >= this
            are clustered as the same entity.

    Returns:
        List of dicts for entity_master: master_entity_id, full_name, email,
        address, source_count.
    """
    if staging_df.empty:
        logger.warning("Staging dataframe is empty; returning no master records.")
        return []

    num_staging = len(staging_df)
    logger.info(
        "Starting entity deduplication: %d staging rows, match_threshold=%.2f",
        num_staging,
        match_probability_threshold,
    )

    settings = get_splink_settings()
    db_api = DuckDBAPI()
    linker = Linker(staging_df, settings, db_api=db_api)
    logger.info("Linker created with DuckDB backend")

    linker.training.estimate_u_using_random_sampling(max_pairs=U_ESTIMATION_MAX_PAIRS)
    logger.info("U probabilities estimated (max_pairs=%d)", U_ESTIMATION_MAX_PAIRS)

    predictions = linker.inference.predict(threshold_match_probability=match_probability_threshold)

    count_df = linker.misc.query_sql(f"SELECT COUNT(*) AS n FROM {predictions.physical_name}")
    num_pairs = int(count_df["n"].iloc[0])
    logger.info("Pairwise predictions generated: %d pairs", num_pairs)

    if num_pairs == 0:
        logger.info(
            "No pairs above threshold; treating each of %d rows as singleton cluster",
            num_staging,
        )
        return _staging_rows_to_master_records(staging_df)

    clusters_sdf = linker.clustering.cluster_pairwise_predictions_at_threshold(
        predictions, threshold_match_probability=match_probability_threshold
    )
    clusters_df = clusters_sdf.as_pandas_dataframe()
    logger.info("Clustering completed: %d cluster assignments", len(clusters_df))

    cluster_id_col = "cluster_id"
    if "cluster_id" not in clusters_df.columns:
        other_cols = [c for c in clusters_df.columns if c != UNIQUE_ID_COLUMN]
        cluster_id_col = other_cols[0] if other_cols else "cluster_id"

    all_ids = staging_df[UNIQUE_ID_COLUMN].drop_duplicates()
    if len(clusters_df) < len(all_ids):
        clustered_ids = set(clusters_df[UNIQUE_ID_COLUMN])
        singleton_ids = all_ids[~all_ids.isin(clustered_ids)]
        num_singletons = len(singleton_ids)
        logger.info("Adding %d singletons not present in clustering result", num_singletons)
        next_id = int(clusters_df[cluster_id_col].max()) + 1
        singletons_df = pd.DataFrame(
            {
                UNIQUE_ID_COLUMN: singleton_ids,
                cluster_id_col: range(next_id, next_id + len(singleton_ids)),
            }
        )
        clusters_df = pd.concat([clusters_df, singletons_df], ignore_index=True)

    master_records: list[dict[str, Any]] = []
    for cluster_id, group in clusters_df.groupby(cluster_id_col, sort=False):
        ids_in_cluster = group[UNIQUE_ID_COLUMN].tolist()
        source_count = len(ids_in_cluster)
        mask = staging_df[UNIQUE_ID_COLUMN].isin(ids_in_cluster)
        rep_row = staging_df.loc[mask].iloc[0]
        master_records.append(
            {
                "master_entity_id": uuid.uuid4(),
                "full_name": rep_row.get(FULL_NAME_COLUMN),
                "email": rep_row.get(EMAIL_COLUMN),
                "address": rep_row.get(ADDRESS_COLUMN),
                "source_count": source_count,
            }
        )

    num_clusters = len(master_records)
    num_merged = sum(1 for r in master_records if r["source_count"] > 1)
    logger.info(
        "Entity deduplication complete: %d master records (%d clusters with multiple sources)",
        num_clusters,
        num_merged,
    )
    return master_records


def _staging_rows_to_master_records(staging_df: pd.DataFrame) -> list[dict[str, Any]]:
    """When there are no pairwise matches, treat each row as its own cluster."""
    logger.info(
        "Building %d master records (one per staging row, no merges)",
        len(staging_df),
    )
    return [
        {
            "master_entity_id": uuid.uuid4(),
            "full_name": getattr(row, FULL_NAME_COLUMN),
            "email": getattr(row, EMAIL_COLUMN),
            "address": getattr(row, ADDRESS_COLUMN),
            "source_count": 1,
        }
        for row in staging_df.itertuples(index=False)
    ]
