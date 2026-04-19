from __future__ import annotations

from pathlib import Path

import pytest

from myflow.engine.workflow_io import resolve_workflow_ref, workflow_yaml_display_path


def test_resolve_workflow_ref_missing_dir(tmp_path: Path) -> None:
    missing = tmp_path / "no_such_workflows"
    assert resolve_workflow_ref("any", missing) is None


def test_workflow_yaml_display_path_fallback_outside_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wf_file = tmp_path / "deep" / "a.yaml"
    wf_file.parent.mkdir(parents=True)
    wf_file.touch()
    monkeypatch.chdir(tmp_path)
    s = workflow_yaml_display_path(wf_file.resolve(), cwd=tmp_path / "other_cwd")
    assert s.endswith("a.yaml")
