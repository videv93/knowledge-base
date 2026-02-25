"""Tests for summarization prompt templates."""

from src.summarization.prompt_templates import (
    SUMMARIZATION_SYSTEM_PROMPT,
    SUMMARIZATION_USER_PROMPT_TEMPLATE,
)


def test_system_prompt_exists_and_not_empty():
    assert isinstance(SUMMARIZATION_SYSTEM_PROMPT, str)
    assert len(SUMMARIZATION_SYSTEM_PROMPT) > 50


def test_system_prompt_contains_required_instructions():
    prompt = SUMMARIZATION_SYSTEM_PROMPT.lower()
    assert "summary" in prompt
    assert "tags" in prompt
    assert "difficulty" in prompt
    assert "beginner" in prompt
    assert "intermediate" in prompt
    assert "advanced" in prompt
    assert "json" in prompt


def test_system_prompt_specifies_sentence_count():
    assert "3-5" in SUMMARIZATION_SYSTEM_PROMPT


def test_system_prompt_specifies_tag_count():
    assert "3-8" in SUMMARIZATION_SYSTEM_PROMPT


def test_user_prompt_template_has_placeholders():
    assert "{title}" in SUMMARIZATION_USER_PROMPT_TEMPLATE
    assert "{body}" in SUMMARIZATION_USER_PROMPT_TEMPLATE


def test_user_prompt_template_renders():
    rendered = SUMMARIZATION_USER_PROMPT_TEMPLATE.format(
        title="Test Title", body="Test body content"
    )
    assert "Test Title" in rendered
    assert "Test body content" in rendered
