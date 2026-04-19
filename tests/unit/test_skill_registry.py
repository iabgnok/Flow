from __future__ import annotations

import pytest

from myflow.engine.skill_registry import SkillNotFoundError, SkillRegistry, build_default_registry
from myflow.skills.file_ops import FileReaderSkill


def test_registered_skill_found() -> None:
    r = SkillRegistry()
    r.register(FileReaderSkill())
    assert r.get("file_reader").name == "file_reader"


def test_unknown_skill_raises() -> None:
    r = SkillRegistry()
    with pytest.raises(SkillNotFoundError):
        r.get("nope")


def test_skill_cards_generated() -> None:
    r = SkillRegistry()
    r.register(FileReaderSkill())
    cards = r.all_skill_cards()
    assert len(cards) == 1
    assert cards[0].name == "file_reader"
    assert "path" in cards[0].input_fields
    assert "file_content" in cards[0].output_fields


def test_prompt_text_contains_all_skills() -> None:
    r = build_default_registry()
    text = r.skill_cards_as_prompt()
    assert "file_reader" in text
    assert "file_writer" in text
    assert "llm_analyze" in text
    assert "llm_generate" in text
    assert "llm_verify" in text
    assert "sub_workflow" in text
    assert "multi_file_reader" not in text  # 别名不在 Composer 清单中，但仍可 registry.get 执行


def test_multi_file_reader_alias_registered() -> None:
    r = build_default_registry()
    assert r.get("multi_file_reader").name == "multi_file_reader"

