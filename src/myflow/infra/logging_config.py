from __future__ import annotations

import logging
import os
import sys

import structlog


def configure_logging(*, debug: bool) -> None:
    """结构化日志；与 Display 的步骤 outputs 展示相互独立。调试模式下 stderr 使用 Rich 日志渲染。"""
    level = logging.DEBUG if debug else logging.INFO
    if debug and sys.stderr.isatty():
        from rich.console import Console
        from rich.logging import RichHandler

        logging.basicConfig(
            level=level,
            format="%(message)s",
            datefmt="[%X]",
            handlers=[
                RichHandler(
                    console=Console(stderr=True),
                    show_time=True,
                    show_path=False,
                    markup=True,
                    rich_tracebacks=True,
                )
            ],
        )
    else:
        logging.basicConfig(
            format="%(message)s",
            stream=sys.stderr,
            level=level,
        )

    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
    ]
    if sys.stderr.isatty():
        shared.append(structlog.dev.ConsoleRenderer(colors=True))
    else:
        shared.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=shared,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def logging_from_env() -> bool:
    v = os.environ.get("MYFLOW_DEBUG", "").strip().lower()
    return v in ("1", "true", "yes", "on")
