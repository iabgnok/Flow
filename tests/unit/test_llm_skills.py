from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myflow.skills.llm_call import (
    LLMAnalyzeSkill,
    LLMAnalyzeInput,
    LLMVerifySkill,
    LLMVerifyInput,
    LLMAnalyzeOutput,
    LLMVerifyOutput,
)
from myflow.skills.base import SkillExecutionError


@pytest.mark.asyncio
async def test_llm_analyze_execute() -> None:
    llm = MagicMock()
    llm.create_structured = AsyncMock(
        return_value=LLMAnalyzeOutput(analysis_result="ok", confidence=0.9),
    )
    skill = LLMAnalyzeSkill(llm)
    out = await skill.execute(LLMAnalyzeInput(content="c", instruction="i"), {})
    assert out.analysis_result == "ok"
    llm.create_structured.assert_awaited()


@pytest.mark.asyncio
async def test_llm_verify_raises_when_failed() -> None:
    llm = MagicMock()
    llm.create_structured = AsyncMock(
        return_value=LLMVerifyOutput(verify_result="bad", passed=False),
    )
    skill = LLMVerifySkill(llm)
    with pytest.raises(SkillExecutionError):
        await skill.execute(LLMVerifyInput(artifact="a", criteria="c"), {})
