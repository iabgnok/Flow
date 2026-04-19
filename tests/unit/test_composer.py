from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myflow.engine.composer import WorkflowComposer
from myflow.engine.models import ParamSpec, WorkflowModel, WorkflowStep
from myflow.engine.skill_registry import SkillRegistry
from myflow.infra.config import AppConfig
from myflow.skills.file_ops import FileReaderSkill, FileWriterSkill


@pytest.mark.asyncio
async def test_compose_until_valid_retries_then_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = SkillRegistry()
    registry.register(FileReaderSkill())
    registry.register(FileWriterSkill())

    bad = WorkflowModel(
        name="bad",
        description="x",
        steps=[
            WorkflowStep(id=1, name="x", action="no_such_skill", inputs={}, outputs={"x": "file_content"}),
        ],
    )
    good = WorkflowModel(
        name="ok",
        description="ok",
        inputs={"file_path": ParamSpec(description="p")},
        steps=[
            WorkflowStep(
                id=1,
                name="r",
                action="file_reader",
                inputs={"file_path": "{{file_path}}"},
                outputs={"file_content": "file_content"},
            ),
        ],
    )

    seq = iter([bad, good])

    async def fake_compose(*_a, **_k):
        return next(seq)

    llm = MagicMock()
    composer = WorkflowComposer(llm, registry, AppConfig(composer_max_attempts=3))
    monkeypatch.setattr(composer, "compose", fake_compose)

    outcome = await composer.compose_until_valid("do something")
    assert outcome.workflow.name == "ok"
    assert outcome.report.execution_ready()
    assert outcome.attempts == 2
