from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myflow.engine.cache import ChampionCache
from myflow.engine.composer import WorkflowComposer
from myflow.engine.models import ParamSpec, WorkflowModel, WorkflowStep
from myflow.engine.skill_registry import SkillRegistry
from myflow.infra.config import AppConfig
from myflow.skills.file_ops import FileReaderSkill


@pytest.mark.asyncio
async def test_compose_until_valid_returns_cached_without_llm(tmp_path: Path) -> None:
    registry = SkillRegistry()
    registry.register(FileReaderSkill())
    wf = WorkflowModel(
        name="cached_wf",
        description="d",
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
    cache = ChampionCache(tmp_path / "cc")
    cache.put("同一需求", wf, registry.skill_names)

    llm = MagicMock()
    llm.create_structured = AsyncMock()
    composer = WorkflowComposer(llm, registry, AppConfig(), cache=cache)

    outcome = await composer.compose_until_valid("同一需求")
    assert outcome.from_cache
    assert outcome.attempts == 0
    assert outcome.workflow.name == "cached_wf"
    llm.create_structured.assert_not_called()
