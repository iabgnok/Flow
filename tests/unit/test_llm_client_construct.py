from __future__ import annotations

import pytest

from myflow.infra.config import AppConfig
from myflow.infra.llm_client import LLMClient


def test_llm_client_openai_with_custom_base_url() -> None:
    cfg = AppConfig(llm_provider="openai", llm_api_key="sk-test", llm_base_url="http://127.0.0.1:9/v1")
    c = LLMClient(cfg)
    assert c._openai_direct is not None


def test_llm_client_deepseek_uses_default_base_when_empty() -> None:
    cfg = AppConfig(llm_provider="deepseek", llm_api_key="k", llm_base_url="")
    c = LLMClient(cfg)
    assert c._openai_direct is not None


def test_llm_client_unknown_provider() -> None:
    cfg = AppConfig(llm_provider="not_a_real_provider", llm_api_key="x")
    with pytest.raises(ValueError, match="不支持的 LLM"):
        LLMClient(cfg)
