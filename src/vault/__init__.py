"""Vault note generation package.

Public interface for generating and validating Obsidian markdown notes.
"""

from src.vault.note_generator import (
    generate_all,
    generate_author_notes,
    generate_post_notes,
    generate_source_notes,
    slugify_title,
    slugify_with_hash,
)
from src.vault.note_validator import (
    ValidationFailure,
    ValidationResult,
    ValidationSummary,
    validate_all,
    validate_note,
)

__all__ = [
    # generation
    "generate_all",
    "generate_author_notes",
    "generate_post_notes",
    "generate_source_notes",
    "slugify_title",
    "slugify_with_hash",
    # validation
    "validate_all",
    "validate_note",
    "ValidationFailure",
    "ValidationResult",
    "ValidationSummary",
]
