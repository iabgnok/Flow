from __future__ import annotations

import instructor
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic import BaseModel

from myflow.infra.config import AppConfig

_DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com"


class LLMClient:
    """
    LLM 调用封装。使用 instructor 将 LLM 输出约束为 Pydantic 模型。
    - Anthropic：原生 messages API。
    - OpenAI / DeepSeek：chat.completions（DeepSeek 官方为 OpenAI 兼容协议，仅需设置 base_url）。
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self._openai_direct: AsyncOpenAI | None = None

        if config.llm_provider == "anthropic":
            self._instructor_client = instructor.from_anthropic(AsyncAnthropic(api_key=config.llm_api_key))
        elif config.llm_provider in ("openai", "deepseek"):
            self._openai_direct = self._build_async_openai()
            self._instructor_client = instructor.from_openai(self._openai_direct)
        else:
            raise ValueError(f"不支持的 LLM 提供商: {config.llm_provider}")

    def _build_async_openai(self) -> AsyncOpenAI:
        if self.config.llm_provider == "openai":
            kwargs: dict[str, str] = {"api_key": self.config.llm_api_key}
            if self.config.llm_base_url.strip():
                kwargs["base_url"] = self.config.llm_base_url.strip()
            return AsyncOpenAI(**kwargs)
        if self.config.llm_provider == "deepseek":
            base = self.config.llm_base_url.strip() or _DEEPSEEK_DEFAULT_BASE_URL
            return AsyncOpenAI(api_key=self.config.llm_api_key, base_url=base)
        raise RuntimeError("internal: expected openai or deepseek")

    def _is_anthropic(self) -> bool:
        return self.config.llm_provider == "anthropic"

    async def create_structured(
        self,
        response_model: type[BaseModel],
        system: str,
        user: str,
        max_retries: int = 2,
    ) -> BaseModel:
        """调用 LLM 并返回类型化的 Pydantic 对象。"""
        if self._is_anthropic():
            return await self._instructor_client.messages.create(
                model=self.config.llm_model,
                max_tokens=8192,
                system=system,
                messages=[{"role": "user", "content": user}],
                response_model=response_model,
                max_retries=max_retries,
                temperature=self.config.llm_temperature,
            )
        return await self._instructor_client.chat.completions.create(
            model=self.config.llm_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_model=response_model,
            max_retries=max_retries,
            temperature=self.config.llm_temperature,
        )

    async def create_text(self, system: str, user: str) -> str:
        """普通文本调用（Skill 内部可选用）。"""
        if self._is_anthropic():
            raw = AsyncAnthropic(api_key=self.config.llm_api_key)
            resp = await raw.messages.create(
                model=self.config.llm_model,
                max_tokens=8192,
                system=system,
                messages=[{"role": "user", "content": user}],
                temperature=self.config.llm_temperature,
            )
            block = resp.content[0]
            text = getattr(block, "text", None)
            return text if isinstance(text, str) else str(block)

        assert self._openai_direct is not None
        resp = await self._openai_direct.chat.completions.create(
            model=self.config.llm_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self.config.llm_temperature,
        )
        msg = resp.choices[0].message
        content = msg.content
        return (content or "").strip()
