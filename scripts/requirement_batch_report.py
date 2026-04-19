"""
根据 batch_manifest.yaml 与 run_specs.yaml 扫描 20 条需求工作流，
执行校验与（可选）运行，并重写 requirement_batch_io/SUMMARY.md。

用法（仓库根目录）::

    uv run python scripts/requirement_batch_report.py
    uv run python scripts/requirement_batch_report.py --skip-ids 10
    uv run python scripts/requirement_batch_report.py --from-id 11

需要真实执行时：配置 .env 中 MYFLOW_LLM_API_KEY，并在 run_specs.yaml
中为对应 id 填写与工作流 inputs 同名的键值。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

_yaml = YAML(typ="safe")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from myflow.engine.runner import Runner  # noqa: E402
from myflow.engine.skill_registry import build_default_registry  # noqa: E402
from myflow.engine.validator import WorkflowValidator  # noqa: E402
from myflow.engine.workflow_io import load_workflow  # noqa: E402
from myflow.infra.config import AppConfig  # noqa: E402
from myflow.infra.state_store import StateStore  # noqa: E402
from myflow.quality_metrics import all_actions_whitelisted  # noqa: E402


def _load_yaml(path: Path) -> dict[str, Any]:
    data = _yaml.load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML 顶层必须是 mapping: {path}")
    return data


def _cell(text: str, max_len: int = 120) -> str:
    t = (text or "").replace("|", "\\|").replace("\r", " ").replace("\n", " ")
    if len(t) > max_len:
        return t[: max_len - 1] + "…"
    return t


def _tier_cn(tier: str) -> str:
    return {"simple": "简单", "medium": "中等", "complex": "复杂"}.get(tier, tier)


def _parse_skip_ids(s: str) -> set[str]:
    ids: set[str] = set()
    for part in (s or "").replace(" ", "").split(","):
        if not part:
            continue
        ids.add(part.zfill(2))
    return ids


async def _run_one(
    wf_path: Path,
    inputs: dict[str, Any],
    config: AppConfig,
) -> tuple[str, str | None, dict[str, Any]]:
    registry = build_default_registry(config)
    store = StateStore(config.db_path)
    runner = Runner(registry, store, config)
    wf = load_workflow(wf_path)
    result = await runner.run(wf, initial_context=dict(inputs))
    if result.status == "completed":
        keys = list(result.final_context.keys())
        tail = f"context_keys={keys[-8:]}" if keys else "empty_context"
        return "成功", None, {"final_context_keys": keys, "run_id": result.run_id, "hint": tail}
    err = result.error or ""
    if result.step_results:
        last = result.step_results[-1]
        if last.error:
            err = err or last.error
    return "失败", err, {"run_id": result.run_id, "error": err}


def main() -> None:
    ap = argparse.ArgumentParser(description="批量校验并执行需求工作流，重写 SUMMARY.md")
    ap.add_argument(
        "--skip-ids",
        default="",
        help="逗号分隔的用例 id（如 10 或 10,11）：仍做存在性/校验/技能统计，但不调用 Runner 执行",
    )
    ap.add_argument(
        "--from-id",
        type=int,
        default=1,
        metavar="N",
        help="仅对用例 id≥N 调用 Runner（默认 1；例如 11 表示只执行 11–20，前面条目不跑）",
    )
    cli = ap.parse_args()
    skip_ids = _parse_skip_ids(cli.skip_ids)
    run_from_id = max(1, int(cli.from_id))

    os.chdir(ROOT)
    manifest_path = ROOT / "requirement_batch_io" / "batch_manifest.yaml"
    run_specs_path = ROOT / "requirement_batch_io" / "run_specs.yaml"
    manifest = _load_yaml(manifest_path)
    run_specs = _load_yaml(run_specs_path)
    cases: dict[str, Any] = run_specs.get("cases") or {}
    wf_subdir = Path(manifest.get("workflow_subdir") or "workflows/requirement_batch_20")
    summary_rel = manifest.get("summary_path") or "requirement_batch_io/SUMMARY.md"
    summary_path = ROOT / summary_rel

    runs_dir = ROOT / "requirement_batch_io" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    items: list[dict[str, Any]] = manifest.get("items") or []
    config = AppConfig()

    rows: list[dict[str, Any]] = []
    n_gen = n_val_ok = n_run_ok = n_run_attempt = 0
    n_skill_eval = n_skill_hit = 0

    async def process_block() -> None:
        nonlocal n_gen, n_val_ok, n_run_ok, n_run_attempt, n_skill_eval, n_skill_hit
        for it in items:
            rid = str(it.get("id", "")).zfill(2)
            tier = str(it.get("tier", ""))
            name_zh = str(it.get("name_zh", ""))
            default_name = str(it.get("default_workflow_filename", ""))
            default_path = (ROOT / wf_subdir / default_name).resolve()

            case = cases.get(rid) or cases.get(str(int(rid))) or {}
            wf_rel = case.get("workflow")
            wf_path = (ROOT / wf_rel).resolve() if wf_rel else default_path
            inputs = case.get("inputs") or {}
            if not isinstance(inputs, dict):
                inputs = {}

            exists = wf_path.is_file()
            val_ok: bool | None = None
            val_msg = ""
            skill_hit_cell = "—"
            wf_load_ok = False
            if exists:
                n_gen += 1
                try:
                    registry = build_default_registry(config)
                    wf = load_workflow(wf_path)
                except Exception as e:
                    val_ok = False
                    val_msg = f"YAML 解析失败: {e}"
                else:
                    wf_load_ok = True
                    report = WorkflowValidator().validate(
                        wf,
                        registry.skill_names,
                        skill_output_fields=registry.skill_output_field_sets(),
                    )
                    val_ok = report.execution_ready()
                    if val_ok:
                        n_val_ok += 1
                    else:
                        val_msg = (report.compose_feedback_summary() or report.error_summary()).strip()
                    n_skill_eval += 1
                    if all_actions_whitelisted(wf, registry.skill_names):
                        n_skill_hit += 1
                        skill_hit_cell = f"是({len(wf.steps)}步)"
                    else:
                        unknown = [s.action for s in wf.steps if s.action not in registry.skill_names]
                        uniq = ",".join(dict.fromkeys(unknown))
                        skill_hit_cell = f"否({uniq[:48]}{'…' if len(uniq) > 48 else ''})"

            run_status = "—"
            run_detail = ""
            extra: dict[str, Any] = {}

            if rid in skip_ids:
                run_status = "跳过"
                run_detail = "已按 --skip-ids 跳过执行（未调用 Runner）"
            elif int(rid) < run_from_id:
                run_status = "跳过"
                run_detail = f"已按 --from-id 跳过执行（本次仅跑 id≥{run_from_id}，未调用 Runner）"
            elif exists and inputs and wf_load_ok:
                n_run_attempt += 1
                run_status, err, extra = await _run_one(wf_path, inputs, config)
                if run_status == "成功":
                    n_run_ok += 1
                run_detail = err or extra.get("hint", "")
                snap = {
                    "id": rid,
                    "workflow": wf_path.resolve().relative_to(ROOT.resolve()).as_posix(),
                    "status": run_status,
                    "error": err,
                    "extra": extra,
                }
                (runs_dir / f"{rid}_last_run.json").write_text(
                    json.dumps(snap, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            elif exists and inputs and not wf_load_ok:
                run_status = "跳过"
                run_detail = "YAML 未解析，未执行"
            elif exists and not inputs:
                run_status = "跳过"
                run_detail = "run_specs 中 inputs 为空"

            yaml_rel = wf_path.resolve().relative_to(ROOT.resolve()).as_posix()
            rows.append(
                {
                    "id": rid,
                    "tier": _tier_cn(tier),
                    "name": name_zh,
                    "yaml": yaml_rel,
                    "exists": "是" if exists else "否",
                    "validate": ("通过" if val_ok else ("未通过" if exists else "—")),
                    "val_msg": val_msg,
                    "run": run_status,
                    "run_detail": run_detail,
                    "skill_hit": skill_hit_cell,
                }
            )

    asyncio.run(process_block())

    total = len(items)
    rate_full = (n_run_ok / total) if total else 0.0
    rate_gen = (n_run_ok / n_gen) if n_gen else 0.0
    rate_attempt = (n_run_ok / n_run_attempt) if n_run_attempt else 0.0

    lines: list[str] = []
    lines.append("# 需求批量测试汇总（20 条）\n")
    lines.append(
        "本文件由 `scripts/requirement_batch_report.py` 自动生成。"
        "**技能命中率**与明细列一致：单条为「所有步骤 `action` 是否均属于引擎已注册技能」"
        "（与 `myflow.quality_metrics.all_actions_whitelisted` 相同）；"
        "总体比率为可评估工作流中命中条数 / 可评估条数（已成功加载为模型的工作流）。\n"
    )
    lines.append("## 目录约定\n")
    lines.append("- **夹具与元数据**：`requirement_batch_io/fixtures/`、`batch_manifest.yaml`、`run_specs.yaml`\n")
    lines.append("- **工作流定义**：`workflows/requirement_batch_20/rb20_rXX.yaml`（由 `myflow generate` 生成）\n")
    lines.append("- **单次执行快照**：`requirement_batch_io/runs/XX_last_run.json`\n")
    lines.append("## 生成工作流（示例）\n")
    lines.append("在项目根执行，将 `requirement` 换为 `batch_manifest.yaml` 中对应 `requirement` 字段：\n")
    lines.append("```bash\n")
    lines.append('uv run myflow generate "……需求原文……" -o workflows/requirement_batch_20/rb20_r01.yaml\n')
    lines.append("```\n")
    lines.append("## 指标（可执行率由脚本计算）\n")
    lines.append(f"- 已生成工作流文件数：**{n_gen}** / {total}\n")
    val_denom = n_gen if n_gen else 0
    lines.append(
        f"- 校验通过数：**{n_val_ok}** / {val_denom if val_denom else '—'}"
        f"（分母为已生成文件数；当前已生成 {n_gen} 个）\n"
    )
    lines.append(f"- 已配置非空 inputs 并尝试执行：**{n_run_attempt}** 条\n")
    lines.append(f"- 执行成功数：**{n_run_ok}** / {total}\n")
    lines.append(
        f"- **可执行率（对全体 20 条）**：{n_run_ok}/{total} = **{rate_full:.1%}**"
        "（未配置 inputs 的条目计为未执行）\n"
    )
    lines.append(
        f"- **可执行率（对已生成文件）**：{n_run_ok}/{n_gen} = **{rate_gen:.1%}**"
        f"（当 n_gen=0 时为 0）\n"
    )
    lines.append(
        f"- **可执行率（对已配置执行用例）**：{n_run_ok}/{n_run_attempt} = **{rate_attempt:.1%}**"
        f"（当未配置时为 0）\n"
    )
    skill_rate = (n_skill_hit / n_skill_eval) if n_skill_eval else 0.0
    skill_rate_all = (n_skill_hit / total) if total else 0.0
    lines.append(
        f"- **技能命中率（可评估子集）**：{n_skill_hit}/{n_skill_eval} = **{skill_rate:.1%}**"
        f"（分母为「文件存在且 YAML 可解析为工作流」的条数；解析失败不计入）\n"
    )
    lines.append(
        f"- **技能命中率（对全体 20 条，缺失计未命中）**：{n_skill_hit}/{total} = **{skill_rate_all:.1%}**\n"
    )
    lines.append("\n## 明细表\n")
    lines.append(
        "| ID | 档位 | 名称 | 工作流 | 已生成 | 校验 | 执行 | 执行摘要 | 技能命中 |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
    )
    for r in rows:
        val_note = f"; {_cell(r['val_msg'], 60)}" if r["val_msg"] else ""
        validate_cell = r["validate"] + val_note if val_note and r["validate"] == "未通过" else r["validate"]
        lines.append(
            f"| {r['id']} | {r['tier']} | {_cell(r['name'], 20)} | `{_cell(r['yaml'], 40)}` | {r['exists']} | "
            f"{_cell(validate_cell, 40)} | {r['run']} | {_cell(r['run_detail'], 80)} | {_cell(r['skill_hit'], 24)} |\n"
        )

    lines.append("\n## 校验失败详情（如有）\n")
    for r in rows:
        if r["val_msg"]:
            lines.append(f"### {r['id']} {r['name']}\n")
            lines.append("```text\n")
            lines.append(r["val_msg"])
            lines.append("\n```\n")

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("".join(lines), encoding="utf-8")
    print(f"Wrote {summary_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
