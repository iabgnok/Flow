from __future__ import annotations

from io import StringIO
from pathlib import Path

from rich.console import Console

from myflow.display import Display
from myflow.engine.models import (
    ParamSpec,
    RunResult,
    StepResult,
    ValidationIssue,
    ValidationReport,
    WorkflowModel,
    WorkflowStep,
)


def test_completed_final_echo_skips_when_last_is_file_writer() -> None:
    buf = StringIO()
    c = Console(file=buf, force_terminal=True, width=120)
    d = Display(c)
    rr = RunResult(
        run_id="abc",
        workflow_name="w",
        status="completed",
        step_results=[
            StepResult(step_id=1, step_name="a", action="llm_analyze", status="success", outputs={"x": "y"}),
            StepResult(step_id=2, step_name="w", action="file_writer", status="success", outputs={}),
        ],
    )
    d.completed_final_echo(rr)
    assert "结果" not in buf.getvalue()


def test_completed_final_echo_shows_last_non_writer_outputs() -> None:
    buf = StringIO()
    c = Console(file=buf, force_terminal=True, width=120)
    d = Display(c)
    rr = RunResult(
        run_id="abc",
        workflow_name="w",
        status="completed",
        step_results=[
            StepResult(
                step_id=1,
                step_name="a",
                action="llm_analyze",
                status="success",
                outputs={"analysis": "ok"},
            ),
        ],
    )
    d.completed_final_echo(rr)
    out = buf.getvalue()
    assert "结果" in out
    assert "analysis" in out


def test_format_output_value_truncates_long_string() -> None:
    buf = StringIO()
    c = Console(file=buf, force_terminal=True, width=120)
    d = Display(c)
    long_s = "x" * 700
    sr = StepResult(
        step_id=1,
        step_name="s",
        action="llm_generate",
        status="success",
        outputs={"t": long_s},
    )
    d.step_outputs(sr)
    body = buf.getvalue()
    assert "省略" in body


def test_run_result_shows_error_panel() -> None:
    buf = StringIO()
    c = Console(file=buf, force_terminal=True, width=120)
    d = Display(c)
    rr = RunResult(
        run_id="deadbeef",
        workflow_name="w",
        status="failed",
        step_results=[
            StepResult(step_id=1, step_name="s", action="file_reader", status="failed", error="boom"),
        ],
        error="top level",
    )
    d.run_result(rr)
    text = buf.getvalue()
    assert "failed" in text or "Error" in text or "boom" in text or "top level" in text


def test_validation_result_pass_and_fail() -> None:
    buf = StringIO()
    c = Console(file=buf, force_terminal=True, width=120)
    d = Display(c)
    ok = ValidationReport(passed=True)
    d.validation_result(ok)
    assert "通过" in buf.getvalue()

    buf2 = StringIO()
    d2 = Display(Console(file=buf2, force_terminal=True, width=120))
    bad = ValidationReport(passed=False, errors=[])
    bad.add_error("E", "bad", step_id=2, suggestion="fix")
    d2.validation_result(bad)
    assert "失败" in buf2.getvalue() or "错误" in buf2.getvalue()


def test_validation_result_warnings_when_passed() -> None:
    buf = StringIO()
    c = Console(file=buf, force_terminal=True, width=120)
    d = Display(c)
    rep = ValidationReport(passed=True)
    rep.add_warning("W", "careful", step_id=1)
    d.validation_result(rep)
    assert "警告" in buf.getvalue()


def test_run_logs_panel_and_runs_list() -> None:
    buf = StringIO()
    c = Console(file=buf, force_terminal=True, width=120)
    d = Display(c)
    d.run_logs_panel(
        "abcd1234ef",
        "wf",
        [
            {"step_id": 1, "step_name": "a", "action": "file_reader", "step_status": "success", "duration_ms": 3},
        ],
        "completed",
        total_duration_ms=3,
    )
    d.runs_list_table(
        [{"run_id": "abcd1234", "workflow_name": "w", "status": "completed", "updated_at": "t"}],
        id_mode="prefix",
    )
    d.runs_list_table(
        [{"run_id": "abcd1234", "workflow_name": "w", "status": "completed", "updated_at": "t"}],
        id_mode="full",
    )
    assert "wf" in buf.getvalue() or "Run" in buf.getvalue()


def test_run_status_detail_and_generation_start() -> None:
    buf = StringIO()
    c = Console(file=buf, force_terminal=True, width=120)
    d = Display(c)
    d.run_status_detail("rid", "wn", "running", "now", 2)
    d.generation_start()
    body = buf.getvalue()
    assert "rid" in body or "生成" in body


def test_workflow_detail_and_summary() -> None:
    buf = StringIO()
    c = Console(file=buf, force_terminal=True, width=120)
    d = Display(c)
    wf = WorkflowModel(
        name="demo",
        description="短描述",
        version="1.0",
        inputs={"p": ParamSpec(type="string", description="参数说明", required=True)},
        outputs={"o": ParamSpec(type="string", description="出参")},
        steps=[
            WorkflowStep(id=1, name="读", action="file_reader", outputs={"c": "file_content"}),
        ],
    )
    d.workflow_detail(wf, "workflows/demo.yaml")
    d.workflow_summary(wf)
    text = buf.getvalue()
    assert "demo" in text
    assert "myflow run" in text


def test_workflows_directory_table() -> None:
    buf = StringIO()
    c = Console(file=buf, force_terminal=True, width=120)
    d = Display(c)
    wf = WorkflowModel(
        name="n",
        description="x" * 100,
        steps=[WorkflowStep(id=1, name="s", action="file_reader", outputs={"a": "file_content"})],
    )
    d.workflows_directory_table("workflows", [(wf, Path("workflows/n.yaml"))])
    assert "n" in buf.getvalue()


def test_step_status_and_skipped_outputs() -> None:
    buf = StringIO()
    c = Console(file=buf, force_terminal=True, width=120)
    d = Display(c)
    d.step_status(StepResult(step_id=1, step_name="n", action="file_reader", status="success", duration_ms=5))
    d.step_status(StepResult(step_id=2, step_name="n2", action="x", status="skipped", duration_ms=0))
    d.step_outputs(StepResult(step_id=3, step_name="n3", action="y", status="skipped", outputs={}))
    # step_status 使用符号渲染（✓/✗/—）；这里仅断言有输出
    assert "Step 1" in buf.getvalue() and "Step 2" in buf.getvalue()
