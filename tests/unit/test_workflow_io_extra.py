from __future__ import annotations

from pathlib import Path

import pytest

from myflow.engine.workflow_io import (
    resolve_cli_yaml_path,
    resolve_existing_workflow_file,
    resolve_workflow_ref,
    save_workflow,
    scan_workflows,
)
from myflow.engine.models import ParamSpec, WorkflowModel, WorkflowStep


def test_scan_and_resolve(tmp_path: Path) -> None:
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    wf = WorkflowModel(
        name="demo",
        description="d",
        inputs={"x": ParamSpec()},
        steps=[
            WorkflowStep(id=1, name="r", action="file_reader", inputs={}, outputs={"file_content": "file_content"}),
        ],
    )
    save_workflow(wf_dir / "nested" / "demo.yaml", wf)

    rows, errs = scan_workflows(wf_dir)
    assert not errs
    assert len(rows) == 1
    assert rows[0][0].name == "demo"

    p = resolve_workflow_ref("demo", wf_dir)
    assert p is not None and p.name == "demo.yaml"


def test_resolve_cli_yaml_path_adds_suffix(tmp_path: Path) -> None:
    p = tmp_path / "w.yaml"
    wf = WorkflowModel(
        name="w",
        description="",
        steps=[
            WorkflowStep(id=1, name="r", action="file_reader", inputs={}, outputs={"a": "file_content"}),
        ],
    )
    save_workflow(p, wf)
    got = resolve_cli_yaml_path(tmp_path / "w")
    assert got.resolve() == p.resolve()


def test_resolve_existing_file(tmp_path: Path) -> None:
    p = tmp_path / "w.yaml"
    wf = WorkflowModel(
        name="w",
        description="",
        steps=[
            WorkflowStep(id=1, name="r", action="file_reader", inputs={}, outputs={"a": "file_content"}),
        ],
    )
    save_workflow(p, wf)
    assert resolve_workflow_ref(str(p), tmp_path) == p.resolve()


def test_resolve_existing_workflow_file_via_workflows_dir(tmp_path: Path) -> None:
    wf_dir = tmp_path / "wfroot"
    wf_dir.mkdir()
    inner = wf_dir / "child.yaml"
    wf = WorkflowModel(
        name="child",
        description="",
        steps=[WorkflowStep(id=1, name="r", action="file_reader", inputs={}, outputs={"a": "file_content"})],
    )
    save_workflow(inner, wf)
    got = resolve_existing_workflow_file("child.yaml", workflows_dir=wf_dir)
    assert got.resolve() == inner.resolve()


def test_resolve_existing_workflow_file_raises_when_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_existing_workflow_file("nope.yaml", workflows_dir=tmp_path)
