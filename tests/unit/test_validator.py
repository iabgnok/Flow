from __future__ import annotations

from myflow.engine.models import ParamSpec, ValidationReport, WorkflowModel, WorkflowStep
from myflow.engine.skill_registry import build_default_registry
from myflow.engine.validator import WorkflowValidator
from myflow.infra.config import AppConfig


def _validator():
    return WorkflowValidator()


def _skill_output_fields():
    return build_default_registry(AppConfig()).skill_output_field_sets()


def _validate(wf: WorkflowModel, skills: set[str]) -> ValidationReport:
    return _validator().validate(wf, skills, skill_output_fields=_skill_output_fields())


def test_empty_steps_rejected() -> None:
    wf = WorkflowModel(name="w", description="d", steps=[])
    report = _validate(wf, {"file_reader"})
    assert report.passed is False
    assert any(e.code == "EMPTY_STEPS" for e in report.errors)


def test_duplicate_ids_rejected() -> None:
    wf = WorkflowModel(
        name="w",
        description="d",
        steps=[
            WorkflowStep(id=1, name="s1", action="file_reader", outputs={"a": "file_content"}),
            WorkflowStep(id=1, name="s2", action="file_reader", outputs={"b": "file_content"}),
        ],
    )
    report = _validate(wf, {"file_reader"})
    assert report.passed is False
    assert any(e.code == "DUPLICATE_STEP_ID" for e in report.errors)


def test_unknown_action_rejected() -> None:
    wf = WorkflowModel(
        name="w",
        description="d",
        steps=[WorkflowStep(id=1, name="s1", action="unknown", outputs={"a": "file_content"})],
    )
    report = _validate(wf, {"file_reader"})
    assert report.passed is False
    assert any(e.code == "UNKNOWN_ACTION" for e in report.errors)


def test_missing_output_rejected() -> None:
    wf = WorkflowModel(
        name="w",
        description="d",
        steps=[WorkflowStep(id=1, name="s1", action="file_reader", outputs={})],
    )
    report = _validate(wf, {"file_reader"})
    assert report.passed is False
    assert any(e.code == "MISSING_OUTPUT" for e in report.errors)


def test_unbound_variable_rejected() -> None:
    wf = WorkflowModel(
        name="w",
        description="d",
        inputs={"file_path": ParamSpec(type="string", description="p")},
        steps=[
            WorkflowStep(
                id=1,
                name="s1",
                action="file_reader",
                inputs={"file_path": "{{not_defined}}"},
                outputs={"file_content": "file_content"},
            )
        ],
    )
    report = _validate(wf, {"file_reader"})
    assert report.passed is False
    assert any(e.code == "UNBOUND_VARIABLE" for e in report.errors)


def test_on_fail_negative_rejected() -> None:
    wf = WorkflowModel(
        name="w",
        description="d",
        steps=[
            WorkflowStep(id=1, name="s1", action="file_reader", outputs={"a": "file_content"}, on_fail=-1),
        ],
    )
    report = _validate(wf, {"file_reader"})
    assert report.passed is False
    assert any(e.code == "ON_FAIL_TARGET_MISSING" for e in report.errors)


def test_invalid_on_fail_rejected() -> None:
    wf = WorkflowModel(
        name="w",
        description="d",
        steps=[
            WorkflowStep(id=1, name="s1", action="file_reader", outputs={"a": "file_content"}),
            WorkflowStep(id=2, name="s2", action="file_reader", outputs={"b": "file_content"}, on_fail=2),
        ],
    )
    report = _validate(wf, {"file_reader"})
    assert report.passed is False
    assert any(e.code == "INVALID_ON_FAIL" for e in report.errors)


def test_on_fail_target_missing_rejected() -> None:
    wf = WorkflowModel(
        name="w",
        description="d",
        steps=[
            WorkflowStep(id=1, name="s1", action="file_reader", outputs={"a": "file_content"}),
            WorkflowStep(id=2, name="s2", action="file_reader", outputs={"b": "file_content"}, on_fail=999),
        ],
    )
    report = _validate(wf, {"file_reader"})
    assert report.passed is False
    assert any(e.code == "ON_FAIL_TARGET_MISSING" for e in report.errors)


def test_excessive_retries_rejected() -> None:
    wf = WorkflowModel(
        name="w",
        description="d",
        steps=[WorkflowStep(id=1, name="s1", action="file_reader", outputs={"a": "file_content"}, max_retries=999)],
    )
    report = _validate(wf, {"file_reader"})
    assert report.passed is False
    assert any(e.code == "EXCESSIVE_RETRIES" for e in report.errors)


def test_template_residue_rejected() -> None:
    wf = WorkflowModel(
        name="w",
        description="d",
        steps=[
            WorkflowStep(
                id=1,
                name="s1",
                action="file_reader",
                inputs={"file_path": "{{}}"},
                outputs={"file_content": "file_content"},
            )
        ],
    )
    report = _validate(wf, {"file_reader"})
    assert report.passed is False
    assert any(e.code == "TEMPLATE_RESIDUE" for e in report.errors)


def test_danger_keywords_warned() -> None:
    wf = WorkflowModel(
        name="w",
        description="d",
        steps=[
            WorkflowStep(
                id=1,
                name="rm file",
                action="file_reader",
                outputs={"x": "file_content"},
            )
        ],
    )
    report = _validate(wf, {"file_reader"})
    assert any(w.code == "DANGER_KEYWORD" for w in report.warnings)


def test_sub_workflow_missing_path_rejected() -> None:
    wf = WorkflowModel(
        name="w",
        description="d",
        steps=[WorkflowStep(id=1, name="s", action="sub_workflow", outputs={"x": "x"}, workflow=None)],
    )
    report = _validate(wf, {"sub_workflow"})
    assert report.passed is False
    assert any(e.code == "MISSING_WORKFLOW_PATH" for e in report.errors)


def test_invalid_output_field_rejected() -> None:
    wf = WorkflowModel(
        name="w",
        description="d",
        inputs={"file_path": ParamSpec(type="string", description="p")},
        steps=[
            WorkflowStep(
                id=1,
                name="s1",
                action="file_reader",
                inputs={"file_path": "{{file_path}}"},
                outputs={"x": "nonexistent_field"},
            ),
        ],
    )
    report = _validate(wf, {"file_reader"})
    assert report.passed is False
    assert any(e.code == "INVALID_OUTPUT_FIELD" for e in report.errors)


def test_unbound_embedded_variable_rejected() -> None:
    wf = WorkflowModel(
        name="w",
        description="d",
        inputs={"fp": ParamSpec(type="string", description="")},
        steps=[
            WorkflowStep(
                id=1,
                name="s1",
                action="file_reader",
                inputs={"file_path": "{{fp}}/{{ghost_var}}"},
                outputs={"file_content": "file_content"},
            ),
        ],
    )
    report = _validate(wf, {"file_reader"})
    assert report.passed is False
    assert any(e.code == "UNBOUND_VARIABLE" and "ghost_var" in e.message for e in report.errors)


def test_mergeable_llm_analyze_blocking_warning() -> None:
    wf = WorkflowModel(
        name="w",
        description="d",
        inputs={"fp": ParamSpec(type="string", description="p")},
        steps=[
            WorkflowStep(
                id=1,
                name="read",
                action="file_reader",
                inputs={"file_path": "{{fp}}"},
                outputs={"body": "file_content"},
            ),
            WorkflowStep(
                id=2,
                name="a1",
                action="llm_analyze",
                inputs={"content": "{{body}}", "instruction": "维度一"},
                outputs={"o1": "analysis_result"},
            ),
            WorkflowStep(
                id=3,
                name="a2",
                action="llm_analyze",
                inputs={"content": "{{body}}", "instruction": "维度二"},
                outputs={"o2": "analysis_result"},
            ),
        ],
    )
    report = _validate(wf, {"file_reader", "llm_analyze"})
    assert report.passed is True
    assert any(w.code == "MERGEABLE_LLM_ANALYZE" for w in report.warnings)
    assert report.execution_ready() is False
    assert "MERGEABLE_LLM_ANALYZE" in report.compose_feedback_summary()


def test_llm_analyze_distinct_content_strings_not_merge_grouped() -> None:
    wf = WorkflowModel(
        name="w",
        description="d",
        inputs={"fp": ParamSpec(type="string", description="p")},
        steps=[
            WorkflowStep(
                id=1,
                name="read",
                action="file_reader",
                inputs={"file_path": "{{fp}}"},
                outputs={"body": "file_content"},
            ),
            WorkflowStep(
                id=2,
                name="a1",
                action="llm_analyze",
                inputs={"content": "{{body}}", "instruction": "i1"},
                outputs={"o1": "analysis_result"},
            ),
            WorkflowStep(
                id=3,
                name="a2",
                action="llm_analyze",
                inputs={"content": "说明：{{body}}", "instruction": "i2"},
                outputs={"o2": "analysis_result"},
            ),
        ],
    )
    report = _validate(wf, {"file_reader", "llm_analyze"})
    assert not any(w.code == "MERGEABLE_LLM_ANALYZE" for w in report.warnings)
    assert report.execution_ready() is True


def test_overlapping_retry_loops_rejected() -> None:
    skills = {"file_reader", "llm_analyze", "llm_generate", "llm_verify"}
    wf = WorkflowModel(
        name="w",
        description="d",
        inputs={"fp": ParamSpec(type="string", description="p")},
        steps=[
            WorkflowStep(
                id=1,
                name="read",
                action="file_reader",
                inputs={"file_path": "{{fp}}"},
                outputs={"zip": "file_content"},
            ),
            WorkflowStep(
                id=2,
                name="analyze",
                action="llm_analyze",
                inputs={"content": "{{zip}}", "instruction": "i"},
                outputs={"fa": "analysis_result"},
            ),
            WorkflowStep(
                id=3,
                name="g1",
                action="llm_generate",
                inputs={"instruction": "t", "context": "{{fa}}"},
                outputs={"t": "generated_text"},
            ),
            WorkflowStep(
                id=4,
                name="g2",
                action="llm_generate",
                inputs={"instruction": "a", "context": "{{fa}}"},
                outputs={"a": "generated_text"},
            ),
            WorkflowStep(
                id=5,
                name="v1",
                action="llm_verify",
                inputs={"artifact": "{{t}}", "criteria": "c"},
                outputs={"vr": "verify_result", "p": "passed"},
                on_fail=3,
                max_retries=2,
            ),
            WorkflowStep(
                id=6,
                name="v2",
                action="llm_verify",
                inputs={"artifact": "{{a}}", "criteria": "c"},
                outputs={"vr2": "verify_result", "p2": "passed"},
                on_fail=4,
                max_retries=2,
            ),
        ],
    )
    report = _validate(wf, skills)
    assert any(e.code == "OVERLAPPING_RETRY_LOOPS" for e in report.errors)


def test_nested_retry_loops_allowed() -> None:
    skills = {"file_reader", "llm_analyze", "llm_generate", "llm_verify"}
    wf = WorkflowModel(
        name="w",
        description="d",
        inputs={"fp": ParamSpec(type="string", description="p")},
        steps=[
            WorkflowStep(
                id=1,
                name="read",
                action="file_reader",
                inputs={"file_path": "{{fp}}"},
                outputs={"zip": "file_content"},
            ),
            WorkflowStep(
                id=2,
                name="analyze",
                action="llm_analyze",
                inputs={"content": "{{zip}}", "instruction": "i"},
                outputs={"fa": "analysis_result"},
            ),
            WorkflowStep(
                id=3,
                name="inner",
                action="llm_generate",
                inputs={"instruction": "inner", "context": "{{fa}}"},
                outputs={"gi": "generated_text"},
            ),
            WorkflowStep(
                id=4,
                name="outer",
                action="llm_generate",
                inputs={"instruction": "outer", "context": "{{fa}}"},
                outputs={"go": "generated_text"},
            ),
            WorkflowStep(
                id=5,
                name="v_inner",
                action="llm_verify",
                inputs={"artifact": "{{gi}}", "criteria": "c"},
                outputs={"vri": "verify_result", "pi": "passed"},
                on_fail=3,
                max_retries=2,
            ),
            WorkflowStep(
                id=6,
                name="v_outer",
                action="llm_verify",
                inputs={"artifact": "{{go}}", "criteria": "c"},
                outputs={"vro": "verify_result", "po": "passed"},
                on_fail=2,
                max_retries=2,
            ),
        ],
    )
    report = _validate(wf, skills)
    assert not any(e.code == "OVERLAPPING_RETRY_LOOPS" for e in report.errors)


def test_independent_retry_loops_allowed() -> None:
    skills = {"file_reader", "llm_analyze", "llm_generate", "llm_verify"}
    wf = WorkflowModel(
        name="w",
        description="d",
        inputs={"fp": ParamSpec(type="string", description="p")},
        steps=[
            WorkflowStep(
                id=1,
                name="read",
                action="file_reader",
                inputs={"file_path": "{{fp}}"},
                outputs={"zip": "file_content"},
            ),
            WorkflowStep(
                id=2,
                name="analyze",
                action="llm_analyze",
                inputs={"content": "{{zip}}", "instruction": "i"},
                outputs={"fa": "analysis_result"},
            ),
            WorkflowStep(
                id=3,
                name="g1",
                action="llm_generate",
                inputs={"instruction": "t", "context": "{{fa}}"},
                outputs={"t": "generated_text"},
            ),
            WorkflowStep(
                id=4,
                name="v1",
                action="llm_verify",
                inputs={"artifact": "{{t}}", "criteria": "c"},
                outputs={"vr": "verify_result", "p": "passed"},
                on_fail=3,
                max_retries=2,
            ),
            WorkflowStep(
                id=5,
                name="g2",
                action="llm_generate",
                inputs={"instruction": "a", "context": "{{fa}}"},
                outputs={"a": "generated_text"},
            ),
            WorkflowStep(
                id=6,
                name="v2",
                action="llm_verify",
                inputs={"artifact": "{{a}}", "criteria": "c"},
                outputs={"vr2": "verify_result", "p2": "passed"},
                on_fail=5,
                max_retries=2,
            ),
        ],
    )
    report = _validate(wf, skills)
    assert not any(e.code == "OVERLAPPING_RETRY_LOOPS" for e in report.errors)


def test_duplicate_context_output_key_rejected() -> None:
    wf = WorkflowModel(
        name="w",
        description="d",
        inputs={"fp": ParamSpec(type="string", description="p")},
        steps=[
            WorkflowStep(
                id=1,
                name="s1",
                action="file_reader",
                inputs={"file_path": "{{fp}}"},
                outputs={"x": "file_content"},
            ),
            WorkflowStep(
                id=2,
                name="s2",
                action="file_reader",
                inputs={"file_path": "{{fp}}"},
                outputs={"x": "file_content"},
            ),
        ],
    )
    report = _validate(wf, {"file_reader"})
    assert any(w.code == "DUPLICATE_CONTEXT_OUTPUT_KEY" for w in report.warnings)


def test_valid_workflow_passes() -> None:
    wf = WorkflowModel(
        name="w",
        description="d",
        inputs={"file_path": ParamSpec(type="string", description="p")},
        steps=[
            WorkflowStep(
                id=1,
                name="s1",
                action="file_reader",
                inputs={"file_path": "{{file_path}}"},
                outputs={"file_content": "file_content"},
            )
        ],
    )
    report = _validate(wf, {"file_reader"})
    assert report.passed is True

