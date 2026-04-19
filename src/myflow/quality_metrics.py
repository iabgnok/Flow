"""§13.3 质量指标：从单次生成结果与样本列表计算比率（纯函数，便于单测）。"""

from __future__ import annotations

from dataclasses import dataclass

from myflow.engine.models import ValidationReport, WorkflowModel


def all_actions_whitelisted(workflow: WorkflowModel, skill_names: set[str]) -> bool:
    """技能命中率：所有 step.action 均在白名单内（与是否通过其它校验规则无关）。"""
    return all(step.action in skill_names for step in workflow.steps)


@dataclass(frozen=True)
class GenerationQualityRecord:
    """单次「需求 → 生成工作流」抽样的度量原子。"""

    validation_passed: bool
    skill_hit: bool
    run_completed: bool | None  # None 表示未尝试执行
    attempts: int
    converged_after_retry: bool  # 首轮未过校验但最终通过
    from_cache: bool


def executable_rate(records: list[GenerationQualityRecord]) -> float:
    if not records:
        return 0.0
    return sum(1 for r in records if r.validation_passed) / len(records)


def skill_hit_rate(records: list[GenerationQualityRecord]) -> float:
    if not records:
        return 0.0
    return sum(1 for r in records if r.skill_hit) / len(records)


def e2e_success_rate(records: list[GenerationQualityRecord]) -> float:
    attempted = [r for r in records if r.run_completed is not None]
    if not attempted:
        return 0.0
    return sum(1 for r in attempted if r.run_completed) / len(attempted)


def retry_convergence_rate(records: list[GenerationQualityRecord]) -> float:
    """在「首轮未通过校验但最终校验通过」的样本上，统计占比；无此类样本时返回 1.0（不适用）。"""
    eligible = [r for r in records if r.validation_passed and r.attempts > 1]
    if not eligible:
        return 1.0
    return sum(1 for r in eligible if r.converged_after_retry) / len(eligible)


def format_metrics_report(
    records: list[GenerationQualityRecord],
    *,
    samples_per_requirement: int = 1,
) -> str:
    lines = [
        "── MyFlow 质量抽样报告 ──",
        f"样本数: {len(records)}（每需求重复约 {samples_per_requirement} 次）",
        f"工作流可执行率（校验通过）: {executable_rate(records):.1%}",
        f"技能命中率（action ∈ 白名单）: {skill_hit_rate(records):.1%}",
        f"端到端成功率（已尝试 run 的子集）: {e2e_success_rate(records):.1%}",
        f"重试收敛率（attempts>1 且最终通过）: {retry_convergence_rate(records):.1%}",
        f"缓存命中（from_cache）: {sum(1 for r in records if r.from_cache)}",
    ]
    return "\n".join(lines)


def record_from_compose(
    *,
    report: ValidationReport,
    workflow: WorkflowModel,
    skill_names: set[str],
    attempts: int,
    from_cache: bool,
    run_completed: bool | None,
) -> GenerationQualityRecord:
    skill_hit = all_actions_whitelisted(workflow, skill_names)
    passed = report.execution_ready()
    converged = passed and attempts > 1 and not from_cache
    return GenerationQualityRecord(
        validation_passed=passed,
        skill_hit=skill_hit,
        run_completed=run_completed,
        attempts=attempts,
        converged_after_retry=converged,
        from_cache=from_cache,
    )
