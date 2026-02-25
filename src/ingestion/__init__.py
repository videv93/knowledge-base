"""Ingestion package: RSS parsing, post ingestion, and source loading."""

from src.ingestion.pipeline import run_ingestion
from src.ingestion.source_loader import get_active_sources

__all__ = ["run_ingestion", "get_active_sources"]
