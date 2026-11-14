"""Tests for director-intent intake."""

from backend.workflows.user_intent import (
    DEFAULT_DIRECTOR_PROMPT,
    is_vague_prompt,
    resolve_user_intent,
)


def test_empty_is_vague() -> None:
    assert is_vague_prompt("")
    assert is_vague_prompt("   ")
    assert is_vague_prompt("默认")


def test_style_only_is_vague() -> None:
    assert is_vague_prompt("现代公寓，简洁高级")
    assert is_vague_prompt("年轻都市生活，温馨")
    assert is_vague_prompt("luxury modern")


def test_content_prompt_not_vague() -> None:
    assert not is_vague_prompt("突出厨房、客厅采光，介绍设施与空间布局")
    assert not is_vague_prompt("Showcase kitchen appliances and natural light")
    assert not is_vague_prompt(DEFAULT_DIRECTOR_PROMPT)


def test_resolve_empty_noninteractive() -> None:
    r = resolve_user_intent("", interactive=False)
    assert r.source == "default_empty"
    assert r.was_vague
    assert "空间" in r.prompt or "space" in r.prompt.lower()


def test_resolve_empty_english_default() -> None:
    from backend.workflows.user_intent import DEFAULT_DIRECTOR_PROMPT_EN

    r = resolve_user_intent("", interactive=False, language="en")
    assert r.source == "default_empty"
    assert r.prompt == DEFAULT_DIRECTOR_PROMPT_EN


def test_resolve_vague_noninteractive() -> None:
    r = resolve_user_intent("现代高级简洁", interactive=False)
    assert r.source == "default_vague"
    assert r.was_vague
    assert r.original_prompt == "现代高级简洁"
    assert r.prompt == DEFAULT_DIRECTOR_PROMPT


def test_resolve_specific_kept() -> None:
    text = "突出开放式厨房设施与采光，介绍每个空间布局"
    r = resolve_user_intent(text, interactive=False)
    assert r.source == "cli"
    assert not r.was_vague
    assert r.prompt == text
