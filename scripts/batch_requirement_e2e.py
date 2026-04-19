"""
批量：读取 batch_manifest →（可选）myflow generate → 推断 run_specs.inputs → 写回 run_specs.yaml
→ 调用 requirement_batch_report.py 更新 SUMMARY。

默认：若目标 YAML 已存在则跳过生成（便于断点续跑）。强制全量重生成：

  uv run python scripts/batch_requirement_e2e.py --force-generate

仅根据已生成 YAML 刷新 run_specs（不调 generate）。默认仍会跑 SUMMARY（会顺序执行 20 条工作流，耗时长）：

  uv run python scripts/batch_requirement_e2e.py --spec-only --no-report
  uv run python scripts/requirement_batch_report.py

跳过若干条（不 generate、report 里也不执行 Runner）::

  uv run python scripts/batch_requirement_e2e.py --skip-ids 10
  uv run python scripts/requirement_batch_report.py --skip-ids 10
  uv run python scripts/requirement_batch_report.py --from-id 11
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from io import StringIO
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

_yaml = YAML()
_yaml.indent(mapping=2, sequence=4, offset=2)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from myflow.engine.models import WorkflowModel  # noqa: E402
from myflow.engine.workflow_io import load_workflow  # noqa: E402


def _load_manifest(path: Path) -> dict[str, Any]:
    data = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("manifest 顶层必须是 mapping")
    return data


def _classify_input(key: str, desc: str) -> str:
    k, d = key.lower(), (desc or "")
    if any(x in d for x in ("读取", "输入", "源文件", "待分析", "待处理", "上传")) and any(
        x in d for x in ("路径", "文件", "目录")
    ):
        return "file"
    if any(x in d for x in ("输出", "写入文件", "保存到", "结果路径", "导出")) and any(
        x in d for x in ("路径", "文件", "目录")
    ):
        return "out"
    if any(x in k for x in ("output_path", "output_file_path", "dest_path", "output_report_path")):
        return "out"
    if "output" in k and ("path" in k or "file" in k):
        return "out"
    if k in ("outfile", "out_path", "dst", "destination"):
        return "out"
    if "keyword" in k or k.endswith("_keyword"):
        return "text"
    if any(
        x in k
        for x in (
            "instruction",
            "criteria",
            "prompt",
            "requirement",
            "task",
            "query",
            "system",
            "user_message",
        )
    ):
        return "text"
    if any(x in k for x in ("path", "file", "csv", "json", "md", "txt", "dir", "folder", "src")):
        return "file"
    return "other"


def _parse_product_marketing_fixture(raw: str) -> tuple[str, str] | None:
    """从 batch 夹具（如 r04_product.txt）解析「产品名称」「核心卖点」正文，避免误填为文件路径。"""
    m_name = re.search(r"产品名称\s*[:：]\s*([^\n\r]+)", raw)
    m_point = re.search(r"核心卖点\s*[:：]\s*([^\n\r]+)", raw)
    if not (m_name and m_point):
        return None
    return m_name.group(1).strip(), m_point.group(1).strip()


def _is_multi_path_key(key: str, desc: str) -> bool:
    kl, d = key.lower(), desc or ""
    if "paths" in kl:
        return True
    if "path" in kl and "列表" in d:
        return True
    if "逗号" in d and "路径" in d:
        return True
    if "多个" in d and "路径" in d:
        return True
    return False


def _infer_inputs(wf: WorkflowModel, item: dict[str, Any], rid: str) -> dict[str, str]:
    requirement = str(item.get("requirement", "")).strip()
    fixtures: list[str] = list(item.get("primary_fixtures") or [])
    keys = list(wf.inputs.keys())
    if not keys:
        return {}
    work = [k for k, p in wf.inputs.items() if p.required] or keys

    out_keys: list[str] = []
    text_keys: list[str] = []
    file_keys: list[str] = []
    for k in work:
        desc = (wf.inputs[k].description or "") if k in wf.inputs else ""
        cls = _classify_input(k, desc)
        if cls == "out":
            out_keys.append(k)
        elif cls == "text":
            text_keys.append(k)
        else:
            file_keys.append(k)

    prefill: dict[str, str] = {}
    if (
        "product_name" in wf.inputs
        and "core_selling_point" in wf.inputs
        and "product_name" in work
        and "core_selling_point" in work
        and fixtures
    ):
        fp = ROOT / fixtures[0]
        if fp.is_file() and fp.suffix.lower() in (".txt", ".md", ""):
            parsed = _parse_product_marketing_fixture(
                fp.read_text(encoding="utf-8", errors="replace")
            )
            if parsed:
                prefill["product_name"], prefill["core_selling_point"] = parsed
                text_keys = [k for k in text_keys if k not in prefill]
                file_keys = [k for k in file_keys if k not in prefill]

    inputs: dict[str, str] = dict(prefill)
    for k in text_keys:
        inputs[k] = requirement[:2000] + ("…" if len(requirement) > 2000 else "")

    rid2 = str(rid).zfill(2)
    base = f"requirement_batch_io/runs/{rid2}"
    (ROOT / base).mkdir(parents=True, exist_ok=True)

    fi = 0
    for k in file_keys:
        desc = (wf.inputs[k].description or "") if k in wf.inputs else ""
        if _is_multi_path_key(k, desc):
            if fixtures:
                joined = ",".join(fixtures)
                inputs[k] = joined if len(fixtures) > 1 else ",".join([fixtures[0]] * 3)
            else:
                inputs[k] = ""
            continue
        if k.endswith("_dir") or ("目录" in desc and "路径" in desc):
            if "课程" in desc or "course" in k.lower():
                inputs[k] = (ROOT / "requirement_batch_io/fixtures/r19_course").as_posix()
            elif fixtures:
                p = (ROOT / fixtures[0]).resolve()
                inputs[k] = p.parent.as_posix() if p.is_file() else p.as_posix()
            else:
                inputs[k] = (ROOT / base).as_posix()
            continue
        if fi < len(fixtures):
            inputs[k] = fixtures[fi]
            fi += 1
        elif fixtures:
            inputs[k] = fixtures[0]
    for i, k in enumerate(out_keys):
        ext = ".md" if any(x in k.lower() for x in ("report", "summary", "memo", "文档")) else ".txt"
        inputs[k] = f"{base}/wf_out_{i}{ext}"

    for k, spec in wf.inputs.items():
        if not spec.required:
            continue
        if k in inputs and str(inputs[k]).strip():
            continue
        if fixtures:
            inputs[k] = fixtures[0]
        elif requirement:
            inputs[k] = requirement[:2000]
        else:
            inputs[k] = ""

    return inputs


def _parse_skip_ids(s: str) -> set[str]:
    ids: set[str] = set()
    for part in (s or "").replace(" ", "").split(","):
        if not part:
            continue
        ids.add(part.zfill(2))
    return ids


def _write_run_specs(cases: dict[str, Any], dest: Path) -> None:
    buf = StringIO()
    _yaml.dump({"version": 1, "cases": cases}, buf)
    dest.write_text(buf.getvalue(), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-generate", action="store_true", help="即使目标 YAML 已存在也重新生成")
    ap.add_argument("--spec-only", action="store_true", help="只刷新 run_specs（不调用 generate）；是否写 SUMMARY 见 --no-report")
    ap.add_argument(
        "--no-report",
        action="store_true",
        help="不调用 requirement_batch_report.py（避免对 20 条工作流顺序做真实 LLM 执行）",
    )
    ap.add_argument(
        "--skip-ids",
        default="",
        help="逗号分隔用例 id（如 10）：不调用 myflow generate；传给 report 以跳过 Runner 执行",
    )
    ap.add_argument(
        "--from-id",
        type=int,
        default=1,
        metavar="N",
        help="传给 report：仅对 id≥N 执行 Runner（默认 1）",
    )
    args = ap.parse_args()
    skip_ids = _parse_skip_ids(args.skip_ids)

    os.chdir(ROOT)
    manifest_path = ROOT / "requirement_batch_io" / "batch_manifest.yaml"
    run_specs_path = ROOT / "requirement_batch_io" / "run_specs.yaml"
    manifest = _load_manifest(manifest_path)
    wf_sub = Path(manifest.get("workflow_subdir") or "workflows/requirement_batch_20")
    items: list[dict[str, Any]] = list(manifest.get("items") or [])

    cases: dict[str, Any] = {}
    if run_specs_path.is_file():
        raw = YAML(typ="safe").load(run_specs_path.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict) and isinstance(raw.get("cases"), dict):
            cases = {str(k).zfill(2): dict(v) for k, v in raw["cases"].items()}

    for it in items:
        rid = str(it.get("id", "")).zfill(2)
        fname = str(it.get("default_workflow_filename", ""))
        out_yaml = (ROOT / wf_sub / fname).resolve()
        req = str(it.get("requirement", ""))

        if not args.spec_only:
            if rid in skip_ids:
                print(f"[{rid}] skip generate (--skip-ids): {out_yaml.relative_to(ROOT)}")
            else:
                need_gen = (not out_yaml.is_file()) or args.force_generate
                if not need_gen:
                    print(f"[{rid}] skip generate (exists): {out_yaml.relative_to(ROOT)}")
                else:
                    print(f"[{rid}] generate → {out_yaml.relative_to(ROOT)}")
                    r = subprocess.run(
                        [
                            "uv",
                            "run",
                            "myflow",
                            "generate",
                            req,
                            "-o",
                            str(out_yaml.relative_to(ROOT)),
                        ],
                        cwd=str(ROOT),
                        timeout=900,
                    )
                    if r.returncode != 0:
                        print(f"[{rid}] generate failed exit={r.returncode}")

        wf_rel = str((wf_sub / fname).as_posix())
        entry = cases.get(rid) or {"workflow": wf_rel, "inputs": {}}
        entry["workflow"] = wf_rel

        if out_yaml.is_file():
            try:
                wf = load_workflow(out_yaml)
                entry["inputs"] = _infer_inputs(wf, it, rid)
            except Exception as e:
                print(f"[{rid}] infer inputs failed: {e}")
                entry["inputs"] = entry.get("inputs") or {}
        else:
            entry["inputs"] = {}
        cases[rid] = entry

    _write_run_specs(cases, run_specs_path)
    print(f"Wrote {run_specs_path.relative_to(ROOT)}")

    if args.no_report:
        print("已跳过 SUMMARY；请执行: uv run python scripts/requirement_batch_report.py")
        raise SystemExit(0)

    report_cmd = [sys.executable, str(ROOT / "scripts" / "requirement_batch_report.py")]
    if args.skip_ids:
        report_cmd.extend(["--skip-ids", args.skip_ids])
    if args.from_id > 1:
        report_cmd.extend(["--from-id", str(args.from_id)])
    r = subprocess.run(report_cmd, cwd=str(ROOT))
    raise SystemExit(r.returncode)


if __name__ == "__main__":
    main()
