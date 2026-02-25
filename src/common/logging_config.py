"""Logging configuration for the pipeline.

Call setup_logging() once at application startup.
All modules use: logger = logging.getLogger(__name__)
"""

import logging
import sys

from src.common import config


def setup_logging():
    """Configure root logger to stdout with standard format."""
    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid duplicate handlers on repeated calls
    if not root_logger.handlers:
        root_logger.addHandler(handler)
