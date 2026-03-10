"""MDM (Master Data Management) module: Splink deduplication and golden records."""

from __future__ import annotations

from mdm.deduplicate_mdm import run_mdm_deduplication
from mdm.splink_settings import get_splink_settings_mdm

__all__ = ["run_mdm_deduplication", "get_splink_settings_mdm"]
