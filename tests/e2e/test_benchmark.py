"""
阶段 4.1 / 4.2：基准需求与质量指标（可选真实 LLM）。

- 默认：桩 Composer，验证 6 条标准需求可走通「生成→校验」骨架。
- ``MYFLOW_RUN_BENCHMARK=1`` 且已配置 ``MYFLOW_LLM_API_KEY``：对 §13.4 的 6 条各调用一次真实 ``compose_until_valid``（计费）。
- ``MYFLOW_BENCHMARK_STRICT=1`` 时（须同时开启 RUN_BENCHMARK）：按 §13.3 对 20 条需求各重复 3 次抽样并 **assert** 阈值（共 60 次生成调用，耗时长、费用高）。
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from myflow.benchmarks import BENCHMARK_REQUIREMENTS, QUALITY_SAMPLE_REQUIREMENTS
from myflow.engine.composer import WorkflowComposer
from myflow.engine.models import ParamSpec, WorkflowModel, WorkflowStep
from myflow.engine.skill_registry import SkillRegistry, build_default_registry
from myflow.infra.config import AppConfig
from myflow.infra.llm_client import LLMClient
from myflow.quality_metrics import (
    executable_rate,
    format_metrics_report,
    record_from_compose,
    skill_hit_rate,
)


def _run_benchmark_on() -> bool:
    v = os.environ.get("MYFLOW_RUN_BENCHMARK", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _strict_benchmark_on() -> bool:
    v = os.environ.get("MYFLOW_BENCHMARK_STRICT", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _skip_live_benchmark_reason() -> str:
    if not _run_benchmark_on():
        return "设置 MYFLOW_RUN_BENCHMARK=1 以开启真实基准（会请求 API 并计费）"
    cfg = AppConfig()
    if not str(cfg.llm_api_key).strip():
        return "需配置 MYFLOW_LLM_API_KEY"
    return ""


skip_live_benchmark = pytest.mark.skipif(
    bool(_skip_live_benchmark_reason()),
    reason=_skip_live_benchmark_reason() or "skip",
)


def test_benchmark_requirements_match_design_doc_count() -> None:
    assert len(BENCHMARK_REQUIREMENTS) == 6


def test_quality_sample_is_twenty_requirements() -> None:
    assert len(QUALITY_SAMPLE_REQUIREMENTS) == 20


@pytest.mark.asyncio
@pytest.mark.parametrize("requirement", BENCHMARK_REQUIREMENTS, ids=[f"b{i}" for i in range(len(BENCHMARK_REQUIREMENTS))])
async def test_each_benchmark_requirement_stub_compose_ok(
    requirement: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无 API：对每条标准需求走通 compose_until_valid（LLM 已桩）。"""
    registry = SkillRegistry()
    from myflow.skills.file_ops import FileReaderSkill

    registry.register(FileReaderSkill())

    wf_ok = WorkflowModel(
        name="stub_benchmark",
        description="stub",
        inputs={"file_path": ParamSpec(type="string", description="p", required=True)},
        steps=[
            WorkflowStep(
                id=1,
                name="read",
                action="file_reader",
                inputs={"file_path": "{{file_path}}"},
                outputs={"file_content": "file_content"},
            ),
        ],
    )

    async def fake_compose(*_a, **_k):
        return wf_ok

    llm = MagicMock()
    composer = WorkflowComposer(llm, registry, AppConfig(composer_max_attempts=2))
    monkeypatch.setattr(composer, "compose", fake_compose)

    outcome = await composer.compose_until_valid(requirement)
    assert outcome.report.execution_ready(), outcome.report.compose_feedback_summary()
    assert outcome.workflow.name == "stub_benchmark"
    assert not outcome.from_cache


@pytest.mark.asyncio
@pytest.mark.benchmark
@skip_live_benchmark
async def test_live_single_pass_per_benchmark_requirement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """真实 LLM：6 条各生成一次，应全部通过校验（软目标；不设 assert 以免模型波动卡 CI）。"""
    monkeypatch.setenv("MYFLOW_CHAMPION_CACHE_ENABLED", "0")
    cfg = AppConfig(
        db_path=str(tmp_path / "s.db"),
        champion_cache_enabled=False,
    )
    registry = build_default_registry(cfg)
    composer = WorkflowComposer(LLMClient(cfg), registry, cfg, cache=None)

    failures: list[str] = []
    for req in BENCHMARK_REQUIREMENTS:
        outcome = await composer.compose_until_valid(req)
        if not outcome.report.execution_ready():
            failures.append(f"{req[:48]}…\n{outcome.report.error_summary()}")

    if failures:
        pytest.fail("以下基准需求未通过校验:\n" + "\n---\n".join(failures))


@pytest.mark.asyncio
@pytest.mark.benchmark
@skip_live_benchmark
async def test_live_quality_strict_thresholds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MYFLOW_BENCHMARK_STRICT=1：20×3 次生成并 assert §13.3 可执行率 / 技能命中率。"""
    if not _strict_benchmark_on():
        pytest.skip("设置 MYFLOW_BENCHMARK_STRICT=1 才会断言阈值（60 次 LLM 生成调用）")

    monkeypatch.setenv("MYFLOW_CHAMPION_CACHE_ENABLED", "0")
    cfg = AppConfig(
        db_path=str(tmp_path / "q.db"),
        champion_cache_enabled=False,
    )
    registry = build_default_registry(cfg)
    composer = WorkflowComposer(LLMClient(cfg), registry, cfg, cache=None)

    records = []
    for req in QUALITY_SAMPLE_REQUIREMENTS:
        for _ in range(3):
            outcome = await composer.compose_until_valid(req)
            records.append(
                record_from_compose(
                    report=outcome.report,
                    workflow=outcome.workflow,
                    skill_names=registry.skill_names,
                    attempts=outcome.attempts,
                    from_cache=outcome.from_cache,
                    run_completed=None,
                )
            )

    text = format_metrics_report(records, samples_per_requirement=3)
    print("\n" + text)
    assert executable_rate(records) >= 0.90
    assert skill_hit_rate(records) >= 0.95
