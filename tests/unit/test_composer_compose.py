from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myflow.engine.composer import WorkflowComposer
from myflow.engine.models import ParamSpec, WorkflowModel, WorkflowStep
from myflow.engine.skill_registry import SkillRegistry
from myflow.infra.config import AppConfig
from myflow.skills.file_ops import FileReaderSkill


@pytest.mark.asyncio
async def test_compose_builds_nonempty_system_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = SkillRegistry()
    registry.register(FileReaderSkill())
    wf = WorkflowModel(
        name="one",
        description="d",
        inputs={"file_path": ParamSpec(description="p")},
        steps=[
            WorkflowStep(
                id=1,
                name="r",
                action="file_reader",
                inputs={"file_path": "{{file_path}}"},
                outputs={"c": "file_content"},
            ),
        ],
    )
    seen: dict[str, str] = {}

    async def capture(*, system: str, user: str, **_kwargs):
        seen["system"] = system
        seen["user"] = user
        return wf

    llm = MagicMock()
    llm.create_structured = capture
    composer = WorkflowComposer(llm, registry, AppConfig())
    out = await composer.compose("某需求")
    assert out.name == "one"
    assert "可用技能" in seen["system"]
    assert "某需求" in seen["user"]
