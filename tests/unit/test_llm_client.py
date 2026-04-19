from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from myflow.infra.config import AppConfig
from myflow.infra.llm_client import LLMClient


class _M(BaseModel):
    x: int = 1


@pytest.mark.asyncio
async def test_create_structured_anthropic_delegates() -> None:
    cfg = AppConfig(llm_provider="anthropic", llm_api_key="k", llm_model="m")
    with patch("myflow.infra.llm_client.instructor") as inst:
        create = AsyncMock(return_value=_M(x=2))
        inst.from_anthropic.return_value = MagicMock(
            messages=MagicMock(create=create),
        )
        c = LLMClient(cfg)
        r = await c.create_structured(_M, "sys", "user", max_retries=1)
        assert r.x == 2
        create.assert_awaited_once()
        _, kwargs = create.call_args
        assert kwargs["response_model"] is _M
        assert kwargs["system"] == "sys"


@pytest.mark.asyncio
async def test_create_structured_openai_delegates() -> None:
    cfg = AppConfig(llm_provider="openai", llm_api_key="k", llm_model="m")
    with patch("myflow.infra.llm_client.instructor") as inst:
        create = AsyncMock(return_value=_M())
        inst.from_openai.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(create=create)),
        )
        c = LLMClient(cfg)
        await c.create_structured(_M, "s", "u")
        create.assert_awaited_once()


def test_deepseek_uses_openai_sdk_with_official_base_url() -> None:
    cfg = AppConfig(llm_provider="deepseek", llm_api_key="k", llm_model="deepseek-chat")
    with patch("myflow.infra.llm_client.AsyncOpenAI") as ao, patch("myflow.infra.llm_client.instructor") as inst:
        inst.from_openai.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(create=AsyncMock(return_value=_M()))),
        )
        LLMClient(cfg)
        ao.assert_called_once()
        _, kwargs = ao.call_args
        assert kwargs["api_key"] == "k"
        assert kwargs["base_url"] == "https://api.deepseek.com"


def test_deepseek_custom_base_url_override() -> None:
    cfg = AppConfig(
        llm_provider="deepseek",
        llm_api_key="k",
        llm_model="deepseek-chat",
        llm_base_url="https://api.deepseek.com/v1",
    )
    with patch("myflow.infra.llm_client.AsyncOpenAI") as ao, patch("myflow.infra.llm_client.instructor") as inst:
        inst.from_openai.return_value = MagicMock()
        LLMClient(cfg)
        _, kwargs = ao.call_args
        assert kwargs["base_url"] == "https://api.deepseek.com/v1"


def test_unknown_provider_raises() -> None:
    cfg = AppConfig(llm_provider="bad")
    with pytest.raises(ValueError):
        LLMClient(cfg)
