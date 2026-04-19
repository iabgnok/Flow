from __future__ import annotations

import pytest

from myflow.infra import logging_config


def test_logging_from_env_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYFLOW_DEBUG", raising=False)
    assert logging_config.logging_from_env() is False


def test_logging_from_env_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYFLOW_DEBUG", "1")
    assert logging_config.logging_from_env() is True


def test_configure_logging_plain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stderr.isatty", lambda: False)
    logging_config.configure_logging(debug=False)


def test_configure_logging_debug_no_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stderr.isatty", lambda: False)
    logging_config.configure_logging(debug=True)


def test_configure_logging_debug_tty_rich(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stderr.isatty", lambda: True)
    logging_config.configure_logging(debug=True)
