"""Настройка структурированного логирования.

Один JSON-объект на строку. Секреты маскируются фильтром и повторно —
в форматтере, чтобы покрыть ``exc_info`` и ``stack_info``.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from crosspost.utils.redact import RedactFilter, redact_text

DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5

_HTTP_LOGGERS: tuple[str, ...] = ("httpx", "httpcore", "h11", "aiogram")

_RESERVED_ATTRS: frozenset[str] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


def _format_timestamp(created: float) -> str:
    moment = datetime.fromtimestamp(created, tz=UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class JsonFormatter(logging.Formatter):
    """Форматтер: одна JSON-строка на запись, секреты маскируются."""

    def __init__(self, secrets: Sequence[str] = ()) -> None:
        super().__init__()
        self._secrets: tuple[str, ...] = tuple(secret for secret in secrets if secret)

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": _format_timestamp(record.created),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)

        for key, value in record.__dict__.items():
            if key in _RESERVED_ATTRS or key.startswith("_"):
                continue
            payload[key] = value

        raw = json.dumps(payload, ensure_ascii=False, default=str)
        return redact_text(raw, self._secrets)


def parse_level(value: str | int) -> int:
    """Перевести имя уровня логирования в числовое значение."""
    if isinstance(value, int):
        return value

    level = logging.getLevelNamesMapping().get(value.strip().upper())
    if level is None:
        raise ValueError(f"unknown log level: {value!r}")
    return level


def setup_logging(
    *,
    level: str | int = "INFO",
    log_dir: Path | None = None,
    log_file_name: str = "crosspost.log",
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
    secrets: Sequence[str] = (),
    http_log_level: str | int = "WARNING",
) -> None:
    """Настроить корневой логгер; повторный вызов заменяет обработчики.

    ``log_dir=None`` оставляет только вывод в stdout.
    """
    root_level = parse_level(level)
    http_level = parse_level(http_log_level)

    formatter = JsonFormatter(secrets=secrets)
    redact_filter = RedactFilter(secrets=secrets)

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    root.setLevel(root_level)

    console = logging.StreamHandler(stream=sys.stdout)
    console.setFormatter(formatter)
    console.addFilter(redact_filter)
    root.addHandler(console)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            filename=log_dir / log_file_name,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redact_filter)
        root.addHandler(file_handler)

    for name in _HTTP_LOGGERS:
        logging.getLogger(name).setLevel(http_level)
