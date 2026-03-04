"""Run Splink deduplication and produce customer master records."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import pandas as pd
from splink import DuckDBAPI, Linker

from mdm.splink_settings import (
    CITY_COLUMN,
    CUSTOMER_UNIQUE_ID_COLUMN,
    STATE_COLUMN,
    ZIP_COLUMN,
    get_splink_settings,
)

logger = logging.getLogger(__name__)

# Match probability threshold for clustering (pairs above this are same entity).
DEFAULT_MATCH_PROBABILITY_THRESHOLD = 0.5


def run_deduplication(
    staging_df: pd.DataFrame,
    match_probability_threshold: float = DEFAULT_MATCH_PROBABILITY_THRESHOLD,
) -> list[dict[str, Any]]:
    """Run Splink deduplication on staging data and return master records.

    Args:
        staging_df: DataFrame with columns customer_id, customer_unique_id,
            zip_code_prefix, city, state (and optionally source_system).
        match_probability_threshold: Pairs with match_probability >= this
            are clustered as the same entity.

    Returns:
        List of dicts suitable for ecommerce_customer_master: master_customer_id,
        customer_unique_id, zip_code_prefix, city, state, source_count.
    """
    if staging_df.empty:
        logger.warning("Staging dataframe is empty; returning no master records.")
        return []

    settings = get_splink_settings()
    db_api = DuckDBAPI()
    linker = Linker(staging_df, settings, db_api=db_api)

    # Optionally improve u probabilities; fixed m/u in settings are used otherwise.
    linker.training.estimate_u_using_random_sampling(max_pairs=500_000)

    predictions = linker.inference.predict(threshold_match_probability=match_probability_threshold)
    predictions_df = predictions.as_pandas_dataframe()

    if predictions_df.empty:
        # No pairs above threshold: every record is its own cluster.
        return _staging_rows_to_master_records(staging_df)

    unique_id_col = settings["unique_id_column_name"]

    # Use linker's clustering method (Splink 4 API).
    clusters_sdf = linker.clustering.cluster_pairwise_predictions_at_threshold(
        predictions, threshold_match_probability=match_probability_threshold
    )
    clusters_df = clusters_sdf.as_pandas_dataframe()

    # Detect cluster id column name (Splink may use different naming).
    cluster_id_col = "cluster_id"
    if "cluster_id" not in clusters_df.columns:
        other_cols = [c for c in clusters_df.columns if c != unique_id_col]
        cluster_id_col = other_cols[0] if other_cols else "cluster_id"

    # Ensure all nodes have a cluster (singletons may be missing from clusters_df).
    all_ids = staging_df[unique_id_col].drop_duplicates()
    if len(clusters_df) < len(all_ids):
        clustered_ids = set(clusters_df[unique_id_col])
        singleton_ids = all_ids[~all_ids.isin(clustered_ids)]
        next_id = int(clusters_df[cluster_id_col].max()) + 1
        singletons_df = pd.DataFrame(
            {
                unique_id_col: singleton_ids,
                cluster_id_col: range(next_id, next_id + len(singleton_ids)),
            }
        )
        clusters_df = pd.concat([clusters_df, singletons_df], ignore_index=True)

    # One master record per cluster: pick representative row, set source_count.
    master_records: list[dict[str, Any]] = []
    for cluster_id, group in clusters_df.groupby(cluster_id_col, sort=False):
        ids_in_cluster = group[unique_id_col].tolist()
        source_count = len(ids_in_cluster)
        # Representative row: first row from staging that belongs to this cluster.
        mask = staging_df[unique_id_col].isin(ids_in_cluster)
        rep_row = staging_df.loc[mask].iloc[0]
        master_records.append(
            {
                "master_customer_id": uuid.uuid4(),
                "customer_unique_id": rep_row.get(CUSTOMER_UNIQUE_ID_COLUMN),
                "zip_code_prefix": rep_row.get(ZIP_COLUMN),
                "city": rep_row.get(CITY_COLUMN),
                "state": rep_row.get(STATE_COLUMN),
                "source_count": source_count,
            }
        )

    return master_records


def _staging_rows_to_master_records(staging_df: pd.DataFrame) -> list[dict[str, Any]]:
    """When there are no pairwise matches, treat each row as its own cluster."""
    return [
        {
            "master_customer_id": uuid.uuid4(),
            "customer_unique_id": getattr(row, CUSTOMER_UNIQUE_ID_COLUMN),
            "zip_code_prefix": getattr(row, ZIP_COLUMN),
            "city": getattr(row, CITY_COLUMN),
            "state": getattr(row, STATE_COLUMN),
            "source_count": 1,
        }
        for row in staging_df.itertuples(index=False)
    ]
