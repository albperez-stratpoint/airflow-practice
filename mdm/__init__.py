"""MDM (Master Data Management) module: Splink deduplication and entity master."""

from __future__ import annotations

from mdm.deduplicate import run_entity_deduplication
from mdm.splink_settings import get_splink_settings

__all__ = ["run_entity_deduplication", "get_splink_settings"]
