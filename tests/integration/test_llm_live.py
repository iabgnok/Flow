"""
真实 LLM 调用（可选）。

默认跳过，避免无密钥或误消耗额度。启用方式：

  Windows PowerShell::

    $env:MYFLOW_RUN_LLM_TESTS = '1'
    uv run --group dev pytest tests/integration/test_llm_live.py -v

  先确保项目根目录 `.env` 已配置 ``MYFLOW_LLM_API_KEY``，
  ``MYFLOW_LLM_PROVIDER`` / ``MYFLOW_LLM_MODEL`` 与厂商一致。
"""

from __future__ import annotations

import os

import pytest
from pydantic import BaseModel, Field

from myflow.infra.config import AppConfig
from myflow.infra.llm_client import LLMClient


def _env_flag_on() -> bool:
    v = os.environ.get("MYFLOW_RUN_LLM_TESTS", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _skip_reason() -> str:
    if not _env_flag_on():
        return "设置环境变量 MYFLOW_RUN_LLM_TESTS=1 以开启（会请求真实 API 并计费）"
    cfg = AppConfig()
    if not str(cfg.llm_api_key).strip():
        return "需在 .env 中配置 MYFLOW_LLM_API_KEY（或导出到环境变量）"
    return ""


def _should_skip_live() -> bool:
    return bool(_skip_reason())


skip_if_no_live_llm = pytest.mark.skipif(_should_skip_live(), reason=_skip_reason() or "skip")


class _OneWord(BaseModel):
    word: str = Field(description="一个英文单词，表示肯定，例如 ok")


@pytest.mark.asyncio
@skip_if_no_live_llm
async def test_live_create_text_non_empty() -> None:
    """文本补全：应返回非空字符串。"""
    cfg = AppConfig()
    client = LLMClient(cfg)
    text = await client.create_text(
        system="You reply with minimal text only.",
        user='Reply with exactly the single word: ping',
    )
    assert isinstance(text, str)
    assert text.strip(), "期望模型返回非空文本"


@pytest.mark.asyncio
@skip_if_no_live_llm
async def test_live_create_structured_pydantic() -> None:
    """结构化输出：instructor + 厂商 API 整条链路。"""
    cfg = AppConfig()
    client = LLMClient(cfg)
    result = await client.create_structured(
        response_model=_OneWord,
        system="Follow the schema. Be concise.",
        user='Fill field `word` with exactly: ok',
        max_retries=2,
    )
    assert isinstance(result, _OneWord)
    assert result.word.strip()
