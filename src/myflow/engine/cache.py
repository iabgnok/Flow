"""Champion 缓存：相同（规范化）需求命中时直接复用上次校验通过的工作流。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from myflow.engine.models import WorkflowModel
from myflow.engine.workflow_io import load_workflow, save_workflow


def normalize_requirement(requirement: str) -> str:
    """空白规范化，避免仅因空格差异导致缓存未命中。"""
    return " ".join((requirement or "").split())


def requirement_fingerprint(requirement: str) -> str:
    return hashlib.sha256(normalize_requirement(requirement).encode("utf-8")).hexdigest()


def skill_set_token(skill_names: set[str]) -> str:
    """技能白名单变更时使旧缓存条目失效。"""
    raw = "|".join(sorted(skill_names))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def build_champion_cache(*, enabled: bool, cache_dir: str) -> ChampionCache | None:
    if not enabled:
        return None
    return ChampionCache(Path(cache_dir))


class ChampionCache:
    """按需求指纹落盘 YAML；元数据记录技能集 token。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _artifact_paths(self, fp: str, skill_tok: str) -> tuple[Path, Path]:
        bucket = self.root / fp[:2]
        stem = bucket / f"{fp}_{skill_tok}"
        return stem.with_suffix(".yaml"), stem.with_suffix(".meta.json")

    def get(self, requirement: str, skill_names: set[str]) -> WorkflowModel | None:
        fp = requirement_fingerprint(requirement)
        st = skill_set_token(skill_names)
        yaml_path, meta_path = self._artifact_paths(fp, st)
        if not yaml_path.is_file() or not meta_path.is_file():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._unlink_pair(yaml_path, meta_path)
            return None
        if meta.get("skill_token") != st or meta.get("fingerprint") != fp:
            self._unlink_pair(yaml_path, meta_path)
            return None
        try:
            return load_workflow(yaml_path)
        except Exception:
            self._unlink_pair(yaml_path, meta_path)
            return None

    def put(self, requirement: str, workflow: WorkflowModel, skill_names: set[str]) -> None:
        fp = requirement_fingerprint(requirement)
        st = skill_set_token(skill_names)
        yaml_path, meta_path = self._artifact_paths(fp, st)
        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        save_workflow(yaml_path, workflow)
        meta_path.write_text(
            json.dumps(
                {
                    "fingerprint": fp,
                    "skill_token": st,
                    "normalized_requirement": normalize_requirement(requirement),
                    "workflow_name": workflow.name,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _unlink_pair(yaml_path: Path, meta_path: Path) -> None:
        for p in (yaml_path, meta_path):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
