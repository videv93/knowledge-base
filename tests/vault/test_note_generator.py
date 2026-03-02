"""Tests for vault note generator — slug generation, file writing, and orchestration."""

import re
from unittest.mock import patch

import pytest

from src.vault.note_generator import (
    _build_sources_by_author,
    _group_posts_by,
    _write_note,
    generate_all,
    generate_author_notes,
    generate_post_notes,
    generate_source_notes,
    slugify_title,
    slugify_with_hash,
)

# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_post():
    return {
        "id": 1,
        "source_id": 10,
        "source_name": "Martin Kleppmann's Blog",
        "category": "Data Engineering",
        "title": "Building Real-Time Pipelines with Kafka",
        "url": "https://example.com/kafka-pipelines",
        "author_name": "Martin Kleppmann",
        "author_id": 100,
        "publication_date": "2026-02-15",
        "summary_text": "A deep dive into Kafka streaming patterns.",
        "tags": ["kafka", "streaming", "data-engineering"],
        "difficulty_classification": "intermediate",
    }


@pytest.fixture
def sample_post_no_author():
    return {
        "id": 2,
        "source_id": 10,
        "source_name": "Tech Blog",
        "category": "DevOps & SRE",
        "title": "Kubernetes Observability Patterns",
        "url": "https://example.com/k8s-obs",
        "author_name": None,
        "author_id": None,
        "publication_date": "2026-02-10",
        "summary_text": None,
        "tags": [],
        "difficulty_classification": None,
    }


@pytest.fixture
def sample_source():
    return {
        "id": 10,
        "name": "Martin Kleppmann's Blog",
        "category": "Data Engineering",
        "feed_url": "https://example.com/rss",
        "status": "active",
        "last_checked_at": "2026-02-20",
        "total_post_count": 42,
        "latest_post_date": "2026-02-15",
    }


@pytest.fixture
def sample_author():
    return {
        "author_id": 100,
        "author_name": "Martin Kleppmann",
        "post_count": 5,
        "source_ids": [10],
        "first_seen_at": "2025-01-01",
        "last_seen_at": "2026-02-15",
        "primary_category": "Data Engineering",
    }


# ---------------------------------------------------------------------------
# slugify_title tests
# ---------------------------------------------------------------------------

class TestSlugifyTitle:
    def test_normal_title(self):
        assert slugify_title("Building Real-Time Pipelines with Kafka") == "building-real-time-pipelines-with-kafka"

    def test_unicode_title(self):
        result = slugify_title("Über die Architektur")
        assert result == "uber-die-architektur"

    def test_long_title_truncated(self):
        long_title = "A" * 200 + " Very Long Title That Should Be Truncated"
        result = slugify_title(long_title)
        assert len(result) <= 80

    def test_empty_title(self):
        assert slugify_title("") == "untitled"

    def test_special_characters(self):
        result = slugify_title("C++ vs Rust: A Developer's Guide!!!")
        assert re.match(r"^[a-z0-9-]+$", result)

    def test_deterministic(self):
        title = "Same Title Twice"
        assert slugify_title(title) == slugify_title(title)


class TestSlugifyWithHash:
    def test_has_hash_suffix(self):
        result = slugify_with_hash("Some Title")
        parts = result.rsplit("-", 1)
        assert len(parts) == 2
        assert len(parts[1]) == 6
        assert re.match(r"^[a-f0-9]{6}$", parts[1])

    def test_deterministic(self):
        assert slugify_with_hash("Same Title") == slugify_with_hash("Same Title")

    def test_different_titles_different_hashes(self):
        assert slugify_with_hash("Title A") != slugify_with_hash("Title B")

    def test_empty_title(self):
        result = slugify_with_hash("")
        # Should be just the hash since base slug is empty
        assert re.match(r"^[a-f0-9]{6}$", result)


# ---------------------------------------------------------------------------
# _write_note tests
# ---------------------------------------------------------------------------

class TestWriteNote:
    def test_creates_file(self, tmp_path):
        path = tmp_path / "notes" / "test.md"
        _write_note(path, "# Hello")
        assert path.read_text() == "# Hello"

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "dir" / "note.md"
        _write_note(path, "content")
        assert path.exists()

    def test_overwrites_existing(self, tmp_path):
        path = tmp_path / "note.md"
        _write_note(path, "v1")
        _write_note(path, "v2")
        assert path.read_text() == "v2"


# ---------------------------------------------------------------------------
# generate_post_notes tests
# ---------------------------------------------------------------------------

class TestGeneratePostNotes:
    def test_creates_correct_structure(self, tmp_path, sample_post):
        paths = generate_post_notes([sample_post], tmp_path)
        assert len(paths) == 1
        # Check path structure: posts/{category-slug}/{post-slug}.md
        rel = paths[0].relative_to(tmp_path)
        parts = rel.parts
        assert parts[0] == "posts"
        assert parts[1] == "data-engineering"
        assert parts[2].endswith(".md")

    def test_content_has_frontmatter(self, tmp_path, sample_post):
        generate_post_notes([sample_post], tmp_path)
        content = list((tmp_path / "posts").rglob("*.md"))[0].read_text()
        assert content.startswith("---")
        assert "uid: 1" in content
        assert "[[Martin Kleppmann's Blog]]" in content

    def test_empty_posts_list(self, tmp_path):
        paths = generate_post_notes([], tmp_path)
        assert paths == []

    def test_null_author_handled(self, tmp_path, sample_post_no_author):
        paths = generate_post_notes([sample_post_no_author], tmp_path)
        assert len(paths) == 1
        content = paths[0].read_text()
        assert "Unknown" in content

    def test_collision_same_title_uses_hash_suffix(self, tmp_path):
        """Two posts with the exact same title both get hash suffixes.

        Since hash is derived from title, they produce the same slug,
        and the second write overwrites the first (deterministic by title).
        Both paths are returned, pointing to the same file.
        """
        post1 = {
            "id": 1, "source_id": 10, "source_name": "Blog", "category": "Tech",
            "title": "Same Title", "url": "https://a.com/1", "author_name": "Author",
            "author_id": 1, "publication_date": "2026-01-01", "summary_text": "Sum1",
            "tags": ["a"], "difficulty_classification": "easy",
        }
        post2 = {
            "id": 2, "source_id": 10, "source_name": "Blog", "category": "Tech",
            "title": "Same Title", "url": "https://a.com/2", "author_name": "Author",
            "author_id": 1, "publication_date": "2026-01-02", "summary_text": "Sum2",
            "tags": ["b"], "difficulty_classification": "easy",
        }
        paths = generate_post_notes([post1, post2], tmp_path)
        # Both posts are attempted; collision triggers hash suffix on both
        assert len(paths) == 2
        # Because both have identical titles, slugify_with_hash produces identical slugs
        assert paths[0] == paths[1]
        # Hash suffix is present in the filename (not a bare slug)
        assert re.match(r".*-[a-f0-9]{6}$", paths[0].stem)

    def test_collision_different_content_same_slug(self, tmp_path):
        """Two posts with titles that slugify to the same string but are different."""
        post1 = {
            "id": 1, "source_id": 10, "source_name": "Blog", "category": "Tech",
            "title": "Hello World!!!", "url": "https://a.com/1", "author_name": "A",
            "author_id": 1, "publication_date": "2026-01-01", "summary_text": "S1",
            "tags": [], "difficulty_classification": None,
        }
        post2 = {
            "id": 2, "source_id": 10, "source_name": "Blog", "category": "Tech",
            "title": "Hello World???", "url": "https://a.com/2", "author_name": "A",
            "author_id": 1, "publication_date": "2026-01-02", "summary_text": "S2",
            "tags": [], "difficulty_classification": None,
        }
        paths = generate_post_notes([post1, post2], tmp_path)
        assert len(paths) == 2
        # Should have different filenames due to hash suffix
        assert paths[0].name != paths[1].name

    def test_category_slug_filesystem_safe(self, tmp_path, sample_post):
        sample_post["category"] = "DevOps & SRE"
        generate_post_notes([sample_post], tmp_path)
        dirs = list((tmp_path / "posts").iterdir())
        assert len(dirs) == 1
        assert dirs[0].name == "devops-sre"


# ---------------------------------------------------------------------------
# generate_source_notes tests
# ---------------------------------------------------------------------------

class TestGenerateSourceNotes:
    def test_creates_source_file(self, tmp_path, sample_source, sample_post):
        paths = generate_source_notes([sample_source], {10: [sample_post]}, tmp_path)
        assert len(paths) == 1
        rel = paths[0].relative_to(tmp_path)
        assert rel.parts[0] == "sources"
        assert rel.parts[1].endswith(".md")

    def test_content_has_source_info(self, tmp_path, sample_source, sample_post):
        generate_source_notes([sample_source], {10: [sample_post]}, tmp_path)
        content = list((tmp_path / "sources").rglob("*.md"))[0].read_text()
        assert "Martin Kleppmann's Blog" in content
        assert "[[Building Real-Time Pipelines with Kafka]]" in content

    def test_source_with_no_posts(self, tmp_path, sample_source):
        paths = generate_source_notes([sample_source], {}, tmp_path)
        assert len(paths) == 1
        content = paths[0].read_text()
        assert "No posts from this source yet." in content


# ---------------------------------------------------------------------------
# generate_author_notes tests
# ---------------------------------------------------------------------------

class TestGenerateAuthorNotes:
    def test_creates_author_file(self, tmp_path, sample_author, sample_post, sample_source):
        paths = generate_author_notes(
            [sample_author], {100: [sample_post]}, {100: [sample_source]}, tmp_path
        )
        assert len(paths) == 1
        rel = paths[0].relative_to(tmp_path)
        assert rel.parts[0] == "authors"

    def test_skips_null_author(self, tmp_path):
        null_author = {"author_id": None, "author_name": None, "post_count": 0,
                       "source_ids": [], "first_seen_at": None, "last_seen_at": None,
                       "primary_category": None}
        paths = generate_author_notes([null_author], {}, {}, tmp_path)
        assert paths == []

    def test_content_has_author_info(self, tmp_path, sample_author, sample_post, sample_source):
        generate_author_notes([sample_author], {100: [sample_post]}, {100: [sample_source]}, tmp_path)
        content = list((tmp_path / "authors").rglob("*.md"))[0].read_text()
        assert "Martin Kleppmann" in content
        assert "[[Building Real-Time Pipelines with Kafka]]" in content


# ---------------------------------------------------------------------------
# Idempotency tests
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_post_notes_idempotent(self, tmp_path, sample_post):
        generate_post_notes([sample_post], tmp_path)
        content1 = list((tmp_path / "posts").rglob("*.md"))[0].read_text()

        generate_post_notes([sample_post], tmp_path)
        content2 = list((tmp_path / "posts").rglob("*.md"))[0].read_text()

        assert content1 == content2

    def test_source_notes_idempotent(self, tmp_path, sample_source, sample_post):
        generate_source_notes([sample_source], {10: [sample_post]}, tmp_path)
        content1 = list((tmp_path / "sources").rglob("*.md"))[0].read_text()

        generate_source_notes([sample_source], {10: [sample_post]}, tmp_path)
        content2 = list((tmp_path / "sources").rglob("*.md"))[0].read_text()

        assert content1 == content2


# ---------------------------------------------------------------------------
# Wikilink consistency tests
# ---------------------------------------------------------------------------

class TestWikilinkConsistency:
    def test_post_wikilinks_match_source_filename(self, tmp_path, sample_post, sample_source):
        generate_post_notes([sample_post], tmp_path)
        generate_source_notes([sample_source], {10: [sample_post]}, tmp_path)

        post_content = list((tmp_path / "posts").rglob("*.md"))[0].read_text()
        source_files = list((tmp_path / "sources").rglob("*.md"))

        # Extract source wikilink from post
        source_wikilinks = re.findall(r"\[\[([^\]]+)\]\]", post_content)
        source_name = sample_post["source_name"]
        assert source_name in source_wikilinks

        # The source file H1 should match the wikilink target
        source_content = source_files[0].read_text()
        assert f"# {source_name}" in source_content

    def test_post_wikilinks_match_author_filename(self, tmp_path, sample_post, sample_author, sample_source):
        generate_post_notes([sample_post], tmp_path)
        generate_author_notes([sample_author], {100: [sample_post]}, {100: [sample_source]}, tmp_path)

        post_content = list((tmp_path / "posts").rglob("*.md"))[0].read_text()
        author_files = list((tmp_path / "authors").rglob("*.md"))

        author_name = sample_post["author_name"]
        wikilinks = re.findall(r"\[\[([^\]]+)\]\]", post_content)
        assert author_name in wikilinks

        author_content = author_files[0].read_text()
        assert f"# {author_name}" in author_content


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_group_posts_by_source_id(self, sample_post):
        grouped = _group_posts_by([sample_post], "source_id")
        assert 10 in grouped
        assert len(grouped[10]) == 1

    def test_group_posts_by_author_id(self, sample_post):
        grouped = _group_posts_by([sample_post], "author_id")
        assert 100 in grouped

    def test_group_posts_skips_none(self, sample_post_no_author):
        grouped = _group_posts_by([sample_post_no_author], "author_id")
        assert None not in grouped

    def test_build_sources_by_author(self, sample_post, sample_source):
        result = _build_sources_by_author([sample_post], [sample_source])
        assert 100 in result
        assert result[100][0]["name"] == "Martin Kleppmann's Blog"


# ---------------------------------------------------------------------------
# generate_all integration test (mocked DB)
# ---------------------------------------------------------------------------

class TestGenerateAll:
    @patch("src.vault.note_generator.fetch_all_authors")
    @patch("src.vault.note_generator.fetch_all_sources")
    @patch("src.vault.note_generator.fetch_all_posts")
    def test_generate_all_orchestration(
        self, mock_posts, mock_sources, mock_authors,
        tmp_path, sample_post, sample_source, sample_author,
    ):
        mock_posts.return_value = [sample_post]
        mock_sources.return_value = [sample_source]
        mock_authors.return_value = [sample_author]

        stats = generate_all(tmp_path)

        assert stats["posts_generated"] == 1
        assert stats["sources_generated"] == 1
        assert stats["authors_generated"] == 1
        assert stats["total_notes"] == 3

        # Verify files exist
        assert len(list((tmp_path / "posts").rglob("*.md"))) == 1
        assert len(list((tmp_path / "sources").rglob("*.md"))) == 1
        assert len(list((tmp_path / "authors").rglob("*.md"))) == 1

    @patch("src.vault.note_generator.fetch_all_authors")
    @patch("src.vault.note_generator.fetch_all_sources")
    @patch("src.vault.note_generator.fetch_all_posts")
    def test_generate_all_empty_data(self, mock_posts, mock_sources, mock_authors, tmp_path):
        mock_posts.return_value = []
        mock_sources.return_value = []
        mock_authors.return_value = []

        stats = generate_all(tmp_path)
        assert stats["total_notes"] == 0
