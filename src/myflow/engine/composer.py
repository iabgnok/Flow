from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from myflow.engine.cache import ChampionCache
from myflow.engine.models import ValidationReport, WorkflowModel
from myflow.engine.skill_registry import SkillRegistry
from myflow.engine.validator import WorkflowValidator
from myflow.infra.config import AppConfig
from myflow.infra.llm_client import LLMClient


def _prompts_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "prompts"


@dataclass(frozen=True)
class ComposeOutcome:
    """compose_until_valid 的完整结果（含尝试次数与缓存命中）。"""

    workflow: WorkflowModel
    report: ValidationReport
    attempts: int
    from_cache: bool = False


class WorkflowComposer:
    """自然语言需求 → WorkflowModel；结合 Validator 做错误回流。"""

    def __init__(
        self,
        llm_client: LLMClient,
        registry: SkillRegistry,
        config: AppConfig,
        cache: ChampionCache | None = None,
    ):
        self.llm = llm_client
        self.registry = registry
        self.config = config
        self.validator = WorkflowValidator()
        self.cache = cache

    def _system_prompt(self) -> str:
        template = (_prompts_dir() / "composer_system.md").read_text(encoding="utf-8")
        return template.format(
            skill_cards=self.registry.skill_cards_as_prompt(),
            examples=self._load_examples(),
        )

    def _load_examples(self) -> str:
        """从 prompts/examples 读取 few-shot YAML。

        与 `prompts/composer_system.md`「few-shot 说明」一致：这里放**完整工作流**形态示范；
        增删文件时勿引入「同 action + 同主输入却拆多步」结构，并保留至少一条「合并分析」类正例
        （如 `multi_analysis_assembly.yaml`）。结构约束以系统提示中的「合并判定」为准，不重复堆长例。
        """
        ex_dir = _prompts_dir() / "examples"
        chunks: list[str] = []
        # 固定顺序：纯格式示范（短）；业务意图见 composer_system.md「需求理解规则」
        for name in (
            "linear_simple.yaml",
            "linear_with_llm.yaml",
            "multi_analysis_assembly.yaml",
            "retry_loop.yaml",
            "sub_workflow.yaml",
            "format_terminal_tail.yaml",
        ):
            p = ex_dir / name
            if not p.exists():
                continue
            chunks.append(f"### {name}\n```yaml\n{p.read_text(encoding='utf-8').rstrip()}\n```")
        return "\n\n".join(chunks) if chunks else "(无示例文件)"

    async def compose(
        self,
        requirement: str,
        prev_errors: list[str] | None = None,
        attempt: int = 1,
    ) -> WorkflowModel:
        system = self._system_prompt()
        user_parts = [f"需求: {requirement}"]
        if prev_errors and attempt > 1:
            user_parts.append(f"\n上一次生成未通过校验（第 {attempt} 次尝试），请修正:\n")
            user_parts.append("\n".join(prev_errors))

        return await self.llm.create_structured(
            response_model=WorkflowModel,
            system=system,
            user="\n".join(user_parts),
            max_retries=2,
        )

    async def compose_until_valid(
        self,
        requirement: str,
        max_attempts: int | None = None,
    ) -> ComposeOutcome:
        """生成并校验；失败则把错误摘要回流给 LLM 再试。"""
        cap = max_attempts if max_attempts is not None else self.config.composer_max_attempts

        if self.cache:
            cached = self.cache.get(requirement, self.registry.skill_names)
            if cached is not None:
                report = self.validator.validate(
                    cached,
                    self.registry.skill_names,
                    skill_output_fields=self.registry.skill_output_field_sets(),
                )
                if report.execution_ready():
                    return ComposeOutcome(cached, report, 0, from_cache=True)

        prev: list[str] | None = None
        last_report: ValidationReport | None = None
        workflow: WorkflowModel | None = None
        for attempt in range(1, cap + 1):
            workflow = await self.compose(requirement, prev, attempt)
            report = self.validator.validate(
                workflow,
                self.registry.skill_names,
                skill_output_fields=self.registry.skill_output_field_sets(),
            )
            last_report = report
            if report.execution_ready():
                if self.cache:
                    self.cache.put(requirement, workflow, self.registry.skill_names)
                return ComposeOutcome(workflow, report, attempt, from_cache=False)
            summary = report.compose_feedback_summary()
            prev = [line for line in summary.splitlines() if line.strip()]
            if not prev:
                prev = [summary]
        assert last_report is not None and workflow is not None
        return ComposeOutcome(workflow, last_report, cap, from_cache=False)
