from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myflow.skills.llm_call import (
    LLMAnalyzeSkill,
    LLMAnalyzeInput,
    LLMGenerateSkill,
    LLMGenerateInput,
    LLMGenerateOutput,
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
async def test_llm_analyze_injects_prev_error_on_retry() -> None:
    llm = MagicMock()
    llm.create_structured = AsyncMock(
        return_value=LLMAnalyzeOutput(analysis_result="ok", confidence=0.9),
    )
    skill = LLMAnalyzeSkill(llm)
    ctx = {"_prev_error": "缺测试目标", "_attempt": 1}
    await skill.execute(LLMAnalyzeInput(content="c", instruction="i"), ctx)
    call_kw = llm.create_structured.await_args.kwargs
    assert "缺测试目标" in call_kw["user"]
    assert "第 2 次尝试" in call_kw["user"]


@pytest.mark.asyncio
async def test_llm_generate_injects_prev_error_on_retry() -> None:
    llm = MagicMock()
    llm.create_structured = AsyncMock(return_value=LLMGenerateOutput(generated_text="ok"))
    skill = LLMGenerateSkill(llm)
    ctx = {"_prev_error": "未通过校验", "_attempt": 2}
    await skill.execute(LLMGenerateInput(instruction="write", context="ctx"), ctx)
    call_kw = llm.create_structured.await_args.kwargs
    assert "未通过校验" in call_kw["user"]
    assert "第 3 次尝试" in call_kw["user"]


@pytest.mark.asyncio
async def test_llm_verify_raises_when_failed() -> None:
    llm = MagicMock()
    llm.create_structured = AsyncMock(
        return_value=LLMVerifyOutput(verify_result="bad", passed=False),
    )
    skill = LLMVerifySkill(llm)
    with pytest.raises(SkillExecutionError):
        await skill.execute(LLMVerifyInput(artifact="a", criteria="c"), {})
