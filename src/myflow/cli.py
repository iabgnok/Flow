from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer
from rich.console import Console

from myflow.display import Display
from myflow.engine.cache import build_champion_cache
from myflow.engine.composer import WorkflowComposer
from myflow.engine.runner import Runner
from myflow.engine.skill_registry import build_default_registry
from myflow.engine.validator import WorkflowValidator
from myflow.engine.workflow_io import (
    load_workflow,
    resolve_cli_yaml_path,
    resolve_workflow_ref,
    save_workflow,
    scan_workflows,
    workflow_yaml_display_path,
)
from myflow.infra.config import AppConfig
from myflow.infra.logging_config import configure_logging, logging_from_env
from myflow.infra.llm_client import LLMClient
from myflow.infra.state_store import StateStore

# 初始化CLI对象：typer.Typer，用于解析命令行参数
app = typer.Typer(name="myflow", help="AI 工作流生成与执行引擎", no_args_is_help=True)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

console = Console()
display = Display(console)


@app.callback()
def _root(
    debug: bool = typer.Option(False, "--debug", help="启用结构化调试日志（stderr）；亦可设 MYFLOW_DEBUG=1"),
) -> None:
    """MyFlow CLI。"""
    import os

    if debug:
        os.environ["MYFLOW_DEBUG"] = "1"
    configure_logging(debug=debug or logging_from_env())


def _ensure_workflow_yaml_file(raw: Path) -> Path:
    """路径无效时给出可读提示（含 Windows 勿误用 `/` 绝对路径）。"""
    path = resolve_cli_yaml_path(raw)
    if path.is_file():
        return path
    console.print(f"[red]找不到工作流文件:[/] {raw}")
    console.print(
        "[dim]提示：请在项目根目录使用相对路径，例如 "
        "`workflows/read_and_write_txt.yaml`；可省略后缀 `.yaml`。"
        " Windows 下若以 `/` 开头会指向磁盘根目录而非项目下的 workflows。[/]"
    )
    raise typer.Exit(code=2)

# 解析输入参数：入参：key=value 格式的字符串列表；返回：字典
def _parse_inputs(pairs: list[str]) -> dict:
    ctx: dict[str, object] = {}
    for item in pairs:
        if "=" not in item:
            raise typer.BadParameter(f"输入参数必须为 key=value: {item}")
        k, v = item.split("=", 1)
        ctx[k.strip()] = v
    return ctx


async def _resolve_run_id_or_exit(store: StateStore, ref: str) -> str:
    """解析 run_id 或唯一前缀；歧义或无匹配时打印说明并退出。"""
    key = ref.strip()
    rid = await store.resolve_run_id(key)
    if rid:
        return rid
    cands = await store.find_run_ids_starting_with(key)
    if len(cands) > 1:
        console.print(
            f"[red]前缀[/] [cyan]{key}[/] [red]匹配到 {len(cands)} 条记录，请加长前缀或输入完整 run_id。[/]"
        )
        console.print(
            "[dim]不会同时对多条执行 status/logs；请从下列候选中选更长前缀直至唯一。[/]"
        )
        for x in cands[:12]:
            console.print(f"  [dim]{x}[/]")
        raise typer.Exit(code=2)
    console.print(
        f"[red]找不到运行记录:[/] {key}\n"
        "[dim]提示：执行 [cyan]myflow list[/] 查看最近 run_id；"
        "续跑/查日志须使用与当时一致的 [cyan]MYFLOW_DB_PATH[/]。[/]"
    )
    raise typer.Exit(code=2)

# 运行命令捕获
@app.command()
def run(
    workflow_path: Path = typer.Argument(..., help="工作流 YAML 文件路径"),
    inputs: list[str] = typer.Option([], "--input", "-i", help="输入参数 key=value"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    run_id: str | None = typer.Option(None, "--resume", help="恢复指定 run_id 的中断执行"),
):
    """执行指定工作流。"""
    asyncio.run(_run_workflow(workflow_path, inputs, verbose, run_id))

# 执行工作流：入参：工作流路径，输入参数，是否打印详细信息，恢复指定 run_id 的中断执行
async def _run_workflow(workflow_path: Path, inputs: list[str], verbose: bool, run_id: str | None) -> None:
    config = AppConfig()
    registry = build_default_registry(config)
    store = StateStore(config.db_path)
    def _on_step(sr):
        display.step_status(sr)
        if verbose and sr.status == "success":
            display.step_outputs(sr)
    # 初始化Runner对象：入参：技能注册表，状态存储，配置，回调函数（用于打印步骤结果）
    runner = Runner(registry, store, config, on_step_result=_on_step)

    try:
        wf = load_workflow(_ensure_workflow_yaml_file(workflow_path))
    except ValueError as e:
        console.print(f"[red]工作流 YAML 结构无效:[/] {e}")
        raise typer.Exit(code=2) from e
    except OSError as e:
        console.print(f"[red]无法读取工作流文件:[/] {e}")
        raise typer.Exit(code=2) from e

    ctx = _parse_inputs(inputs)

    try:
        # 运行工作流：入参：工作流对象，初始上下文，恢复 run_id；返回：运行结果
        result = await runner.run(wf, initial_context=ctx, run_id=run_id)
    except KeyboardInterrupt:
        console.print(
            "[yellow]已中断。[/] 进度已写入数据库（状态 running）；请 [cyan]myflow list[/] 查看 run_id，"
            "并用同一 YAML [cyan]myflow run … --resume <run_id>[/] 续跑。"
        )
        raise typer.Exit(code=130)
    except Exception as e:
        console.print(f"[red]执行失败（未捕获异常）:[/] {e}")
        raise typer.Exit(code=1) from e

    # 步骤已在执行过程中逐条打印；结尾 run 报告仍保留完整步骤表便于对照与复制。
    display.run_result(result, show_steps=True)
    if result.status == "completed":
        display.completed_final_echo(result)

    if result.status != "completed":
        raise typer.Exit(code=1)

# 生成命令捕获
@app.command()
def generate(
    requirement: str = typer.Argument(..., help="自然语言需求描述"),
    output: Path | None = typer.Option(None, "--output", "-o", help="输出文件路径（默认写入配置的工作流目录）"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    execute: bool = typer.Option(False, "--run", help="生成校验通过后立即执行"),
):
    """根据自然语言生成工作流 YAML。"""
    asyncio.run(_generate_workflow(requirement, output, verbose, execute))

# 生成工作流：入参：自然语言需求描述，输出文件路径，是否打印详细信息，生成校验通过后是否立即执行
async def _generate_workflow(
    requirement: str,
    output: Path | None,
    verbose: bool,
    execute: bool,
) -> None:
    config = AppConfig()
    if not str(config.llm_api_key).strip():
        console.print("[red]未配置 MYFLOW_LLM_API_KEY，无法调用 LLM。[/]")
        raise typer.Exit(code=1)

    registry = build_default_registry(config)
    cache = build_champion_cache(
        enabled=config.champion_cache_enabled,
        cache_dir=config.champion_cache_dir,
    )
    composer = WorkflowComposer(LLMClient(config), registry, config, cache=cache)

    display.generation_start()
    outcome = await composer.compose_until_valid(requirement)
    wf, report = outcome.workflow, outcome.report
    if outcome.from_cache:
        console.print("[dim]Champion 缓存命中，已跳过 LLM 生成。[/]")
    display.validation_result(report)
    if not report.execution_ready():
        console.print("[dim]可根据上方错误与建议修改需求后重试；或先 [cyan]myflow validate[/] 手工 YAML。[/]")
        raise typer.Exit(code=1)

    out_path = output
    if out_path is None:
        out_dir = Path(config.workflows_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{wf.name}.yaml"
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)

    save_workflow(out_path, wf)
    rel = workflow_yaml_display_path(out_path.resolve())
    display.generation_result(wf, rel, validation_ok=report.execution_ready())

    if execute:
        await _run_workflow(Path(out_path), [], verbose, None)


@app.command("validate")
def validate_workflow(
    workflow_path: Path = typer.Argument(..., help="工作流 YAML 文件路径"),
):
    """校验工作流定义（确定性规则）。"""
    asyncio.run(_validate_workflow(workflow_path))


async def _validate_workflow(workflow_path: Path) -> None:
    config = AppConfig()
    registry = build_default_registry(config)
    try:
        wf = load_workflow(_ensure_workflow_yaml_file(workflow_path))
    except ValueError as e:
        console.print(f"[red]YAML 无法解析为工作流模型:[/] {e}")
        raise typer.Exit(code=2) from e
    except OSError as e:
        console.print(f"[red]无法读取文件:[/] {e}")
        raise typer.Exit(code=2) from e
    report = WorkflowValidator().validate(
        wf,
        registry.skill_names,
        skill_output_fields=registry.skill_output_field_sets(),
    )
    display.validation_result(report)
    if not report.execution_ready():
        raise typer.Exit(code=1)


@app.command(name="list-workflows")
def list_workflows_cmd():
    """列出配置的工作流目录下的 YAML 工作流摘要。"""
    asyncio.run(_list_workflows())


async def _list_workflows() -> None:
    config = AppConfig()
    root = config.workflows_dir
    rows, errors = scan_workflows(root)
    for p, err in errors:
        console.print(f"[yellow]警告[/] 跳过 [dim]{p}[/]: {err}")
    if not rows:
        console.print(
            f"[dim]没有可列出的工作流（目录 [cyan]{root}[/]）。"
            "请检查 [cyan]MYFLOW_WORKFLOWS_DIR[/] 或修复上方解析警告。[/]"
        )
    display.workflows_directory_table(root, rows)


@app.command()
def show(
    name_or_path: str = typer.Argument(
        ...,
        help="工作流逻辑名（无后缀）、相对/绝对路径；多文件同名时取路径最短的一条",
    ),
):
    """展示单个工作流的契约、步骤与 run 示例。"""
    asyncio.run(_show_workflow_usage(name_or_path))


async def _show_workflow_usage(name_or_path: str) -> None:
    config = AppConfig()
    path = resolve_workflow_ref(name_or_path, config.workflows_dir)
    if path is None:
        console.print(
            f"[red]未找到工作流:[/] {name_or_path}\n"
            f"[dim]在 [cyan]{config.workflows_dir}[/] 下按逻辑名或路径查找；可用 [cyan]myflow list-workflows[/] 浏览。[/]"
        )
        raise typer.Exit(code=1)
    try:
        wf = load_workflow(path)
    except ValueError as e:
        console.print(f"[red]YAML 无效（{path}）:[/] {e}")
        raise typer.Exit(code=2) from e
    yaml_rel = workflow_yaml_display_path(path)
    display.workflow_detail(wf, yaml_rel)


@app.command(
    "list",
    context_settings={"help_option_names": ["-h", "--help"]},
)
def list_run_records_cmd(
    limit: int = typer.Option(20, "--limit", "-n", min=1, max=500),
    full_id: bool = typer.Option(False, "--full-id", help="列表中显示完整 run_id（列较宽，易挤占时间列）"),
):
    """列出最近的运行记录（与工作流目录的 list-workflows 不同）。"""
    asyncio.run(_list_run_records(limit, full_id))


async def _list_run_records(limit: int, full_id: bool) -> None:
    config = AppConfig()
    store = StateStore(config.db_path)
    await store.init()
    rows = await store.list_runs(limit=limit)
    if not rows:
        console.print("[dim]暂无运行记录。[/]")
        return
    console.print("\n[bold]运行记录[/]\n")
    display.runs_list_table(rows, id_mode="full" if full_id else "prefix")
    if full_id:
        console.print("[dim]完整 run_id 模式；断点与详情仍可用 [cyan]myflow status <id 或前缀>[/]。[/]")
    else:
        console.print(
            "[dim]上表为 run_id 前 8 位（Prefix）。完整 id 与断点：[cyan]myflow status <前缀>[/]；"
            "前缀若匹配多条会列出候选，[red]不会[/]同时对多条展开 status；"
            "需要宽表可加 [cyan]myflow list --full-id[/]。[/]"
        )


@app.command("logs")
def runs_logs(
    run_ref: str = typer.Argument(..., help="run_id 或其唯一前缀"),
):
    """查看某次运行的步骤历史（来自数据库）。"""
    asyncio.run(_logs_run(run_ref))


async def _logs_run(run_ref: str) -> None:
    config = AppConfig()
    store = StateStore(config.db_path)
    await store.init()
    rid = await _resolve_run_id_or_exit(store, run_ref)
    row = await store.load_run(rid)
    if not row:
        console.print(f"[red]运行记录已不存在:[/] {rid}")
        raise typer.Exit(code=2)
    steps = await store.load_steps(rid)
    meta: dict[int, tuple[str, str]] = {}
    path = resolve_workflow_ref(row["workflow_name"], config.workflows_dir)
    if path is not None:
        try:
            wf = load_workflow(path)
            meta = {s.id: (s.name, s.action) for s in wf.steps}
        except Exception:
            pass
    disp_rows: list[dict] = []
    total_ms = 0
    counted = 0
    for s in steps:
        sid = int(s["step_id"])
        name, action = meta.get(sid, ("?", "?"))
        d = s.get("duration_ms")
        if isinstance(d, int):
            dur = d
        elif isinstance(d, str) and d.isdigit():
            dur = int(d)
        else:
            dur = None
        if dur is not None:
            total_ms += dur
            counted += 1
        disp_rows.append(
            {
                "step_id": sid,
                "step_name": name,
                "action": action,
                "step_status": s["status"],
                "duration_ms": dur,
            }
        )
    total_arg = total_ms if counted else None
    display.run_logs_panel(rid, row["workflow_name"], disp_rows, row["status"], total_duration_ms=total_arg)


@app.command("status")
def run_status(
    run_ref: str | None = typer.Argument(None, help="run_id 或其唯一前缀；省略则提示并列出最近记录"),
):
    """查看单次运行的状态与断点信息。"""
    asyncio.run(_status_run(run_ref))


async def _status_run(run_ref: str | None) -> None:
    config = AppConfig()
    store = StateStore(config.db_path)
    await store.init()
    if not (run_ref or "").strip():
        console.print("[yellow]用法:[/] [cyan]myflow status <run_id 或前缀>[/]")
        rows = await store.list_runs(limit=12)
        if rows:
            console.print("\n[dim]最近运行（Prefix 列，完整 id 请 status）：[/]\n")
            display.runs_list_table(rows)
            console.print(
                "[dim]用法：[cyan]myflow status <前缀>[/]；多条同前缀时会报错并列出候选，不会同时展示多条详情。[/]"
            )
        else:
            console.print("[dim]暂无运行记录。[/]")
        return

    rid = await _resolve_run_id_or_exit(store, run_ref)
    row = await store.load_run(rid)
    if not row:
        console.print(f"[red]运行记录已不存在:[/] {rid}")
        raise typer.Exit(code=2)
    updated = str(row.get("updated_at") or "")
    display.run_status_detail(
        rid,
        row["workflow_name"],
        row["status"],
        updated,
        int(row.get("current_step_id") or 0),
    )
