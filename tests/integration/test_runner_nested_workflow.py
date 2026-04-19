"""
Runner 对嵌套子工作流（sub_workflow）的运行测试：多层嵌套、与后续步骤衔接、失败上浮、路径模板。
"""

from __future__ import annotations

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
    """前 N 次 execute 抛错，之后成功；idempotent=False 以免技能级 tenacity 吞失败。"""

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


def _registry_with_flaky(cfg: AppConfig, tmp_flaky: FlakyTickSkill) -> SkillRegistry:
    r = build_default_registry(cfg)
    r.register(tmp_flaky)
    return r


def _runner(tmp_db_path: str) -> tuple[Runner, AppConfig]:
    cfg = AppConfig(db_path=tmp_db_path)
    return Runner(build_default_registry(cfg), StateStore(cfg.db_path), cfg), cfg


def _runner_with_flaky(tmp_db_path: str, flaky: FlakyTickSkill) -> tuple[Runner, AppConfig]:
    cfg = AppConfig(db_path=tmp_db_path)
    return Runner(_registry_with_flaky(cfg, flaky), StateStore(cfg.db_path), cfg), cfg


@pytest.mark.asyncio
async def test_nested_sub_workflow_depth_two(tmp_path, tmp_db_path: str) -> None:
    """祖父 → 父(sub_workflow) → 子(sub_workflow) → 叶(file_reader)，共两层 sub_workflow。"""
    leaf = WorkflowModel(
        name="leaf_read",
        description="",
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
    leaf_yaml = tmp_path / "leaf.yaml"
    save_workflow(leaf_yaml, leaf)

    middle = WorkflowModel(
        name="middle_sub",
        description="",
        inputs={"fp": ParamSpec(type="string", description="")},
        outputs={"file_content": ParamSpec(type="string", description="")},
        steps=[
            WorkflowStep(
                id=1,
                name="call_leaf",
                action="sub_workflow",
                workflow=str(leaf_yaml.resolve()),
                inputs={"file_path": "{{fp}}"},
                outputs={"file_content": "file_content"},
            ),
        ],
    )
    middle_yaml = tmp_path / "middle.yaml"
    save_workflow(middle_yaml, middle)

    top = WorkflowModel(
        name="top_sub",
        description="",
        inputs={"src": ParamSpec(type="string", description="")},
        outputs={"file_content": ParamSpec(type="string", description="")},
        steps=[
            WorkflowStep(
                id=1,
                name="call_middle",
                action="sub_workflow",
                workflow=str(middle_yaml.resolve()),
                inputs={"fp": "{{src}}"},
                outputs={"file_content": "file_content"},
            ),
        ],
    )

    data = tmp_path / "data.txt"
    data.write_text("depth-two", encoding="utf-8")
    runner, _ = _runner(tmp_db_path)
    result = await runner.run(top, initial_context={"src": str(data)})
    assert result.status == "completed"
    assert result.final_context.get("file_content") == "depth-two"
    assert len(result.step_results) == 1
    assert result.step_results[0].action == "sub_workflow"


@pytest.mark.asyncio
async def test_sub_workflow_then_sibling_file_writer(tmp_path, tmp_db_path: str) -> None:
    """父：先 sub_workflow 读内容，再 file_writer 落盘。"""
    child = WorkflowModel(
        name="child_read_only",
        description="",
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
    child_yaml = tmp_path / "child_rw.yaml"
    save_workflow(child_yaml, child)

    src = tmp_path / "in.txt"
    dst = tmp_path / "out.txt"
    src.write_text("chain-write", encoding="utf-8")

    parent = WorkflowModel(
        name="parent_chain",
        description="",
        inputs={
            "in_path": ParamSpec(type="string", description=""),
            "out_path": ParamSpec(type="string", description=""),
        },
        outputs={
            "report_path": ParamSpec(type="string", description=""),
            "bytes_written": ParamSpec(type="string", description=""),
        },
        steps=[
            WorkflowStep(
                id=1,
                name="sub",
                action="sub_workflow",
                workflow=str(child_yaml.resolve()),
                inputs={"file_path": "{{in_path}}"},
                outputs={"file_content": "file_content"},
            ),
            WorkflowStep(
                id=2,
                name="write",
                action="file_writer",
                inputs={"file_path": "{{out_path}}", "content": "{{file_content}}"},
                outputs={"report_path": "report_path", "bytes_written": "bytes_written"},
            ),
        ],
    )

    runner, _ = _runner(tmp_db_path)
    result = await runner.run(
        parent,
        initial_context={"in_path": str(src), "out_path": str(dst)},
    )
    assert result.status == "completed"
    assert dst.read_text(encoding="utf-8") == "chain-write"
    assert len(result.step_results) == 2
    assert result.step_results[0].action == "sub_workflow"
    assert result.step_results[1].action == "file_writer"


@pytest.mark.asyncio
async def test_sub_workflow_child_failure_fails_parent(tmp_path, tmp_db_path: str) -> None:
    """子工作流失败时，父步骤应失败且不再执行后续步。"""
    child = WorkflowModel(
        name="child_bad_path",
        description="",
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
    child_yaml = tmp_path / "child_bad.yaml"
    save_workflow(child_yaml, child)

    parent = WorkflowModel(
        name="parent_fail",
        description="",
        inputs={"p": ParamSpec(type="string", description="")},
        outputs={"file_content": ParamSpec(type="string", description="")},
        steps=[
            WorkflowStep(
                id=1,
                name="sub",
                action="sub_workflow",
                workflow=str(child_yaml.resolve()),
                inputs={"file_path": "{{p}}"},
                outputs={"file_content": "file_content"},
            ),
            WorkflowStep(
                id=2,
                name="never",
                action="file_reader",
                inputs={"file_path": "{{p}}"},
                outputs={"file_content": "file_content"},
            ),
        ],
    )

    runner, _ = _runner(tmp_db_path)
    result = await runner.run(parent, initial_context={"p": str(tmp_path / "nonexistent.txt")})
    assert result.status == "failed"
    assert len(result.step_results) >= 1
    assert result.step_results[0].status == "failed"
    assert any(s.step_id == 1 for s in result.step_results if s.status == "failed")


@pytest.mark.asyncio
async def test_sub_workflow_path_from_context_template(tmp_path, tmp_db_path: str) -> None:
    """step.workflow 支持 {{var}}，由上下文解析为子 YAML 路径。"""
    child = WorkflowModel(
        name="child_tpl",
        description="",
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
    child_yaml = tmp_path / "child_tpl.yaml"
    save_workflow(child_yaml, child)

    parent = WorkflowModel(
        name="parent_tpl",
        description="",
        inputs={
            "fp": ParamSpec(type="string", description=""),
            "child_ref": ParamSpec(type="string", description=""),
        },
        outputs={"file_content": ParamSpec(type="string", description="")},
        steps=[
            WorkflowStep(
                id=1,
                name="sub",
                action="sub_workflow",
                workflow="{{child_ref}}",
                inputs={"file_path": "{{fp}}"},
                outputs={"file_content": "file_content"},
            ),
        ],
    )

    txt = tmp_path / "t.txt"
    txt.write_text("tpl-path", encoding="utf-8")

    runner, _ = _runner(tmp_db_path)
    result = await runner.run(
        parent,
        initial_context={"fp": str(txt), "child_ref": str(child_yaml.resolve())},
    )
    assert result.status == "completed"
    assert result.final_context.get("file_content") == "tpl-path"


@pytest.mark.asyncio
async def test_two_sequential_sub_workflows(tmp_path, tmp_db_path: str) -> None:
    """同一父流程连续两次 sub_workflow；上下文里同名输出以后者为准。"""
    child_a = WorkflowModel(
        name="ca",
        description="",
        inputs={"file_path": ParamSpec(type="string", description="")},
        outputs={"file_content": ParamSpec(type="string", description="")},
        steps=[
            WorkflowStep(
                id=1,
                name="r",
                action="file_reader",
                inputs={"file_path": "{{file_path}}"},
                outputs={"file_content": "file_content"},
            ),
        ],
    )
    path_a = tmp_path / "ca.yaml"
    save_workflow(path_a, child_a)

    f1 = tmp_path / "1.txt"
    f1.write_text("first", encoding="utf-8")

    child_b = WorkflowModel(
        name="cb",
        description="",
        inputs={"file_path": ParamSpec(type="string", description="")},
        outputs={"file_content": ParamSpec(type="string", description="")},
        steps=[
            WorkflowStep(
                id=1,
                name="r2",
                action="file_reader",
                inputs={"file_path": "{{file_path}}"},
                outputs={"file_content": "file_content"},
            ),
        ],
    )
    path_b = tmp_path / "cb.yaml"
    save_workflow(path_b, child_b)

    f2 = tmp_path / "2.txt"
    f2.write_text("second", encoding="utf-8")

    parent = WorkflowModel(
        name="parent_two_sub",
        description="",
        inputs={
            "path1": ParamSpec(type="string", description=""),
            "path2": ParamSpec(type="string", description=""),
        },
        outputs={"file_content": ParamSpec(type="string", description="")},
        steps=[
            WorkflowStep(
                id=1,
                name="s1",
                action="sub_workflow",
                workflow=str(path_a.resolve()),
                inputs={"file_path": "{{path1}}"},
                outputs={"file_content": "file_content"},
            ),
            WorkflowStep(
                id=2,
                name="s2",
                action="sub_workflow",
                workflow=str(path_b.resolve()),
                inputs={"file_path": "{{path2}}"},
                outputs={"file_content": "file_content"},
            ),
        ],
    )

    runner, _ = _runner(tmp_db_path)
    result = await runner.run(parent, initial_context={"path1": str(f1), "path2": str(f2)})
    assert result.status == "completed"
    # 第二次 sub 覆盖 file_content
    assert result.final_context.get("file_content") == "second"
    assert len(result.step_results) == 2
    assert all(sr.status == "success" for sr in result.step_results)


@pytest.fixture()
def flaky_skill() -> FlakyTickSkill:
    return FlakyTickSkill()


@pytest.mark.asyncio
async def test_nested_child_on_fail_retries_then_parent_succeeds(
    tmp_path, tmp_db_path: str, flaky_skill: FlakyTickSkill
) -> None:
    """子 YAML 内含 on_fail 回跳重试；嵌套 Runner 跑完后父 sub_workflow 仍成功。"""
    flaky_skill.reset(fails_before_success=2)

    child = WorkflowModel(
        name="child_retry_loop",
        description="",
        inputs={"file_path": ParamSpec(type="string", description="")},
        outputs={
            "file_content": ParamSpec(type="string", description=""),
            "ok": ParamSpec(type="string", description=""),
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
                name="flaky",
                action="flaky_tick",
                inputs={},
                outputs={"ok": "ok"},
                on_fail=1,
                max_retries=5,
            ),
        ],
    )
    child_yaml = tmp_path / "child_on_fail.yaml"
    save_workflow(child_yaml, child)

    parent = WorkflowModel(
        name="parent_wrap_retry",
        description="",
        inputs={"fp": ParamSpec(type="string", description="")},
        outputs={
            "file_content": ParamSpec(type="string", description=""),
            "ok": ParamSpec(type="string", description=""),
        },
        steps=[
            WorkflowStep(
                id=1,
                name="sub",
                action="sub_workflow",
                workflow=str(child_yaml.resolve()),
                inputs={"file_path": "{{fp}}"},
                outputs={"file_content": "file_content", "ok": "ok"},
            ),
        ],
    )

    src = tmp_path / "src.txt"
    src.write_text("retry-nested", encoding="utf-8")

    runner, _ = _runner_with_flaky(tmp_db_path, flaky_skill)
    result = await runner.run(parent, initial_context={"fp": str(src)})
    assert result.status == "completed"
    assert result.final_context.get("file_content") == "retry-nested"
    assert result.final_context.get("ok") is True
    assert flaky_skill.executions == 3
    assert len(result.step_results) == 1


@pytest.mark.asyncio
async def test_nested_child_on_fail_exhausted_fails_parent(
    tmp_path, tmp_db_path: str, flaky_skill: FlakyTickSkill
) -> None:
    """子工作流 on_fail 用尽仍失败时，父级 sub_workflow 失败。"""
    flaky_skill.reset(fails_before_success=99)

    child = WorkflowModel(
        name="child_never_ok",
        description="",
        inputs={"file_path": ParamSpec(type="string", description="")},
        outputs={"ok": ParamSpec(type="string", description="")},
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
    child_yaml = tmp_path / "child_fail_cap.yaml"
    save_workflow(child_yaml, child)

    parent = WorkflowModel(
        name="parent_wrap_fail",
        description="",
        inputs={"fp": ParamSpec(type="string", description="")},
        outputs={"ok": ParamSpec(type="string", description="")},
        steps=[
            WorkflowStep(
                id=1,
                name="sub",
                action="sub_workflow",
                workflow=str(child_yaml.resolve()),
                inputs={"file_path": "{{fp}}"},
                outputs={"ok": "ok"},
            ),
        ],
    )

    src = tmp_path / "ok.txt"
    src.write_text("x", encoding="utf-8")

    runner, _ = _runner_with_flaky(tmp_db_path, flaky_skill)
    result = await runner.run(parent, initial_context={"fp": str(src)})
    assert result.status == "failed"
    assert result.step_results and result.step_results[0].status == "failed"
