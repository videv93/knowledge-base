"""Vault note validator — validates generated Obsidian markdown notes.

Checks each note for:
- Valid YAML frontmatter that parses without error
- Required frontmatter fields present and non-null/non-empty (by note type)
- Frontmatter wikilinks (source/author fields) resolve to existing notes
- Tags are non-empty strings (when present)

Does NOT query the database. Reads only from the filesystem.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from slugify import slugify

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

REQUIRED_FIELDS: dict[str, list[str]] = {
    "post": ["uid", "source", "author", "date", "tags", "category", "url", "status"],
    "source": ["name", "category", "rss_url", "status"],
    "author": ["name", "primary_category", "post_count"],
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ValidationFailure:
    """A single field-level validation failure."""

    field: str
    reason: str


@dataclass
class ValidationResult:
    """Validation outcome for a single note file."""

    file_path: Path
    passed: bool
    failures: list[ValidationFailure] = field(default_factory=list)


@dataclass
class ValidationSummary:
    """Aggregated validation results across all notes."""

    total: int
    passed: int
    failed: int
    results: list[ValidationResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Individual validators
# ---------------------------------------------------------------------------


def validate_frontmatter(content: str, file_path: Path) -> tuple[list[ValidationFailure], dict | None]:
    """Parse YAML frontmatter from note content.

    Returns (failures, frontmatter_dict).
    If parsing fails, failures is non-empty and frontmatter_dict is None.
    """
    if not content.startswith("---"):
        return [
            ValidationFailure(field="frontmatter", reason="Note does not begin with '---' frontmatter delimiter")
        ], None

    parts = content.split("---", 2)
    if len(parts) < 3:
        return [
            ValidationFailure(field="frontmatter", reason="Frontmatter block not properly closed with '---'")
        ], None

    raw_fm = parts[1]
    try:
        fm = yaml.safe_load(raw_fm)
        return [], fm if isinstance(fm, dict) else {}
    except yaml.YAMLError as exc:
        return [
            ValidationFailure(field="frontmatter", reason=f"YAML parse error: {exc}")
        ], None


def validate_required_fields(
    frontmatter: dict, note_type: str, file_path: Path
) -> list[ValidationFailure]:
    """Check that all required frontmatter fields are present and non-null/non-empty."""
    required = REQUIRED_FIELDS.get(note_type, [])
    failures = []
    for field_name in required:
        if field_name not in frontmatter:
            failures.append(
                ValidationFailure(
                    field=field_name,
                    reason=f"Required field '{field_name}' missing from {note_type} note frontmatter",
                )
            )
        elif frontmatter[field_name] is None:
            failures.append(
                ValidationFailure(
                    field=field_name,
                    reason=f"Required field '{field_name}' is null in {note_type} note frontmatter",
                )
            )
        elif isinstance(frontmatter[field_name], str) and not frontmatter[field_name].strip():
            failures.append(
                ValidationFailure(
                    field=field_name,
                    reason=f"Required field '{field_name}' is empty in {note_type} note frontmatter",
                )
            )
    return failures


def validate_wikilinks(
    frontmatter: dict,
    generated_dir: Path,
    existing_slugs: frozenset[str] | None = None,
) -> list[ValidationFailure]:
    """Validate that source and author wikilinks in frontmatter resolve to existing notes.

    Only validates frontmatter 'source' and 'author' fields (not body topic wikilinks,
    which are intentionally unresolved in Obsidian).

    Skips validation for [[Unknown]] author — a template fallback with no note.

    Args:
        frontmatter: Parsed frontmatter dict from the note.
        generated_dir: Root of the generated/ directory (used for rglob fallback).
        existing_slugs: Pre-built set of note filename stems for O(1) lookup.
            When provided by validate_all, avoids repeated rglob traversals.
            When None (direct call), falls back to rglob for correctness.
    """
    failures = []
    for fm_field in ("source", "author"):
        value = frontmatter.get(fm_field)
        if not value:
            continue
        match = WIKILINK_RE.match(str(value).strip())
        if not match:
            continue
        target = match.group(1).strip()

        # Skip the [[Unknown]] template fallback for author (NULL author_name in DB)
        if target.lower() == "unknown":
            continue

        target_slug = slugify(target, max_length=80)
        if not target_slug:
            continue

        if existing_slugs is not None:
            found = target_slug in existing_slugs
        else:
            found = bool(list(generated_dir.rglob(f"{target_slug}.md")))

        if not found:
            failures.append(
                ValidationFailure(
                    field=fm_field,
                    reason=f"Wikilink target '[[{target}]]' has no corresponding note in generated/",
                )
            )
    return failures


def validate_tags(frontmatter: dict, file_path: Path) -> list[ValidationFailure]:
    """Check that tags, when present, are a list of non-empty strings."""
    if "tags" not in frontmatter:
        return []

    tags = frontmatter["tags"]
    if not isinstance(tags, list):
        return [
            ValidationFailure(
                field="tags",
                reason=f"'tags' must be a YAML list, got {type(tags).__name__}",
            )
        ]

    failures = []
    for i, tag in enumerate(tags):
        if not isinstance(tag, str) or not tag.strip():
            failures.append(
                ValidationFailure(
                    field="tags",
                    reason=f"tags[{i}] is empty or not a string: {tag!r}",
                )
            )
    return failures


def detect_note_type(file_path: Path) -> str:
    """Determine note type from directory structure.

    generated/posts/...   → 'post'
    generated/sources/... → 'source'
    generated/authors/... → 'author'
    otherwise             → 'unknown'
    """
    parts = file_path.parts
    for i, part in enumerate(parts):
        if part == "posts" and i + 1 < len(parts):
            return "post"
        if part == "sources":
            return "source"
        if part == "authors":
            return "author"
    return "unknown"


# ---------------------------------------------------------------------------
# Per-note orchestration
# ---------------------------------------------------------------------------


def validate_note(
    file_path: Path,
    generated_dir: Path,
    *,
    existing_slugs: frozenset[str] | None = None,
) -> ValidationResult:
    """Validate a single note file.

    Runs all validators and collects all failures.
    Logs each failure at WARNING level.
    Returns ValidationResult(passed=True) if no failures.

    Args:
        file_path: Path to the note file to validate.
        generated_dir: Root of the generated/ directory.
        existing_slugs: Pre-built slug set passed from validate_all for O(1)
            wikilink resolution. Falls back to rglob when None.
    """
    all_failures: list[ValidationFailure] = []

    # Read file
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        failure = ValidationFailure(field="file", reason=f"Cannot read file: {exc}")
        logger.warning("Validation failure — %s: [file] %s", file_path, failure.reason)
        return ValidationResult(file_path=file_path, passed=False, failures=[failure])

    # 1. Frontmatter parsing
    fm_failures, frontmatter = validate_frontmatter(content, file_path)
    all_failures.extend(fm_failures)

    if frontmatter is None:
        for f in fm_failures:
            logger.warning("Validation failure — %s: [%s] %s", file_path, f.field, f.reason)
        return ValidationResult(file_path=file_path, passed=False, failures=all_failures)

    note_type = detect_note_type(file_path)

    # 2. Required fields (presence + non-null/non-empty)
    req_failures = validate_required_fields(frontmatter, note_type, file_path)
    all_failures.extend(req_failures)

    # 3. Wikilinks (source/author frontmatter fields only)
    wl_failures = validate_wikilinks(frontmatter, generated_dir, existing_slugs)
    all_failures.extend(wl_failures)

    # 4. Tags
    tag_failures = validate_tags(frontmatter, file_path)
    all_failures.extend(tag_failures)

    # Log each failure at WARNING
    for f in all_failures:
        logger.warning("Validation failure — %s: [%s] %s", file_path, f.field, f.reason)

    passed = len(all_failures) == 0
    return ValidationResult(file_path=file_path, passed=passed, failures=all_failures)


# ---------------------------------------------------------------------------
# Directory-level orchestration
# ---------------------------------------------------------------------------


def validate_all(generated_dir: Path) -> ValidationSummary:
    """Validate all .md files in generated_dir recursively.

    Returns a ValidationSummary with counts and individual results.
    Non-existent directory returns an empty summary (not an error).

    Builds a slug lookup set once and passes it to each validate_note call,
    keeping wikilink resolution O(n) instead of O(n²).
    """
    if not generated_dir.exists():
        logger.info("Generated directory does not exist: %s — skipping validation", generated_dir)
        return ValidationSummary(total=0, passed=0, failed=0, results=[])

    note_paths = sorted(generated_dir.rglob("*.md"))

    if not note_paths:
        logger.info("No .md files found in %s", generated_dir)
        return ValidationSummary(total=0, passed=0, failed=0, results=[])

    # Build slug set from already-collected paths — no second rglob traversal
    existing_slugs = frozenset(p.stem for p in note_paths)

    results: list[ValidationResult] = []
    for path in note_paths:
        result = validate_note(path, generated_dir, existing_slugs=existing_slugs)
        results.append(result)

    passed_count = sum(1 for r in results if r.passed)
    failed_count = len(results) - passed_count

    logger.info(
        "Vault validation complete: %d/%d notes passed, %d failed",
        passed_count,
        len(results),
        failed_count,
    )

    return ValidationSummary(
        total=len(results),
        passed=passed_count,
        failed=failed_count,
        results=results,
    )
