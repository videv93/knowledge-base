"""Tests for src.common.retry module."""

from unittest.mock import patch

import pytest

from src.common.retry import retry_with_backoff


def test_retry_succeeds_on_first_attempt():
    """Function succeeds on first attempt, no retries needed."""
    call_count = 0

    @retry_with_backoff(max_retries=3, base_delay=0)
    def succeed():
        nonlocal call_count
        call_count += 1
        return "ok"

    result = succeed()
    assert result == "ok"
    assert call_count == 1


def test_retry_succeeds_after_failures():
    """Function succeeds after transient failures."""
    call_count = 0

    @retry_with_backoff(max_retries=3, base_delay=0)
    def fail_then_succeed():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("transient failure")
        return "recovered"

    result = fail_then_succeed()
    assert result == "recovered"
    assert call_count == 3


def test_retry_exhausted_raises():
    """Function raises after all retries exhausted."""

    @retry_with_backoff(max_retries=2, base_delay=0)
    def always_fail():
        raise ValueError("permanent failure")

    with pytest.raises(ValueError, match="permanent failure"):
        always_fail()


def test_retry_only_catches_specified_exceptions():
    """Retry only catches specified exception types."""

    @retry_with_backoff(max_retries=3, base_delay=0, exceptions=(ConnectionError,))
    def raise_type_error():
        raise TypeError("not retryable")

    with pytest.raises(TypeError, match="not retryable"):
        raise_type_error()


@patch("src.common.retry.time.sleep")
def test_retry_backoff_delays(mock_sleep):
    """Retry uses exponential backoff delays: base * 4^attempt."""
    call_count = 0

    @retry_with_backoff(max_retries=3, base_delay=30)
    def fail_twice():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise ConnectionError("fail")
        return "ok"

    fail_twice()
    # First retry: 30 * 4^0 = 30s, Second retry: 30 * 4^1 = 120s
    assert mock_sleep.call_count == 2
    assert mock_sleep.call_args_list[0][0][0] == 30
    assert mock_sleep.call_args_list[1][0][0] == 120
