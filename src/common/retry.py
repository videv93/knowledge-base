"""Retry/backoff utilities for external API calls.

Provides exponential backoff matching Airflow retry policy: 30s, 120s, 480s.
"""

import logging
import time
from functools import wraps

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 30  # seconds


def retry_with_backoff(max_retries=DEFAULT_MAX_RETRIES, base_delay=DEFAULT_BASE_DELAY, exceptions=(Exception,)):
    """Decorator that retries a function with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts.
        base_delay: Base delay in seconds. Multiplied by 4^attempt (30, 120, 480).
        exceptions: Tuple of exception types to catch and retry on.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = base_delay * (4**attempt)
                        logger.warning(
                            "Retry %d/%d for %s after %ds: %s",
                            attempt + 1,
                            max_retries,
                            func.__name__,
                            delay,
                            str(e),
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            "All %d retries exhausted for %s: %s",
                            max_retries,
                            func.__name__,
                            str(e),
                        )
            raise last_exception

        return wrapper

    return decorator
