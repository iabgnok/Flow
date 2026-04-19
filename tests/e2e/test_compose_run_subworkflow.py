"""
E2E：自然语言需求 → Composer 生成含 sub_workflow 的父工作流 → Runner 执行成功。

与 `tests/integration/test_llm_live.py` 相同，默认跳过，避免无密钥或误消耗额度。

启用示例（PowerShell）::

    $env:MYFLOW_RUN_LLM_TESTS = '1'
    uv run pytest tests/e2e/test_compose_run_subworkflow.py -v

需已配置 ``MYFLOW_LLM_API_KEY``（及与厂商一致的 provider/model）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from myflow.engine.composer import WorkflowComposer
from myflow.engine.models import ParamSpec, WorkflowModel, WorkflowStep
from myflow.engine.runner import Runner
from myflow.engine.skill_registry import build_default_registry
from myflow.engine.validator import WorkflowValidator
from myflow.engine.workflow_io import dump_workflow, save_workflow
from myflow.infra.config import AppConfig
from myflow.infra.llm_client import LLMClient
from myflow.infra.state_store import StateStore


def _env_flag_on() -> bool:
    v = os.environ.get("MYFLOW_RUN_LLM_TESTS", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _skip_reason() -> str:
    if not _env_flag_on():
        return "设置 MYFLOW_RUN_LLM_TESTS=1 以开启（会请求真实 API 并计费）"
    cfg = AppConfig()
    if not str(cfg.llm_api_key).strip():
        return "需配置 MYFLOW_LLM_API_KEY"
    return ""


skip_if_no_live_llm = pytest.mark.skipif(bool(_skip_reason()), reason=_skip_reason() or "skip")


def _write_child_reader(child_path: Path) -> None:
    child = WorkflowModel(
        name="child_reader",
        description="仅读取文件，供父工作流 sub_workflow 调用",
        inputs={"file_path": ParamSpec(type="string", description="源文件路径", required=True)},
        outputs={"file_content": ParamSpec(type="string", description="文件文本", required=True)},
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
    child_path.write_text(dump_workflow(child), encoding="utf-8")


@pytest.mark.asyncio
@skip_if_no_live_llm
async def test_compose_parent_with_sub_workflow_then_run_ok(
    tmp_path: Path, tmp_db_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """子 YAML 预先落盘；需求明确要求 sub_workflow；生成后跑一次并校验产物。"""
    monkeypatch.setenv("MYFLOW_WORKFLOWS_DIR", str(tmp_path.resolve()))

    child_path = tmp_path / "child_reader.yaml"
    _write_child_reader(child_path)
    assert child_path.is_file()

    cfg = AppConfig(db_path=tmp_db_path)
    registry = build_default_registry(cfg)
    composer = WorkflowComposer(LLMClient(cfg), registry, cfg)

    requirement = """请生成一个可执行的父工作流，并满足以下硬约束：

1. 父工作流 name 必须为 parent_with_sub。
2. 父工作流 inputs：in_file、out_file，均为必填 string，表示源文件路径与要写入的目标文件路径。
3. 第一步：action 必须是 sub_workflow；workflow 字段填相对工作流目录的路径字符串 child_reader.yaml（整段路径不要用双花括号模板包裹）。
   该步 inputs 中 file_path 必须使用与其它步骤相同的模板语法引用工作流入参 in_file。
   该步 outputs 必须包含 file_content。
4. 第二步：action 为 file_writer；file_path 引用 out_file，content 引用 file_content（同样使用标准双花括号模板）。
5. 父工作流 outputs 声明 file_writer 写入上下文的字段（与 file_writer 技能输出字段一致或为其子集）。

子工作流文件已存在于同一工作流目录，文件名为 child_reader.yaml，仅含一步 file_reader。
不要添加与子需求无关的步骤。"""

    outcome = await composer.compose_until_valid(requirement)
    wf, report = outcome.workflow, outcome.report
    assert report.execution_ready(), report.compose_feedback_summary()

    assert wf.name == "parent_with_sub", f"期望 name=parent_with_sub，实际 {wf.name!r}"
    sub_steps = [s for s in wf.steps if s.action == "sub_workflow"]
    assert len(sub_steps) == 1, f"期望恰好一步 sub_workflow，实际步骤: {[s.action for s in wf.steps]}"
    child_rel = "child_reader.yaml"
    assert sub_steps[0].workflow and child_rel in (sub_steps[0].workflow or ""), sub_steps[0].workflow

    parent_yaml = tmp_path / "parent_with_sub.yaml"
    save_workflow(parent_yaml, wf)
    v2 = WorkflowValidator().validate(
        wf,
        registry.skill_names,
        skill_output_fields=registry.skill_output_field_sets(),
    )
    assert v2.passed, v2.error_summary()

    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_text("e2e-subworkflow-hello", encoding="utf-8")

    runner = Runner(registry, StateStore(cfg.db_path), cfg)
    result = await runner.run(
        wf,
        initial_context={"in_file": str(src.resolve()), "out_file": str(dst.resolve())},
    )
    assert result.status == "completed", result.error
    assert dst.read_text(encoding="utf-8") == "e2e-subworkflow-hello"
