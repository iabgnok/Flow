from __future__ import annotations

from myflow.engine.models import ParamSpec, WorkflowModel, WorkflowStep
from myflow.engine.skill_registry import build_default_registry
from myflow.engine.validator import WorkflowValidator
from myflow.infra.config import AppConfig
from myflow.quality_metrics import (
    GenerationQualityRecord,
    all_actions_whitelisted,
    e2e_success_rate,
    executable_rate,
    format_metrics_report,
    record_from_compose,
    retry_convergence_rate,
    skill_hit_rate,
)


def test_all_actions_whitelisted() -> None:
    wf = WorkflowModel(
        name="w",
        description="d",
        steps=[
            WorkflowStep(id=1, name="a", action="file_reader", outputs={"x": "file_content"}),
            WorkflowStep(id=2, name="b", action="file_writer", outputs={"y": "report_path"}),
        ],
    )
    assert all_actions_whitelisted(wf, {"file_reader", "file_writer"})
    assert not all_actions_whitelisted(wf, {"file_reader"})


def test_rates_and_record_from_compose() -> None:
    v = WorkflowValidator()
    fields = build_default_registry(AppConfig()).skill_output_field_sets()
    wf = WorkflowModel(
        name="w",
        description="d",
        inputs={"file_path": ParamSpec(description="p")},
        steps=[
            WorkflowStep(
                id=1,
                name="r",
                action="file_reader",
                inputs={"file_path": "{{file_path}}"},
                outputs={"c": "file_content"},
            ),
        ],
    )
    report = v.validate(wf, {"file_reader", "file_writer"}, skill_output_fields=fields)
    rec = record_from_compose(
        report=report,
        workflow=wf,
        skill_names={"file_reader"},
        attempts=2,
        from_cache=False,
        run_completed=True,
    )
    assert rec.validation_passed and rec.skill_hit and rec.run_completed is True
    assert rec.converged_after_retry

    bad_wf = WorkflowModel(name="bad", description="", steps=[])
    bad_rep = v.validate(bad_wf, {"file_reader"}, skill_output_fields=fields)
    rec2 = record_from_compose(
        report=bad_rep,
        workflow=wf,
        skill_names={"file_reader"},
        attempts=1,
        from_cache=False,
        run_completed=None,
    )
    assert not rec2.validation_passed
    assert rec2.run_completed is None

    rs = [rec, rec2]
    assert executable_rate(rs) == 0.5
    assert skill_hit_rate(rs) == 1.0
    assert e2e_success_rate(rs) == 1.0  # 仅 1 条尝试 run
    assert retry_convergence_rate([rec]) == 1.0
    assert retry_convergence_rate([]) == 1.0  # 无 eligible 时约定为 1.0


def test_format_metrics_report_contains_headers() -> None:
    rows = [
        GenerationQualityRecord(
            validation_passed=True,
            skill_hit=True,
            run_completed=None,
            attempts=1,
            converged_after_retry=False,
            from_cache=False,
        )
    ]
    text = format_metrics_report(rows, samples_per_requirement=2)
    assert "质量抽样报告" in text
    assert "可执行率" in text
