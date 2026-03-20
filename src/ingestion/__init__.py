"""Ingestion package: RSS parsing, post ingestion, and source loading."""

from src.ingestion.pipeline import run_ingestion
from src.ingestion.source_loader import get_active_sources
from src.ingestion.source_manager import (
    activate_source,
    add_source,
    deactivate_source,
    get_source_by_id,
    get_source_health,
    update_source,
)

__all__ = [
    "run_ingestion",
    "get_active_sources",
    "add_source",
    "deactivate_source",
    "activate_source",
    "update_source",
    "get_source_by_id",
    "get_source_health",
]
