from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from myflow.engine.models import (
    BLOCKING_WARNING_CODES,
    ParamSpec,
    RunResult,
    StepResult,
    ValidationReport,
    WorkflowModel,
)

_OUTPUT_SINGLE_LINE_MAX = 520


class Display:
    def __init__(self, console: Console):
        self.c = console

    def step_status(self, step: StepResult) -> None:
        icon = {"success": "[green]OK[/]", "failed": "[red]X[/]", "skipped": "[dim]SKIP[/]"}
        self.c.print(
            f"  {icon.get(step.status, '?')} Step {step.step_id} │ {step.step_name} │ {step.action} │ {step.duration_ms}ms"
        )

    def step_outputs(self, step: StepResult, *, heading: str | None = None) -> None:
        """打印单步全部 outputs（字符串化；单行过长截断）。成功且无产出时不打印。"""
        if step.status != "success" or not step.outputs:
            return
        title = heading or f"步骤 {step.step_id} 产出"
        self.c.print(f"\n[bold]{title}[/]")
        for k in sorted(step.outputs.keys()):
            self.c.print(f"  [cyan]{k}[/] → {self._format_output_value(step.outputs[k])}")

    def completed_final_echo(self, result: RunResult) -> None:
        """completed 且最后一步非 file_writer 时展示最后一步 outputs。"""
        if result.status != "completed" or not result.step_results:
            return
        last = result.step_results[-1]
        if last.action == "file_writer" or last.status != "success":
            return
        self.step_outputs(last, heading="结果")

    def run_logs_panel(
        self,
        run_id: str,
        wf_name: str,
        rows: list[dict[str, Any]],
        status: str,
        *,
        total_duration_ms: int | None = None,
    ) -> None:
        """rows 每项含 step_id, step_name, action, step_status, duration_ms（可选）。"""
        t = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
        t.add_column("Step", style="dim", width=4)
        t.add_column("Name", min_width=10)
        t.add_column("Action", style="cyan", min_width=12)
        t.add_column("St", width=5)
        t.add_column("Time", justify="right", width=10)
        for r in rows:
            dur = r.get("duration_ms")
            time_cell = "—"
            if isinstance(dur, int):
                time_cell = f"{dur}ms" if dur < 10_000 else f"{dur / 1000:.1f}s"
            icon = "[green]✓[/]" if r.get("step_status") == "success" else "[red]✗[/]" if r.get("step_status") == "failed" else "[dim]—[/]"
            t.add_row(
                str(r.get("step_id", "")),
                str(r.get("step_name", "")),
                str(r.get("action", "")),
                icon,
                time_cell,
            )
        st_color = "green" if status == "completed" else "red" if status == "failed" else "yellow"
        sub = f"[{st_color}]{status}[/]"
        if total_duration_ms is not None:
            sub += f"   │   Duration: {total_duration_ms}ms"
        panel = Panel(
            t,
            title=f"Run {run_id[:8]} — {wf_name}",
            subtitle=sub,
            border_style=st_color,
        )
        self.c.print(panel)

    def runs_list_table(
        self,
        rows: list[dict[str, Any]],
        *,
        id_mode: str = "prefix",
        prefix_len: int = 8,
    ) -> None:
        """
        id_mode: \"prefix\" 仅显示 run_id 前若干字符（列表省宽）；\"full\" 显示完整 id。
        """
        t = Table(show_header=True, header_style="bold")
        if id_mode == "full":
            t.add_column("Run ID", style="cyan", min_width=28, overflow="fold")
        else:
            t.add_column("Prefix", style="cyan", width=max(prefix_len, 8) + 1, no_wrap=True)
        t.add_column("Workflow", min_width=14)
        t.add_column("Status", width=11)
        t.add_column("Updated", min_width=22, overflow="fold")
        for r in rows:
            rid = str(r.get("run_id", ""))
            id_cell = rid if id_mode == "full" else (rid[:prefix_len] if rid else "")
            t.add_row(
                id_cell,
                str(r.get("workflow_name", "")),
                str(r.get("status", "")),
                str(r.get("updated_at", "")),
            )
        self.c.print(t)

    def run_status_detail(
        self, run_id: str, workflow_name: str, status: str, updated_at: str, current_step_id: int
    ) -> None:
        self.c.print(
            f"\n[bold]Run[/] {run_id}\n"
            f"  工作流: [cyan]{workflow_name}[/]\n"
            f"  状态: {status}\n"
            f"  断点步骤 ID: {current_step_id}\n"
            f"  更新于: {updated_at}\n"
        )

    @staticmethod
    def _format_output_value(v: Any) -> str:
        if isinstance(v, str):
            s = v
        else:
            try:
                s = json.dumps(v, ensure_ascii=False, default=str)
            except TypeError:
                s = str(v)
        s = s.replace("\n", "⏎")
        if len(s) > _OUTPUT_SINGLE_LINE_MAX:
            return s[: _OUTPUT_SINGLE_LINE_MAX] + " … [dim][省略][/]"
        return s

    def run_result(self, result: RunResult) -> None:
        status_color = {"completed": "green", "failed": "red", "interrupted": "yellow"}
        color = status_color.get(result.status, "white")

        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
        table.add_column("Step", style="dim", width=6)
        table.add_column("Name", min_width=16)
        table.add_column("Action", style="cyan")
        table.add_column("Status", width=8)
        table.add_column("Time", justify="right", width=8)

        for sr in result.step_results:
            status_text = {"success": "[green]OK[/]", "failed": "[red]X[/]", "skipped": "[dim]SKIP[/]"}.get(
                sr.status, sr.status
            )
            table.add_row(str(sr.step_id), sr.step_name, sr.action, status_text, f"{sr.duration_ms}ms")

        panel = Panel(
            table,
            title=f"Run {result.run_id[:8]} — {result.workflow_name}",
            subtitle=f"[{color}]{result.status}[/] │ {result.total_duration_ms}ms",
            border_style=color,
        )
        self.c.print(panel)
        if result.error:
            self.c.print(f"\n[red]Error:[/] {result.error}")

    def validation_result(self, report: ValidationReport) -> None:
        if report.execution_ready():
            soft = [w for w in report.warnings if w.code not in BLOCKING_WARNING_CODES]
            if soft:
                self.c.print(f"[green]OK 校验通过[/] ([yellow]{len(soft)}[/] 条非阻塞警告)")
            else:
                self.c.print("[green]OK 校验通过[/]")
            for w in soft:
                loc = f"Step {w.step_id}" if w.step_id else "Workflow"
                self.c.print(f"  [yellow]![/] [{w.code}] {loc}: {w.message}")
            return

        parts: list[str] = []
        if report.errors:
            parts.append(f"{len(report.errors)} 条错误")
        if report.has_blocking_warnings():
            parts.append("阻塞级警告")
        label = " + ".join(parts) if parts else "问题"
        self.c.print(f"[red]X 校验未通过[/] ({label})")
        for e in report.errors:
            loc = f"Step {e.step_id}" if e.step_id else "Workflow"
            self.c.print(f"  [red]X[/] [{e.code}] {loc}: {e.message}")
            if e.suggestion:
                self.c.print(f"    [dim]建议: {e.suggestion}[/]")
        for w in report.warnings:
            loc = f"Step {w.step_id}" if w.step_id else "Workflow"
            if w.code in BLOCKING_WARNING_CODES:
                self.c.print(f"  [red]X[/] [{w.code}] {loc}: {w.message}")
                if w.suggestion:
                    self.c.print(f"    [dim]建议: {w.suggestion}[/]")
            else:
                self.c.print(f"  [yellow]![/] [{w.code}] {loc}: {w.message}")

    def generation_start(self) -> None:
        self.c.print("\n[bold]正在生成工作流…[/]\n")

    def generation_result(self, wf: WorkflowModel, path: str, validation_ok: bool = True) -> None:
        vlabel = "[green]校验通过[/]" if validation_ok else "[yellow]校验未通过（见上）[/]"
        self.c.print(f"[green]OK[/] 工作流已生成: [bold]{wf.name}[/]（{len(wf.steps)} 步骤）│ {vlabel}")
        for s in sorted(wf.steps, key=lambda x: x.id):
            self.c.print(f"  {s.id}. {s.name:24s} -> {s.action}")
        self.c.print(f"\n已保存至: [cyan]{path}[/]")

    def workflows_directory_table(self, workflows_dir: str, rows: list[tuple[WorkflowModel, Path]]) -> None:
        """Name / Description / Steps；行序与 scan 一致（路径排序）。"""
        self.c.print(f"\n[bold]可用工作流[/] ([dim]{workflows_dir}/[/])\n")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Name", style="cyan", min_width=16)
        table.add_column("Description", min_width=28)
        table.add_column("Steps", justify="right", width=6)
        for wf, _path in rows:
            desc = wf.description
            if len(desc) > 72:
                desc = desc[:69] + "…"
            table.add_row(wf.name, desc, str(len(wf.steps)))
        self.c.print(table)

    def workflow_detail(self, wf: WorkflowModel, yaml_rel_path: str) -> None:
        self.c.print(f"\n[bold]{wf.name}[/] v{wf.version}\n{wf.description}\n")
        self.c.print("[bold]输入参数[/]")
        if not wf.inputs:
            self.c.print("  （无）")
        else:
            for k, spec in wf.inputs.items():
                self.c.print(self._param_line(k, spec, show_required=True))
        self.c.print("\n[bold]输出[/]")
        if not wf.outputs:
            self.c.print("  （无）")
        else:
            for k, spec in wf.outputs.items():
                self.c.print(self._param_line(k, spec, show_required=False))

        self.c.print("\n[bold]步骤[/]")
        for s in sorted(wf.steps, key=lambda x: x.id):
            line = f"  {s.id}. {s.name} -> {s.action}"
            if s.on_fail is not None:
                line += f"  [dim](失败→步骤 {s.on_fail}, 最多 {s.max_retries} 次)[/]"
            self.c.print(line)

        self.c.print("\n[bold]用法[/]")
        run_line = f"myflow run {yaml_rel_path}"
        keys = list(wf.inputs.keys())
        if keys:
            self.c.print(f"  {run_line} \\")
            for i, k in enumerate(keys):
                last = i == len(keys) - 1
                cont = "" if last else " \\"
                self.c.print(f"    --input {k}=<{k}>{cont}")
        else:
            self.c.print(f"  {run_line}")

    def _param_line(self, name: str, spec: ParamSpec, *, show_required: bool) -> str:
        req = ""
        if show_required:
            req = " (必填)" if spec.required else " (可选)"
        default = f" default={spec.default}" if spec.default is not None else ""
        desc = spec.description.strip()
        tail = f"  {desc}" if desc else ""
        return f"  [cyan]{name}[/]  {spec.type}{req}{default}{tail}"

    def workflow_summary(self, wf: WorkflowModel) -> None:
        self.c.print(f"[bold]{wf.name}[/] — {wf.description} ({len(wf.steps)} steps)")
        for s in sorted(wf.steps, key=lambda x: x.id):
            self.c.print(f"  {s.id}. {s.name} → {s.action}")
