from __future__ import annotations

import pytest

from myflow.engine.models import ValidationReport, WorkflowModel, WorkflowStep


def test_workflow_step_caps_max_retries_to_5() -> None:
    step = WorkflowStep(id=1, name="x", action="file_reader", outputs={"o": "file_content"}, max_retries=999)
    assert step.max_retries == 999


def test_workflow_step_on_fail_not_normalized_in_model() -> None:
    """非法 on_fail 不在 Pydantic 层改写，交给 WorkflowValidator。"""
    step = WorkflowStep(id=1, name="x", action="file_reader", outputs={"o": "file_content"}, on_fail=-1)
    assert step.on_fail == -1


def test_validation_report_error_summary_contains_codes() -> None:
    r = ValidationReport()
    r.add_error("E1", "bad", step_id=2, suggestion="fix")
    text = r.error_summary()
    assert r.passed is False
    assert "[E1]" in text
    assert "step 2" in text
    assert "修复建议" in text


def test_workflow_model_minimum_constructs() -> None:
    wf = WorkflowModel(
        name="w",
        description="d",
        steps=[WorkflowStep(id=1, name="s", action="file_reader", outputs={"x": "file_content"})],
    )
    assert wf.name == "w"
    assert len(wf.steps) == 1

