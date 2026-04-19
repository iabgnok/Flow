from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from myflow.engine.models import WorkflowModel


_yaml = YAML(typ="safe")


def resolve_cli_yaml_path(raw: str | Path) -> Path:
    """
    解析 CLI 传入的工作流路径：若已是现有文件则返回 resolve()；
    未带 .yaml/.yml 时尝试在同目录下补全后缀。
    """
    p = Path(raw).expanduser()
    if p.is_file():
        return p.resolve()
    if p.suffix.lower() not in (".yaml", ".yml"):
        for ext in (".yaml", ".yml"):
            cand = p.with_suffix(ext)
            if cand.is_file():
                return cand.resolve()
    return p


def resolve_existing_workflow_file(path_str: str, *, workflows_dir: str | Path) -> Path:
    """解析磁盘上存在的工作流 YAML（子工作流路径）；相对路径优先相对 cwd，其次相对 workflows_dir。"""
    raw = (path_str or "").strip()
    if not raw:
        raise ValueError("工作流路径为空")
    p = Path(raw).expanduser()
    if p.is_file():
        return p.resolve()
    cwd_try = resolve_cli_yaml_path(p)
    if cwd_try.is_file():
        return cwd_try.resolve()
    anchor = Path(workflows_dir).resolve() / raw
    if anchor.is_file():
        return anchor.resolve()
    raise FileNotFoundError(f"找不到工作流文件: {path_str}")


# 输入：YAML 文件路径（字符串或 Path）。
# 做什么：用 ruamel.yaml 的 safe 加载器读文件 → 顶层必须是 dict，否则报错 →
# 把字典 WorkflowModel(**data) 转成强类型的 WorkflowModel 实例。
# 用途：从磁盘上的 .yaml 工作流定义加载成引擎可直接校验、执行的模型。
def load_workflow(path: str | Path) -> WorkflowModel:
    p = Path(path)
    data = _yaml.load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"工作流 YAML 顶层必须是对象: {p}")
    return WorkflowModel(**data)

# 输入：已构造好的 WorkflowModel。
# 做什么：workflow.model_dump() 变成普通 dict → 
# 用 ruamel.yaml 写到内存里的 StringIO → 
# 返回 YAML 字符串（块风格、允许 Unicode）。
# 用途：把内存里的工作流定义序列化成 YAML 文本
# （保存文件、打印、交给别的系统都可以；函数本身只返回字符串，不写盘）。
def save_workflow(path: str | Path, workflow: WorkflowModel) -> None:
    """将工作流写入 YAML 文件。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dump_workflow(workflow), encoding="utf-8")


def dump_workflow(workflow: WorkflowModel) -> str:
    from io import StringIO

    buf = StringIO()
    y = YAML()
    y.default_flow_style = False
    y.allow_unicode = True
    y.dump(workflow.model_dump(), buf)
    return buf.getvalue()


def scan_workflows(
    workflows_dir: str | Path,
) -> tuple[list[tuple[WorkflowModel, Path]], list[tuple[Path, str]]]:
    """
    递归扫描目录下全部 .yaml，解析为 WorkflowModel。
    返回 (成功列表, 解析失败列表)，失败项为 (路径, 错误摘要)。
    文件顺序：按路径字符串排序（确定性）。
    """
    root = Path(workflows_dir).resolve()
    ok: list[tuple[WorkflowModel, Path]] = []
    errors: list[tuple[Path, str]] = []
    if not root.exists():
        return ok, errors
    paths = sorted(root.glob("**/*.yaml"), key=lambda p: str(p))
    for p in paths:
        try:
            wf = load_workflow(p)
            ok.append((wf, p.resolve()))
        except Exception as e:
            errors.append((p, repr(e)))
    return ok, errors


def resolve_workflow_ref(name_or_path: str, workflows_dir: str | Path) -> Path | None:
    """
    解析 `show` / 文档用的工作流引用：
    - 若指向存在的文件，直接返回；
    - 否则在 workflows_dir 下按文件名 stem 匹配首个 .yaml（多命中时取路径最短，再按字典序）。
    """
    raw = Path(name_or_path)
    if raw.is_file():
        return raw.resolve()

    root = Path(workflows_dir).resolve()
    if not root.exists():
        return None

    stem = Path(name_or_path.rstrip("/\\")).stem
    matches = [p for p in root.glob("**/*.yaml") if p.stem == stem]
    if not matches:
        return None
    matches.sort(key=lambda p: (len(str(p)), str(p)))
    return matches[0].resolve()


def workflow_yaml_display_path(yaml_path: Path, cwd: Path | None = None) -> str:
    """尽量输出相对当前工作目录的路径字符串。"""
    base = cwd or Path.cwd()
    try:
        return str(yaml_path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(yaml_path.resolve())

