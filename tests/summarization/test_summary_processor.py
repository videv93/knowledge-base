"""Tests for the summary processing pipeline."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.common.models import AiSummary, BlogPost, ProcessingResult


def _make_post(post_id=1, title="Test Post", body="Test body", url="https://example.com/post"):
    return BlogPost(
        id=post_id,
        source_id=1,
        title=title,
        body=body,
        url=url,
        publication_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        author_name="Author",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _make_summary(post_id=1):
    return AiSummary(
        id=None,
        post_id=post_id,
        summary_text="A test summary.",
        tags=["python", "testing"],
        difficulty_classification="beginner",
        raw_api_response={"id": "msg_123"},
    )


class TestGetUnsummarizedPosts:
    """Tests for get_unsummarized_posts()."""

    def test_returns_posts_without_summaries(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchall.return_value = [
            (1, 10, "Post 1", "Body 1", "https://example.com/1", None, "Author", None),
            (2, 10, "Post 2", "Body 2", "https://example.com/2", None, "Author", None),
        ]

        from src.summarization.summary_processor import get_unsummarized_posts

        posts = get_unsummarized_posts()
        assert len(posts) == 2
        assert posts[0].id == 1
        assert posts[0].title == "Post 1"
        assert posts[1].id == 2

    def test_returns_empty_when_all_summarized(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchall.return_value = []

        from src.summarization.summary_processor import get_unsummarized_posts

        posts = get_unsummarized_posts()
        assert len(posts) == 0

    def test_executes_left_join_query(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchall.return_value = []

        from src.summarization.summary_processor import get_unsummarized_posts

        get_unsummarized_posts()
        sql = mock_cursor.execute.call_args[0][0]
        assert "LEFT JOIN raw_ai_summaries" in sql
        assert "WHERE ais.id IS NULL" in sql


class TestSummarizePostAndStore:
    """Tests for summarize_post_and_store()."""

    def test_success_stores_summary(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.rowcount = 1

        mock_client = MagicMock()
        mock_client.summarize_post.return_value = _make_summary(post_id=1)

        from src.summarization.summary_processor import summarize_post_and_store

        post = _make_post(post_id=1)
        result = summarize_post_and_store(mock_client, post)

        assert result == "succeeded"
        mock_client.summarize_post.assert_called_once_with(
            title="Test Post", body="Test body", post_id=1
        )
        sql = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO raw_ai_summaries" in sql
        assert "ON CONFLICT (post_id) DO NOTHING" in sql

    def test_failure_routes_to_dlq(self, mock_db_connection):
        mock_client = MagicMock()
        mock_client.summarize_post.side_effect = Exception("API error")

        from src.summarization.summary_processor import summarize_post_and_store

        post = _make_post(post_id=42)

        with patch("src.summarization.summary_processor.route_to_dlq") as mock_dlq:
            result = summarize_post_and_store(mock_client, post)

        assert result == "failed"
        mock_dlq.assert_called_once_with(
            post_reference="42",
            failure_stage="summarization",
            failure_reason="Exception: API error",
        )

    def test_summarization_error_routes_to_dlq(self, mock_db_connection):
        from src.summarization.claude_client import SummarizationError
        mock_client = MagicMock()
        mock_client.summarize_post.side_effect = SummarizationError("bad JSON")

        from src.summarization.summary_processor import summarize_post_and_store

        post = _make_post(post_id=5)

        with patch("src.summarization.summary_processor.route_to_dlq") as mock_dlq:
            result = summarize_post_and_store(mock_client, post)

        assert result == "failed"
        mock_dlq.assert_called_once_with(
            post_reference="5",
            failure_stage="summarization",
            failure_reason="SummarizationError: bad JSON",
        )

    def test_idempotent_on_conflict(self, mock_db_connection):
        """Already-summarized post: ON CONFLICT DO NOTHING, rowcount=0."""
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.rowcount = 0  # conflict — already exists

        mock_client = MagicMock()
        mock_client.summarize_post.return_value = _make_summary(post_id=1)

        from src.summarization.summary_processor import summarize_post_and_store

        result = summarize_post_and_store(mock_client, _make_post(post_id=1))
        assert result == "skipped"


class TestProcessAllUnsummarized:
    """Tests for process_all_unsummarized()."""

    def test_empty_returns_zero_counts(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchall.return_value = []

        from src.summarization.summary_processor import process_all_unsummarized

        with patch("src.summarization.summary_processor.ClaudeClient"):
            result = process_all_unsummarized(max_concurrent=2)

        assert isinstance(result, ProcessingResult)
        assert result.total_found == 0
        assert result.succeeded == 0
        assert result.failed == 0
        assert result.skipped == 0

    def test_processes_all_posts(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchall.return_value = [
            (1, 10, "Post 1", "Body 1", "https://example.com/1", None, "Author", None),
            (2, 10, "Post 2", "Body 2", "https://example.com/2", None, "Author", None),
        ]
        mock_cursor.rowcount = 1

        mock_client_instance = MagicMock()
        mock_client_instance.summarize_post.return_value = _make_summary()

        from src.summarization.summary_processor import process_all_unsummarized

        with patch("src.summarization.summary_processor.ClaudeClient", return_value=mock_client_instance):
            result = process_all_unsummarized(max_concurrent=2)

        assert result.total_found == 2
        assert result.succeeded == 2
        assert result.failed == 0

    def test_failure_isolation(self, mock_db_connection):
        """One post failure shouldn't stop others."""
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchall.return_value = [
            (1, 10, "Good Post", "Body", "https://example.com/1", None, "Author", None),
            (2, 10, "Bad Post", "Body", "https://example.com/2", None, "Author", None),
        ]
        mock_cursor.rowcount = 1

        mock_client_instance = MagicMock()

        def side_effect(title, body, post_id):
            if post_id == 2:
                raise Exception("API failure")
            return _make_summary(post_id=post_id)

        mock_client_instance.summarize_post.side_effect = side_effect

        from src.summarization.summary_processor import process_all_unsummarized

        with patch("src.summarization.summary_processor.ClaudeClient", return_value=mock_client_instance), \
             patch("src.summarization.summary_processor.route_to_dlq"):
            result = process_all_unsummarized(max_concurrent=1)

        assert result.total_found == 2
        assert result.succeeded == 1
        assert result.failed == 1

    def test_uses_config_concurrency(self, mock_db_connection, monkeypatch):
        """Verify process_all_unsummarized passes config concurrency to ThreadPoolExecutor."""
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchall.return_value = [
            (1, 10, "Post", "Body", "https://example.com/1", None, "A", None),
        ]
        mock_cursor.rowcount = 1

        mock_client = MagicMock()
        mock_client.summarize_post.return_value = _make_summary()

        from src.summarization.summary_processor import process_all_unsummarized

        with patch("src.summarization.summary_processor.ClaudeClient", return_value=mock_client), \
             patch("src.summarization.summary_processor.ThreadPoolExecutor") as mock_executor:
            mock_executor.return_value.__enter__ = MagicMock(return_value=mock_executor.return_value)
            mock_executor.return_value.__exit__ = MagicMock(return_value=False)
            mock_executor.return_value.submit.return_value = MagicMock()
            mock_executor.return_value.submit.return_value.result.return_value = "succeeded"
            # as_completed needs to yield the future
            with patch("src.summarization.summary_processor.as_completed",
                       return_value=[mock_executor.return_value.submit.return_value]):
                process_all_unsummarized(max_concurrent=7)

            mock_executor.assert_called_once_with(max_workers=7)

    def test_counts_accurate(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchall.return_value = [
            (1, 10, "Post 1", "B", "https://example.com/1", None, "A", None),
            (2, 10, "Post 2", "B", "https://example.com/2", None, "A", None),
            (3, 10, "Post 3", "B", "https://example.com/3", None, "A", None),
        ]
        mock_cursor.rowcount = 1

        mock_client_instance = MagicMock()
        call_count = 0

        def side_effect(title, body, post_id):
            nonlocal call_count
            call_count += 1
            if post_id == 2:
                raise Exception("fail")
            return _make_summary(post_id=post_id)

        mock_client_instance.summarize_post.side_effect = side_effect

        from src.summarization.summary_processor import process_all_unsummarized

        with patch("src.summarization.summary_processor.ClaudeClient", return_value=mock_client_instance), \
             patch("src.summarization.summary_processor.route_to_dlq"):
            result = process_all_unsummarized(max_concurrent=1)

        assert result.total_found == 3
        assert result.succeeded == 2
        assert result.failed == 1
        assert result.skipped == 0
