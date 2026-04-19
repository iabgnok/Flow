from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_db_path(tmp_path: Path) -> str:
    return str(tmp_path / "state.db")


@pytest.fixture(autouse=True)
def _force_utf8_io(monkeypatch: pytest.MonkeyPatch) -> None:
    # 测试环境中避免编码差异导致的输出异常
    monkeypatch.setenv("PYTHONUTF8", "1")
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")

