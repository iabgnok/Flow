"""
一次性迁移：将步骤 outputs 从 list 转为 dict（上下文变量名 -> 技能字段名）。

用法（仓库根）::

    uv run python scripts/migrate_workflow_outputs_to_mapping.py

迁移完成后可删除本脚本。
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[1]
_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.default_flow_style = False


def _migrate_step_outputs(step: dict) -> None:
    outs = step.get("outputs")
    if outs is None:
        return
    if isinstance(outs, dict):
        return
    if not isinstance(outs, list):
        step["outputs"] = {}
        return

    action = str(step.get("action", "") or "")
    items = [str(x).strip() for x in outs if isinstance(x, str) and str(x).strip()]

    if action == "file_reader":
        if len(items) == 1:
            step["outputs"] = {items[0]: "file_content"}
        else:
            step["outputs"] = {}

    elif action == "file_writer":
        if len(items) >= 2:
            step["outputs"] = {items[0]: "report_path", items[1]: "bytes_written"}
        elif len(items) == 1:
            step["outputs"] = {items[0]: "report_path"}
        else:
            step["outputs"] = {}

    elif action == "llm_generate":
        if len(items) >= 1:
            step["outputs"] = {items[0]: "generated_text"}
        else:
            step["outputs"] = {}

    elif action == "llm_analyze":
        if len(items) >= 2:
            conf = [i for i in items if i == "confidence" or i.endswith("_confidence")]
            other = [i for i in items if i not in conf]
            if len(conf) == 1 and len(other) == 1:
                step["outputs"] = {other[0]: "analysis_result", conf[0]: "confidence"}
            else:
                step["outputs"] = {items[0]: "analysis_result", items[1]: "confidence"}
        elif len(items) == 1:
            step["outputs"] = {items[0]: "analysis_result", "confidence": "confidence"}
        else:
            step["outputs"] = {}

    elif action == "llm_verify":
        if len(items) >= 2:
            ps = [i for i in items if "passed" in i.lower()]
            rest = [i for i in items if i not in ps]
            if len(ps) == 1 and len(rest) == 1:
                step["outputs"] = {rest[0]: "verify_result", ps[0]: "passed"}
            else:
                step["outputs"] = {items[0]: "verify_result", items[1]: "passed"}
        elif len(items) == 1:
            step["outputs"] = {items[0]: "verify_result", "passed": "passed"}
        else:
            step["outputs"] = {}

    elif action == "sub_workflow":
        step["outputs"] = {x: x for x in items}
    else:
        step["outputs"] = {x: x for x in items}


def migrate_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    data = _yaml.load(text)
    if not isinstance(data, dict) or "steps" not in data:
        return False
    steps = data.get("steps")
    if not isinstance(steps, list):
        return False
    changed = False
    for step in steps:
        if isinstance(step, dict) and isinstance(step.get("outputs"), list):
            _migrate_step_outputs(step)
            changed = True
    if changed:
        buf = StringIO()
        _yaml.dump(data, buf)
        path.write_text(buf.getvalue(), encoding="utf-8")
    return changed


def main() -> None:
    roots = [ROOT / "workflows", ROOT / "src" / "myflow" / "prompts" / "examples"]
    n = 0
    for root in roots:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.yaml"), key=lambda x: str(x)):
            if migrate_file(p):
                print("migrated:", p.relative_to(ROOT))
                n += 1
    print("done, files changed:", n)


if __name__ == "__main__":
    main()
