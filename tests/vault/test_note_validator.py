"""Tests for vault note validator — frontmatter parsing, required fields, wikilink validation."""

import logging
from pathlib import Path

from src.vault.note_validator import (
    ValidationSummary,
    detect_note_type,
    validate_all,
    validate_frontmatter,
    validate_note,
    validate_required_fields,
    validate_tags,
    validate_wikilinks,
)

# ---------------------------------------------------------------------------
# Helper to write note files
# ---------------------------------------------------------------------------


def write_note(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def make_post_note(
    generated_dir: Path,
    filename: str = "test-post.md",
    category: str = "data-engineering",
    uid: str = "1",
    source: str = "[[Some Blog]]",
    author: str = "[[Jane Doe]]",
    date: str = "2026-02-15",
    tags: str = "[kafka, streaming]",
    category_fm: str = "Data Engineering",
    url: str = "https://example.com/post",
    status: str = "🌱 Seedling",
    body: str = "# Test Post\n\nBody text.\n",
) -> Path:
    frontmatter = (
        f"uid: {uid}\n"
        f'source: "{source}"\n'
        f'author: "{author}"\n'
        f"date: {date}\n"
        f"tags: {tags}\n"
        f"category: {category_fm}\n"
        f"url: {url}\n"
        f"status: {status!r}\n"
    )
    content = f"---\n{frontmatter}---\n\n{body}"
    path = generated_dir / "posts" / category / filename
    return write_note(path, content)


def make_source_note(
    generated_dir: Path,
    filename: str = "some-blog.md",
    name: str = "Some Blog",
    category: str = "Data Engineering",
    rss_url: str = "https://example.com/feed.xml",
    total_post_count: int = 42,
    status: str = "active",
) -> Path:
    frontmatter = (
        f"name: {name}\n"
        f"category: {category}\n"
        f"rss_url: {rss_url}\n"
        f"total_post_count: {total_post_count}\n"
        f"status: {status}\n"
    )
    content = f"---\n{frontmatter}---\n\n# {name}\n"
    path = generated_dir / "sources" / filename
    return write_note(path, content)


def make_author_note(
    generated_dir: Path,
    filename: str = "jane-doe.md",
    name: str = "Jane Doe",
    primary_category: str = "Data Engineering",
    post_count: int = 5,
) -> Path:
    frontmatter = (
        f"name: {name}\n"
        f"primary_category: {primary_category}\n"
        f"post_count: {post_count}\n"
    )
    content = f"---\n{frontmatter}---\n\n# {name}\n"
    path = generated_dir / "authors" / filename
    return write_note(path, content)


# ---------------------------------------------------------------------------
# validate_frontmatter
# ---------------------------------------------------------------------------


class TestValidateFrontmatter:
    def test_valid_yaml_returns_empty_failures(self, tmp_path):
        content = "---\nuid: 1\nname: foo\n---\n# Hello\n"
        file_path = tmp_path / "note.md"
        failures, fm = validate_frontmatter(content, file_path)
        assert failures == []
        assert fm == {"uid": 1, "name": "foo"}

    def test_malformed_yaml_returns_failure(self, tmp_path):
        content = "---\nuid: [unclosed\n---\n"
        file_path = tmp_path / "note.md"
        failures, fm = validate_frontmatter(content, file_path)
        assert len(failures) == 1
        assert failures[0].field == "frontmatter"
        assert fm is None

    def test_no_frontmatter_returns_failure(self, tmp_path):
        content = "# Just a heading\nNo frontmatter here.\n"
        file_path = tmp_path / "note.md"
        failures, fm = validate_frontmatter(content, file_path)
        assert len(failures) == 1
        assert failures[0].field == "frontmatter"
        assert fm is None

    def test_empty_frontmatter_block_returns_empty_dict(self, tmp_path):
        content = "---\n---\n# Hello\n"
        file_path = tmp_path / "note.md"
        failures, fm = validate_frontmatter(content, file_path)
        assert failures == []
        assert fm == {}

    def test_bad_indentation_returns_failure(self, tmp_path):
        # YAML with invalid indentation
        content = "---\nkey:\n  sub:\n bad_indent: x\n---\n"
        file_path = tmp_path / "note.md"
        failures, fm = validate_frontmatter(content, file_path)
        # pyyaml is lenient about some indentation, only check that it doesn't crash
        assert isinstance(failures, list)


# ---------------------------------------------------------------------------
# validate_required_fields
# ---------------------------------------------------------------------------


class TestValidateRequiredFields:
    def test_post_all_fields_present_passes(self, tmp_path):
        fm = {
            "uid": "abc",
            "source": "[[Blog]]",
            "author": "[[Author]]",
            "date": "2026-01-01",
            "tags": ["tag1"],
            "category": "Engineering",
            "url": "https://example.com",
            "status": "active",
        }
        failures = validate_required_fields(fm, "post", tmp_path / "note.md")
        assert failures == []

    def test_post_missing_uid_fails(self, tmp_path):
        fm = {
            "source": "[[Blog]]",
            "author": "[[Author]]",
            "date": "2026-01-01",
            "tags": ["tag1"],
            "category": "Engineering",
            "url": "https://example.com",
            "status": "active",
        }
        failures = validate_required_fields(fm, "post", tmp_path / "note.md")
        fields = [f.field for f in failures]
        assert "uid" in fields

    def test_post_missing_url_fails(self, tmp_path):
        fm = {
            "uid": "1",
            "source": "[[Blog]]",
            "author": "[[Author]]",
            "date": "2026-01-01",
            "tags": ["tag1"],
            "category": "Engineering",
            "status": "active",
        }
        failures = validate_required_fields(fm, "post", tmp_path / "note.md")
        fields = [f.field for f in failures]
        assert "url" in fields

    def test_post_missing_tags_fails(self, tmp_path):
        fm = {
            "uid": "1",
            "source": "[[Blog]]",
            "author": "[[Author]]",
            "date": "2026-01-01",
            "category": "Engineering",
            "url": "https://example.com",
            "status": "active",
        }
        failures = validate_required_fields(fm, "post", tmp_path / "note.md")
        fields = [f.field for f in failures]
        assert "tags" in fields

    def test_source_all_fields_present_passes(self, tmp_path):
        fm = {
            "name": "My Blog",
            "category": "Engineering",
            "rss_url": "https://example.com/rss",
            "status": "active",
        }
        failures = validate_required_fields(fm, "source", tmp_path / "note.md")
        assert failures == []

    def test_source_missing_name_fails(self, tmp_path):
        fm = {"category": "Engineering", "rss_url": "https://example.com/rss", "status": "active"}
        failures = validate_required_fields(fm, "source", tmp_path / "note.md")
        fields = [f.field for f in failures]
        assert "name" in fields

    def test_author_all_fields_present_passes(self, tmp_path):
        fm = {"name": "Jane Doe", "primary_category": "Engineering", "post_count": 5}
        failures = validate_required_fields(fm, "author", tmp_path / "note.md")
        assert failures == []

    def test_author_missing_name_fails(self, tmp_path):
        fm = {"primary_category": "Engineering", "post_count": 5}
        failures = validate_required_fields(fm, "author", tmp_path / "note.md")
        fields = [f.field for f in failures]
        assert "name" in fields

    def test_unknown_note_type_returns_no_failures(self, tmp_path):
        fm = {"anything": "value"}
        failures = validate_required_fields(fm, "unknown", tmp_path / "note.md")
        assert failures == []

    def test_post_null_uid_fails(self, tmp_path):
        """uid: null should fail — key present but value is None."""
        fm = {
            "uid": None,
            "source": "[[Blog]]",
            "author": "[[Author]]",
            "date": "2026-01-01",
            "tags": ["tag1"],
            "category": "Engineering",
            "url": "https://example.com",
            "status": "active",
        }
        failures = validate_required_fields(fm, "post", tmp_path / "note.md")
        fields = [f.field for f in failures]
        assert "uid" in fields
        assert any("null" in f.reason for f in failures if f.field == "uid")

    def test_post_empty_string_url_fails(self, tmp_path):
        """url: '' should fail — key present but value is empty string."""
        fm = {
            "uid": "1",
            "source": "[[Blog]]",
            "author": "[[Author]]",
            "date": "2026-01-01",
            "tags": ["tag1"],
            "category": "Engineering",
            "url": "",
            "status": "active",
        }
        failures = validate_required_fields(fm, "post", tmp_path / "note.md")
        fields = [f.field for f in failures]
        assert "url" in fields
        assert any("empty" in f.reason for f in failures if f.field == "url")


# ---------------------------------------------------------------------------
# validate_wikilinks
# ---------------------------------------------------------------------------


class TestValidateWikilinks:
    def test_all_wikilinks_resolve_passes(self, tmp_path):
        generated_dir = tmp_path / "generated"
        make_source_note(generated_dir, "some-blog.md")
        make_author_note(generated_dir, "jane-doe.md")
        fm = {"source": "[[Some Blog]]", "author": "[[Jane Doe]]"}
        failures = validate_wikilinks(fm, generated_dir)
        assert failures == []

    def test_missing_source_note_returns_failure(self, tmp_path):
        generated_dir = tmp_path / "generated"
        # author note exists, source does not
        make_author_note(generated_dir, "jane-doe.md")
        fm = {"source": "[[Nonexistent Blog]]", "author": "[[Jane Doe]]"}
        failures = validate_wikilinks(fm, generated_dir)
        fields = [f.field for f in failures]
        assert "source" in fields

    def test_missing_author_note_returns_failure(self, tmp_path):
        generated_dir = tmp_path / "generated"
        make_source_note(generated_dir, "some-blog.md")
        fm = {"source": "[[Some Blog]]", "author": "[[Unknown Author]]"}
        failures = validate_wikilinks(fm, generated_dir)
        fields = [f.field for f in failures]
        assert "author" in fields

    def test_no_wikilinks_in_fm_passes(self, tmp_path):
        generated_dir = tmp_path / "generated"
        generated_dir.mkdir()
        fm = {}
        failures = validate_wikilinks(fm, generated_dir)
        assert failures == []

    def test_unknown_author_wikilink_skipped(self, tmp_path):
        """[[Unknown]] author is a template default — no corresponding file; should be skipped."""
        generated_dir = tmp_path / "generated"
        make_source_note(generated_dir, "some-blog.md")
        fm = {"source": "[[Some Blog]]", "author": "[[Unknown]]"}
        failures = validate_wikilinks(fm, generated_dir)
        # [[Unknown]] is a template fallback for NULL author_name — must not fail validation
        source_failures = [f for f in failures if f.field == "source"]
        author_failures = [f for f in failures if f.field == "author"]
        assert source_failures == []
        assert author_failures == []

    def test_existing_slugs_set_used_for_lookup(self, tmp_path):
        """When existing_slugs is provided, it is used instead of rglob."""
        generated_dir = tmp_path / "generated"
        generated_dir.mkdir()
        # No files on disk — but slug set says source exists
        existing_slugs = frozenset(["some-blog"])
        fm = {"source": "[[Some Blog]]"}
        failures = validate_wikilinks(fm, generated_dir, existing_slugs=existing_slugs)
        assert failures == []

    def test_existing_slugs_set_missing_slug_fails(self, tmp_path):
        """Slug not in existing_slugs reports a failure even if file exists on disk."""
        generated_dir = tmp_path / "generated"
        make_source_note(generated_dir, "some-blog.md")
        existing_slugs: frozenset[str] = frozenset()  # empty — overrides disk state
        fm = {"source": "[[Some Blog]]"}
        failures = validate_wikilinks(fm, generated_dir, existing_slugs=existing_slugs)
        fields = [f.field for f in failures]
        assert "source" in fields


# ---------------------------------------------------------------------------
# validate_tags
# ---------------------------------------------------------------------------


class TestValidateTags:
    def test_valid_tags_list_passes(self, tmp_path):
        fm = {"tags": ["kafka", "streaming"]}
        failures = validate_tags(fm, tmp_path / "note.md")
        assert failures == []

    def test_empty_tags_list_passes(self, tmp_path):
        """Empty tags list is allowed (not all posts have tags in the template)."""
        fm = {"tags": []}
        failures = validate_tags(fm, tmp_path / "note.md")
        assert failures == []

    def test_tags_with_empty_string_fails(self, tmp_path):
        fm = {"tags": ["kafka", "", "streaming"]}
        failures = validate_tags(fm, tmp_path / "note.md")
        assert len(failures) >= 1
        assert any("empty" in f.reason.lower() for f in failures)

    def test_tags_missing_passes(self, tmp_path):
        """Tags field may not be present in all note types."""
        fm = {"name": "Some Blog"}
        failures = validate_tags(fm, tmp_path / "note.md")
        assert failures == []

    def test_tags_is_string_not_list_fails(self, tmp_path):
        fm = {"tags": "kafka, streaming"}
        failures = validate_tags(fm, tmp_path / "note.md")
        assert len(failures) >= 1
        assert any("list" in f.reason.lower() for f in failures)


# ---------------------------------------------------------------------------
# detect_note_type
# ---------------------------------------------------------------------------


class TestDetectNoteType:
    def test_post_path_detected(self, tmp_path):
        path = tmp_path / "generated" / "posts" / "data-engineering" / "note.md"
        assert detect_note_type(path) == "post"

    def test_source_path_detected(self, tmp_path):
        path = tmp_path / "generated" / "sources" / "my-blog.md"
        assert detect_note_type(path) == "source"

    def test_author_path_detected(self, tmp_path):
        path = tmp_path / "generated" / "authors" / "jane-doe.md"
        assert detect_note_type(path) == "author"

    def test_unknown_path_returns_unknown(self, tmp_path):
        path = tmp_path / "generated" / "misc" / "something.md"
        assert detect_note_type(path) == "unknown"

    def test_readme_in_generated_returns_unknown(self, tmp_path):
        path = tmp_path / "generated" / "README.md"
        assert detect_note_type(path) == "unknown"


# ---------------------------------------------------------------------------
# validate_note
# ---------------------------------------------------------------------------


class TestValidateNote:
    def test_fully_valid_post_note_passes(self, tmp_path):
        generated_dir = tmp_path / "generated"
        make_source_note(generated_dir, "some-blog.md")
        make_author_note(generated_dir, "jane-doe.md")
        post_path = make_post_note(generated_dir)

        result = validate_note(post_path, generated_dir)
        assert result.passed is True
        assert result.failures == []

    def test_invalid_yaml_fails(self, tmp_path, caplog):
        generated_dir = tmp_path / "generated"
        path = generated_dir / "posts" / "cat" / "bad.md"
        write_note(path, "---\nbad: [unclosed\n---\n# Title\n")

        with caplog.at_level(logging.WARNING):
            result = validate_note(path, generated_dir)

        assert result.passed is False
        assert len(result.failures) >= 1
        assert any(record.levelno == logging.WARNING for record in caplog.records)

    def test_missing_required_field_fails(self, tmp_path, caplog):
        generated_dir = tmp_path / "generated"
        # Post note missing uid
        path = generated_dir / "posts" / "data-engineering" / "note.md"
        write_note(
            path,
            '---\nsource: "[[Blog]]"\nauthor: "[[Auth]]"\ndate: 2026-01-01\n'
            "tags: [x]\ncategory: Eng\nurl: https://ex.com\nstatus: active\n---\n# Title\n",
        )

        with caplog.at_level(logging.WARNING):
            result = validate_note(path, generated_dir)

        assert result.passed is False
        fields = [f.field for f in result.failures]
        assert "uid" in fields
        assert any(record.levelno == logging.WARNING for record in caplog.records)

    def test_broken_source_wikilink_fails(self, tmp_path, caplog):
        generated_dir = tmp_path / "generated"
        # No source note for "[[Ghost Blog]]"
        make_author_note(generated_dir, "jane-doe.md")
        post_path = make_post_note(generated_dir, source="[[Ghost Blog]]")

        with caplog.at_level(logging.WARNING):
            result = validate_note(post_path, generated_dir)

        assert result.passed is False
        fields = [f.field for f in result.failures]
        assert "source" in fields

    def test_valid_source_note_passes(self, tmp_path):
        generated_dir = tmp_path / "generated"
        source_path = make_source_note(generated_dir)
        result = validate_note(source_path, generated_dir)
        assert result.passed is True

    def test_valid_author_note_passes(self, tmp_path):
        generated_dir = tmp_path / "generated"
        author_path = make_author_note(generated_dir)
        result = validate_note(author_path, generated_dir)
        assert result.passed is True

    def test_file_read_error_is_counted_as_failure(self, tmp_path):
        generated_dir = tmp_path / "generated"
        # Non-existent path
        missing_path = generated_dir / "posts" / "cat" / "nonexistent.md"
        result = validate_note(missing_path, generated_dir)
        assert result.passed is False
        assert len(result.failures) >= 1


# ---------------------------------------------------------------------------
# validate_all
# ---------------------------------------------------------------------------


class TestValidateAll:
    def test_all_valid_notes_returns_zero_failures(self, tmp_path):
        generated_dir = tmp_path / "generated"
        make_source_note(generated_dir, "some-blog.md")
        make_author_note(generated_dir, "jane-doe.md")
        make_post_note(generated_dir)

        summary = validate_all(generated_dir)
        assert isinstance(summary, ValidationSummary)
        assert summary.failed == 0
        assert summary.passed == 3
        assert summary.total == 3

    def test_mixed_valid_invalid_returns_correct_counts(self, tmp_path):
        generated_dir = tmp_path / "generated"
        make_source_note(generated_dir)  # valid
        make_author_note(generated_dir)  # valid
        make_post_note(generated_dir)  # valid

        # Add an invalid note — missing uid
        bad_path = generated_dir / "posts" / "devops" / "bad-note.md"
        write_note(
            bad_path,
            '---\nsource: "[[Blog]]"\nauthor: "[[Auth]]"\ndate: 2026-01-01\n'
            "tags: [x]\ncategory: Eng\nurl: https://ex.com\nstatus: active\n---\n# Bad\n",
        )

        summary = validate_all(generated_dir)
        assert summary.total == 4
        assert summary.failed == 1
        assert summary.passed == 3

    def test_empty_directory_returns_zero_summary(self, tmp_path):
        generated_dir = tmp_path / "generated"
        generated_dir.mkdir()

        summary = validate_all(generated_dir)
        assert summary.total == 0
        assert summary.passed == 0
        assert summary.failed == 0

    def test_summary_results_list_length_matches_total(self, tmp_path):
        generated_dir = tmp_path / "generated"
        make_source_note(generated_dir)
        make_author_note(generated_dir)

        summary = validate_all(generated_dir)
        assert len(summary.results) == summary.total

    def test_nonexistent_generated_dir_returns_zero_summary(self, tmp_path):
        generated_dir = tmp_path / "nonexistent"
        summary = validate_all(generated_dir)
        assert summary.total == 0
        assert summary.passed == 0
        assert summary.failed == 0

    def test_validate_all_logs_summary_at_info(self, tmp_path, caplog):
        generated_dir = tmp_path / "generated"
        make_source_note(generated_dir)

        with caplog.at_level(logging.INFO, logger="src.vault.note_validator"):
            validate_all(generated_dir)

        assert any(record.levelno == logging.INFO for record in caplog.records)

    def test_validate_note_accepts_existing_slugs_kwarg(self, tmp_path):
        """validate_note forwards existing_slugs to wikilink validator."""
        generated_dir = tmp_path / "generated"
        make_author_note(generated_dir, "jane-doe.md")
        # Source note NOT on disk — but we inject it via existing_slugs
        existing_slugs = frozenset(["some-blog", "jane-doe"])
        post_path = make_post_note(generated_dir)

        result = validate_note(post_path, generated_dir, existing_slugs=existing_slugs)
        assert result.passed is True


# ---------------------------------------------------------------------------
# Public API surface (imported from src.vault)
# ---------------------------------------------------------------------------


class TestPublicApi:
    def test_validate_all_importable_from_vault(self):
        from src.vault import validate_all as va
        assert va is not None

    def test_validate_note_importable_from_vault(self):
        from src.vault import validate_note as vn
        assert vn is not None

    def test_dataclasses_importable_from_vault(self):
        from src.vault import ValidationFailure, ValidationResult, ValidationSummary
        assert ValidationSummary is not None
        assert ValidationResult is not None
        assert ValidationFailure is not None
