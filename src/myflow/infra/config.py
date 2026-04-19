from __future__ import annotations

from pydantic_settings import BaseSettings


class AppConfig(BaseSettings):
    # LLM 配置（阶段一不使用，但保留接口）
    llm_provider: str = "anthropic"  # anthropic / openai / deepseek
    llm_model: str = "claude-sonnet-4-20250514"
    llm_api_key: str = ""
    # 可选：自定义 OpenAI 兼容网关（如自建代理）；deepseek 未填时默认为官方 https://api.deepseek.com
    llm_base_url: str = ""
    llm_temperature: float = 0.3

    # 存储配置
    db_path: str = "myflow_state.db"
    workflows_dir: str = "workflows"

    # 执行配置
    max_global_retries: int = 5
    default_step_retries: int = 3

    # Composer：校验失败后的最大重新生成次数（含首轮）
    composer_max_attempts: int = 5

    # Champion 缓存：校验通过的工作流按需求指纹落盘，命中则跳过 LLM
    champion_cache_enabled: bool = True
    champion_cache_dir: str = ".myflow/champion_cache"

    # 结构化调试日志（structlog）；也可用环境变量 MYFLOW_DEBUG=1
    debug: bool = False

    model_config = {"env_prefix": "MYFLOW_", "env_file": ".env"}

