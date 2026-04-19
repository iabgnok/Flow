from __future__ import annotations

from pathlib import Path

import pytest

from myflow.engine.cache import (
    ChampionCache,
    build_champion_cache,
    normalize_requirement,
    requirement_fingerprint,
    skill_set_token,
)
from myflow.engine.models import ParamSpec, WorkflowModel, WorkflowStep


def test_normalize_requirement_collapses_whitespace() -> None:
    assert normalize_requirement("  a   b  ") == "a b"
    assert normalize_requirement("") == ""


def test_fingerprint_stable_under_whitespace() -> None:
    assert requirement_fingerprint("  x  ") == requirement_fingerprint("x")


def test_build_champion_cache_respects_enabled() -> None:
    assert build_champion_cache(enabled=False, cache_dir="/tmp/x") is None
    assert isinstance(build_champion_cache(enabled=True, cache_dir="/tmp/y"), ChampionCache)


def test_put_get_roundtrip(tmp_path: Path) -> None:
    cache = ChampionCache(tmp_path / "c")
    skills = {"file_reader", "file_writer"}
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
                outputs={"file_content": "file_content"},
            ),
        ],
    )
    req = "读取某文件"
    cache.put(req, wf, skills)
    got = cache.get(req, skills)
    assert got is not None
    assert got.name == "w"
    assert got.steps[0].action == "file_reader"


def test_skill_set_change_invalidates(tmp_path: Path) -> None:
    cache = ChampionCache(tmp_path / "c2")
    wf = WorkflowModel(
        name="w",
        description="d",
        steps=[WorkflowStep(id=1, name="r", action="file_reader", outputs={"a": "file_content"})],
    )
    cache.put("需求A", wf, {"file_reader"})
    assert cache.get("需求A", {"file_reader", "new_skill"}) is None


def test_corrupt_yaml_entry_is_removed(tmp_path: Path) -> None:
    cache = ChampionCache(tmp_path / "c3")
    skills = {"file_reader"}
    wf = WorkflowModel(
        name="w",
        description="d",
        steps=[WorkflowStep(id=1, name="r", action="file_reader", outputs={"a": "file_content"})],
    )
    cache.put("k", wf, skills)
    fp = __import__("myflow.engine.cache", fromlist=["requirement_fingerprint"]).requirement_fingerprint("k")
    st = skill_set_token(skills)
    yaml_path, meta_path = cache._artifact_paths(fp, st)
    yaml_path.write_text("- not_a_dict\n", encoding="utf-8")
    assert cache.get("k", skills) is None
    assert not yaml_path.is_file()
    assert not meta_path.is_file()
