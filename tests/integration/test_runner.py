from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from myflow.engine.models import ParamSpec, WorkflowModel, WorkflowStep
from myflow.engine.runner import Runner
from myflow.engine.skill_registry import SkillRegistry, build_default_registry
from myflow.engine.workflow_io import save_workflow
from myflow.infra.config import AppConfig
from myflow.infra.state_store import StateStore
from myflow.skills.base import Skill, SkillExecutionError


class _FlakyIn(BaseModel):
    pass


class _FlakyOut(BaseModel):
    ok: bool = True


class FlakyTickSkill(Skill):
    """仅用于集成测试：前 N 次 execute 抛错，之后成功。需 idempotent=False 以免 tenacity 吞掉失败。"""

    name = "flaky_tick"
    description = "test"
    when_to_use = "test"
    do_not_use_when = ""
    idempotent = False
    input_model = _FlakyIn
    output_model = _FlakyOut

    fails_before_success: int = 0
    executions: int = 0

    def __init__(self) -> None:
        super().__init__()
        self.executions = 0

    def reset(self, fails_before_success: int) -> None:
        self.fails_before_success = fails_before_success
        self.executions = 0

    async def execute(self, inputs: _FlakyIn, context: dict) -> _FlakyOut:
        self.executions += 1
        if self.executions <= self.fails_before_success:
            raise SkillExecutionError("retry me")
        return _FlakyOut(ok=True)


def _registry_with_flaky(tmp_flaky: FlakyTickSkill) -> SkillRegistry:
    r = build_default_registry()
    r.register(tmp_flaky)
    return r


@pytest.mark.asyncio
async def test_linear_workflow_completes(tmp_path: Path, tmp_db_path: str) -> None:
    in_file = tmp_path / "in.txt"
    out_file = tmp_path / "out.txt"
    in_file.write_text("hello", encoding="utf-8")

    wf = WorkflowModel(
        name="w",
        description="d",
        inputs={
            "file_path": ParamSpec(type="string", description=""),
            "output_path": ParamSpec(type="string", description=""),
        },
        steps=[
            WorkflowStep(
                id=1,
                name="read",
                action="file_reader",
                inputs={"file_path": "{{file_path}}"},
                outputs={"file_content": "file_content"},
            ),
            WorkflowStep(
                id=2,
                name="write",
                action="file_writer",
                inputs={"file_path": "{{output_path}}", "content": "{{file_content}}"},
                outputs={"report_path": "report_path", "bytes_written": "bytes_written"},
            ),
        ],
    )

    config = AppConfig(db_path=tmp_db_path)
    runner = Runner(build_default_registry(config), StateStore(config.db_path), config)
    result = await runner.run(wf, initial_context={"file_path": str(in_file), "output_path": str(out_file)})
    assert result.status == "completed"
    assert out_file.read_text(encoding="utf-8") == "hello"

    store_chk = StateStore(config.db_path)
    await store_chk.init()
    logged = await store_chk.load_steps(result.run_id)
    assert len(logged) >= 2
    assert all(r.get("duration_ms") is not None for r in logged)
    assert all(int(r["duration_ms"]) >= 0 for r in logged)


@pytest.mark.asyncio
async def test_condition_skips_step(tmp_path: Path, tmp_db_path: str) -> None:
    in_file = tmp_path / "in.txt"
    out_file = tmp_path / "out.txt"
    in_file.write_text("hello", encoding="utf-8")

    wf = WorkflowModel(
        name="w",
        description="d",
        inputs={
            "file_path": ParamSpec(type="string", description=""),
            "output_path": ParamSpec(type="string", description=""),
        },
        steps=[
            WorkflowStep(
                id=1,
                name="read",
                action="file_reader",
                inputs={"file_path": "{{file_path}}"},
                outputs={"file_content": "file_content"},
            ),
            WorkflowStep(
                id=2,
                name="write",
                action="file_writer",
                condition="False",
                inputs={"file_path": "{{output_path}}", "content": "{{file_content}}"},
                outputs={"report_path": "report_path", "bytes_written": "bytes_written"},
            ),
        ],
    )

    config = AppConfig(db_path=tmp_db_path)
    runner = Runner(build_default_registry(config), StateStore(config.db_path), config)
    result = await runner.run(wf, initial_context={"file_path": str(in_file), "output_path": str(out_file)})
    assert result.status == "completed"
    assert not out_file.exists()
    assert any(sr.step_id == 2 and sr.status == "skipped" for sr in result.step_results)


@pytest.fixture()
def flaky_skill() -> FlakyTickSkill:
    return FlakyTickSkill()


@pytest.mark.asyncio
async def test_unknown_action_fails_before_execution(tmp_path: Path, tmp_db_path: str) -> None:
    """未注册技能在 Runner 校验阶段失败（与 SkillRegistry 白名单一致）。"""
    wf = WorkflowModel(
        name="bad",
        description="d",
        steps=[WorkflowStep(id=1, name="n", action="not_registered", outputs={"x": "file_content"})],
    )
    config = AppConfig(db_path=tmp_db_path)
    runner = Runner(build_default_registry(config), StateStore(config.db_path), config)
    result = await runner.run(wf, initial_context={})
    assert result.status == "failed"
    assert result.error and "校验失败" in result.error


@pytest.mark.asyncio
async def test_on_fail_retries_then_succeeds(
    tmp_path: Path, tmp_db_path: str, flaky_skill: FlakyTickSkill
) -> None:
    in_file = tmp_path / "in.txt"
    in_file.write_text("x", encoding="utf-8")

    flaky_skill.reset(fails_before_success=2)

    wf = WorkflowModel(
        name="retry_wf",
        description="d",
        inputs={"file_path": ParamSpec(type="string", description="")},
        steps=[
            WorkflowStep(
                id=1,
                name="read",
                action="file_reader",
                inputs={"file_path": "{{file_path}}"},
                outputs={"file_content": "file_content"},
            ),
            WorkflowStep(
                id=2,
                name="flaky",
                action="flaky_tick",
                inputs={},
                outputs={"ok": "ok"},
                on_fail=1,
                max_retries=5,
            ),
        ],
    )

    config = AppConfig(db_path=tmp_db_path)
    runner = Runner(_registry_with_flaky(flaky_skill), StateStore(config.db_path), config)
    result = await runner.run(wf, initial_context={"file_path": str(in_file)})
    assert result.status == "completed"
    assert flaky_skill.executions == 3
    assert result.step_results[-1].step_id == 2
    assert result.step_results[-1].status == "success"


@pytest.mark.asyncio
async def test_max_retries_stops_on_fail_loop(
    tmp_path: Path, tmp_db_path: str, flaky_skill: FlakyTickSkill
) -> None:
    in_file = tmp_path / "in.txt"
    in_file.write_text("x", encoding="utf-8")

    flaky_skill.reset(fails_before_success=99)

    wf = WorkflowModel(
        name="retry_cap",
        description="d",
        inputs={"file_path": ParamSpec(type="string", description="")},
        steps=[
            WorkflowStep(
                id=1,
                name="read",
                action="file_reader",
                inputs={"file_path": "{{file_path}}"},
                outputs={"file_content": "file_content"},
            ),
            WorkflowStep(
                id=2,
                name="flaky",
                action="flaky_tick",
                inputs={},
                outputs={"ok": "ok"},
                on_fail=1,
                max_retries=1,
            ),
        ],
    )

    config = AppConfig(db_path=tmp_db_path)
    runner = Runner(_registry_with_flaky(flaky_skill), StateStore(config.db_path), config)
    result = await runner.run(wf, initial_context={"file_path": str(in_file)})
    assert result.status == "failed"
    assert result.error and "Step 2" in result.error


@pytest.mark.asyncio
async def test_checkpoint_resumes_from_saved_step(tmp_path: Path, tmp_db_path: str) -> None:
    """模拟上次在 step 2 开始前中断：库中已有 file_content，从 step 2 续跑只执行写入。"""
    in_file = tmp_path / "in.txt"
    out_file = tmp_path / "out.txt"
    in_file.write_text("hello", encoding="utf-8")

    wf = WorkflowModel(
        name="w",
        description="d",
        inputs={
            "file_path": ParamSpec(type="string", description=""),
            "output_path": ParamSpec(type="string", description=""),
        },
        steps=[
            WorkflowStep(
                id=1,
                name="read",
                action="file_reader",
                inputs={"file_path": "{{file_path}}"},
                outputs={"file_content": "file_content"},
            ),
            WorkflowStep(
                id=2,
                name="write",
                action="file_writer",
                inputs={"file_path": "{{output_path}}", "content": "{{file_content}}"},
                outputs={"report_path": "report_path", "bytes_written": "bytes_written"},
            ),
        ],
    )

    run_id = "integration-resume-1"
    store = StateStore(tmp_db_path)
    await store.init()
    merged_ctx = {
        "file_path": str(in_file),
        "output_path": str(out_file),
        "file_content": "hello",
    }
    await store.save_run(run_id, wf.name, "running", merged_ctx, current_step_id=2)

    config = AppConfig(db_path=tmp_db_path)
    runner = Runner(build_default_registry(config), store, config)
    result = await runner.run(
        wf,
        initial_context={"file_path": str(in_file), "output_path": str(out_file)},
        run_id=run_id,
    )
    assert result.status == "completed"
    assert out_file.read_text(encoding="utf-8") == "hello"
    assert len(result.step_results) == 1
    assert result.step_results[0].step_id == 2
    assert result.step_results[0].status == "success"


@pytest.mark.asyncio
async def test_unknown_cli_input_key_fails_fast(tmp_path: Path, tmp_db_path: str) -> None:
    in_file = tmp_path / "in.txt"
    out_file = tmp_path / "out.txt"
    in_file.write_text("hello", encoding="utf-8")

    wf = WorkflowModel(
        name="w",
        description="d",
        inputs={
            "file_path": ParamSpec(type="string", description=""),
            "output_path": ParamSpec(type="string", description=""),
        },
        steps=[
            WorkflowStep(
                id=1,
                name="read",
                action="file_reader",
                inputs={"file_path": "{{file_path}}"},
                outputs={"file_content": "file_content"},
            ),
            WorkflowStep(
                id=2,
                name="write",
                action="file_writer",
                inputs={"file_path": "{{output_path}}", "content": "{{file_content}}"},
                outputs={"report_path": "report_path", "bytes_written": "bytes_written"},
            ),
        ],
    )

    config = AppConfig(db_path=tmp_db_path)
    runner = Runner(build_default_registry(config), StateStore(config.db_path), config)
    result = await runner.run(
        wf,
        initial_context={"file_path": str(in_file), "out_path": str(out_file)},
    )
    assert result.status == "failed"
    assert result.step_results == []
    assert result.error
    assert "未知的 --input 参数" in result.error
    assert "out_path" in result.error


@pytest.mark.asyncio
async def test_missing_required_input_fails_fast(tmp_path: Path, tmp_db_path: str) -> None:
    in_file = tmp_path / "in.txt"
    in_file.write_text("hello", encoding="utf-8")

    wf = WorkflowModel(
        name="w",
        description="d",
        inputs={
            "file_path": ParamSpec(type="string", description=""),
            "output_path": ParamSpec(type="string", description=""),
        },
        steps=[
            WorkflowStep(
                id=1,
                name="read",
                action="file_reader",
                inputs={"file_path": "{{file_path}}"},
                outputs={"file_content": "file_content"},
            ),
            WorkflowStep(
                id=2,
                name="write",
                action="file_writer",
                inputs={"file_path": "{{output_path}}", "content": "{{file_content}}"},
                outputs={"report_path": "report_path", "bytes_written": "bytes_written"},
            ),
        ],
    )

    config = AppConfig(db_path=tmp_db_path)
    runner = Runner(build_default_registry(config), StateStore(config.db_path), config)
    result = await runner.run(wf, initial_context={"file_path": str(in_file)})
    assert result.status == "failed"
    assert result.step_results == []
    assert result.error
    assert "缺少必填" in result.error
    assert "output_path" in result.error


@pytest.mark.asyncio
async def test_sub_workflow_merges_child_outputs(tmp_path: Path, tmp_db_path: str) -> None:
    child = WorkflowModel(
        name="child",
        description="c",
        inputs={"file_path": ParamSpec(type="string", description="")},
        outputs={"file_content": ParamSpec(type="string", description="")},
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
    child_yaml = tmp_path / "child.yaml"
    save_workflow(child_yaml, child)

    parent = WorkflowModel(
        name="parent",
        description="p",
        inputs={"fp": ParamSpec(type="string", description="")},
        outputs={"file_content": ParamSpec(type="string", description="")},
        steps=[
            WorkflowStep(
                id=1,
                name="nest",
                action="sub_workflow",
                workflow=str(child_yaml.resolve()),
                inputs={"file_path": "{{fp}}"},
                outputs={"file_content": "file_content"},
            ),
        ],
    )

    txt = tmp_path / "data.txt"
    txt.write_text("nested-ok", encoding="utf-8")

    cfg = AppConfig(db_path=tmp_db_path)
    runner = Runner(build_default_registry(cfg), StateStore(cfg.db_path), cfg)
    result = await runner.run(parent, initial_context={"fp": str(txt)})
    assert result.status == "completed"
    assert result.final_context.get("file_content") == "nested-ok"


def test_runner_resolves_single_brace_placeholder(tmp_db_path: str) -> None:
    """Composer 误生成 {var} 时与 {{var}} 一致，应能从 context 取值。"""
    cfg = AppConfig(db_path=tmp_db_path)
    runner = Runner(build_default_registry(cfg), StateStore(cfg.db_path), cfg)
    ctx = {"pdf_file_path": "/data/paper.txt"}
    assert runner._resolve_template_value("{pdf_file_path}", ctx) == "/data/paper.txt"
    assert runner._resolve_template_value("{{pdf_file_path}}", ctx) == "/data/paper.txt"


def test_runner_resolves_embedded_template_interpolation(tmp_db_path: str) -> None:
    """P1：字符串内插，多占位符替换为 str(值)。"""
    cfg = AppConfig(db_path=tmp_db_path)
    runner = Runner(build_default_registry(cfg), StateStore(cfg.db_path), cfg)
    ctx = {"lang": "en", "text": "hi"}
    assert (
        runner._resolve_template_value("翻译为{{lang}}：{{text}}", ctx) == "翻译为en：hi"
    )
    # 整段单引用仍保留非 str 类型
    ctx2 = {"n": 42}
    assert runner._resolve_template_value("{{n}}", ctx2) == 42


@pytest.mark.asyncio
async def test_multi_file_reader_merges_files(tmp_path: Path, tmp_db_path: str) -> None:
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("A", encoding="utf-8")
    b.write_text("B", encoding="utf-8")

    wf = WorkflowModel(
        name="m",
        description="d",
        steps=[
            WorkflowStep(
                id=1,
                name="read_many",
                action="file_reader",
                inputs={"paths": f"{a},{b}"},
                outputs={"files_map": "file_content"},
            ),
        ],
    )
    cfg = AppConfig(db_path=tmp_db_path)
    runner = Runner(build_default_registry(cfg), StateStore(cfg.db_path), cfg)
    result = await runner.run(wf, initial_context={})
    assert result.status == "completed"
    merged = result.final_context["files_map"]
    assert "=== " in merged and "A" in merged and "B" in merged


@pytest.mark.asyncio
async def test_resolve_run_id_unique_prefix(tmp_db_path: str) -> None:
    rid = "abcd0123ef456789abcdef0123456789"
    store = StateStore(tmp_db_path)
    await store.init()
    await store.save_run(rid, "demo", "completed", {})
    assert await store.resolve_run_id("abcd0123") == rid

