"""CLI 烟测：覆盖 Typer 入口与常用子命令（提升覆盖率，不调用真实 LLM）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from myflow.cli import app


@pytest.fixture()
def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture()
def runner(project_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("MYFLOW_DB_PATH", str(tmp_path / "cli_state.db"))
    monkeypatch.setenv("MYFLOW_LLM_API_KEY", "")
    return CliRunner()


def test_cli_help(runner: CliRunner) -> None:
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    assert "myflow" in (r.stdout or "").lower() or "工作流" in (r.stdout or "")


def test_cli_validate_ok(runner: CliRunner) -> None:
    r = runner.invoke(app, ["validate", "workflows/read_and_write_txt.yaml"])
    assert r.exit_code == 0


def test_cli_validate_missing_file(runner: CliRunner) -> None:
    r = runner.invoke(app, ["validate", "workflows/does_not_exist_12345.yaml"])
    assert r.exit_code == 2


def test_cli_list_workflows(runner: CliRunner) -> None:
    r = runner.invoke(app, ["list-workflows"])
    assert r.exit_code == 0


def test_cli_show_workflow(runner: CliRunner) -> None:
    r = runner.invoke(app, ["show", "read_and_write_txt"])
    assert r.exit_code == 0


def test_cli_generate_without_key_exits(runner: CliRunner) -> None:
    r = runner.invoke(app, ["generate", "任意需求"])
    assert r.exit_code == 1


def test_cli_list_empty_runs(runner: CliRunner) -> None:
    r = runner.invoke(app, ["list"])
    assert r.exit_code == 0


def test_cli_list_full_id(runner: CliRunner) -> None:
    r = runner.invoke(app, ["list", "--full-id"])
    assert r.exit_code == 0


def test_cli_status_no_arg(runner: CliRunner) -> None:
    r = runner.invoke(app, ["status"])
    assert r.exit_code == 0


def test_cli_run_read_write_txt_ok(runner: CliRunner, tmp_path: Path) -> None:
    src = tmp_path / "in.txt"
    dst = tmp_path / "out.txt"
    src.write_text("cli-smoke", encoding="utf-8")
    r = runner.invoke(
        app,
        [
            "run",
            "workflows/read_and_write_txt.yaml",
            "--input",
            f"input_file_path={src}",
            "--input",
            f"output_file_path={dst}",
        ],
    )
    assert r.exit_code == 0
    assert dst.read_text(encoding="utf-8") == "cli-smoke"


def test_cli_run_verbose(runner: CliRunner, tmp_path: Path) -> None:
    src = tmp_path / "in2.txt"
    dst = tmp_path / "out2.txt"
    src.write_text("v", encoding="utf-8")
    r = runner.invoke(
        app,
        [
            "run",
            "workflows/read_and_write_txt.yaml",
            "-v",
            "--input",
            f"input_file_path={src}",
            "--input",
            f"output_file_path={dst}",
        ],
    )
    assert r.exit_code == 0


def test_cli_debug_callback(runner: CliRunner) -> None:
    r = runner.invoke(app, ["--debug", "list"])
    assert r.exit_code == 0
