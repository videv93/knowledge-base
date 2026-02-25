"""Tests for src.common.logging_config module."""

import importlib
import logging


def test_setup_logging_configures_root_logger():
    """setup_logging() adds a stdout handler to the root logger."""
    root = logging.getLogger()
    root.handlers.clear()

    import src.common.config as config

    importlib.reload(config)

    from src.common import logging_config

    importlib.reload(logging_config)
    logging_config.setup_logging()

    assert len(root.handlers) == 1
    assert root.level == logging.DEBUG  # LOG_LEVEL=DEBUG from conftest


def test_setup_logging_idempotent():
    """Calling setup_logging() twice does not add duplicate handlers."""
    root = logging.getLogger()
    root.handlers.clear()

    import src.common.config as config

    importlib.reload(config)

    from src.common import logging_config

    importlib.reload(logging_config)
    logging_config.setup_logging()
    logging_config.setup_logging()

    assert len(root.handlers) == 1
