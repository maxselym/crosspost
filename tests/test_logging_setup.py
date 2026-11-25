import json
import logging
from pathlib import Path

import pytest

from crosspost.logging_setup import JsonFormatter, parse_level, setup_logging

HTTP_LOGGERS = ("httpx", "httpcore", "h11", "aiogram")


@pytest.fixture
def logging_env():
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_http = {name: logging.getLogger(name).level for name in HTTP_LOGGERS}

    # Чужие обработчики (в том числе pytest) не закрываем, только отцепляем.
    root.handlers.clear()

    yield

    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    root.setLevel(saved_level)
    for handler in saved_handlers:
        root.addHandler(handler)
    for name, level in saved_http.items():
        logging.getLogger(name).setLevel(level)


def flush_root() -> None:
    for handler in logging.getLogger().handlers:
        handler.flush()


def read_lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_writes_one_json_line_per_record(logging_env, tmp_path: Path) -> None:
    setup_logging(level="INFO", log_dir=tmp_path)
    logging.getLogger("crosspost.test").info("publish started")
    flush_root()

    lines = read_lines(tmp_path / "crosspost.log")

    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["level"] == "INFO"
    assert payload["logger"] == "crosspost.test"
    assert payload["message"] == "publish started"
    assert payload["ts"].endswith("Z")


def test_secret_not_written_to_file(logging_env, tmp_path: Path) -> None:
    url = "https://api.vk.com/method/wall.get?access_token=VKSECRET123&v=5.199"
    setup_logging(level="DEBUG", log_dir=tmp_path, secrets=("VKSECRET123",))
    logging.getLogger("crosspost.test").debug("GET %s", url)
    flush_root()

    content = (tmp_path / "crosspost.log").read_text(encoding="utf-8")

    assert "VKSECRET123" not in content
    payload = json.loads(read_lines(tmp_path / "crosspost.log")[0])
    assert "access_token=***" in payload["message"]


def test_exception_text_is_redacted(logging_env, tmp_path: Path) -> None:
    setup_logging(level="INFO", log_dir=tmp_path)
    logger = logging.getLogger("crosspost.test.exc")

    try:
        raise RuntimeError("failed with access_token=VKSECRET123")
    except RuntimeError:
        logger.exception("publish failed")

    flush_root()
    content = (tmp_path / "crosspost.log").read_text(encoding="utf-8")

    assert "VKSECRET123" not in content
    payload = json.loads(read_lines(tmp_path / "crosspost.log")[0])
    assert "exc_info" in payload
    assert payload["exc_info"].startswith("Traceback")


def test_extra_fields_preserved(logging_env, tmp_path: Path) -> None:
    setup_logging(level="INFO", log_dir=tmp_path)
    logging.getLogger("crosspost.test").info("done", extra={"post_id": 123})
    flush_root()

    payload = json.loads(read_lines(tmp_path / "crosspost.log")[0])

    assert payload["post_id"] == 123


def test_setup_is_idempotent(logging_env, tmp_path: Path) -> None:
    setup_logging(level="INFO", log_dir=tmp_path)
    setup_logging(level="INFO", log_dir=tmp_path)

    assert len(logging.getLogger().handlers) == 2


def test_unknown_level_raises(logging_env) -> None:
    with pytest.raises(ValueError):
        setup_logging(level="VERBOSE")

    with pytest.raises(ValueError):
        parse_level("NOT-A-LEVEL")


def test_http_loggers_are_quieted(logging_env, tmp_path: Path) -> None:
    setup_logging(level="DEBUG", log_dir=tmp_path)

    for name in HTTP_LOGGERS:
        assert logging.getLogger(name).level == logging.WARNING

    setup_logging(level="DEBUG", log_dir=tmp_path, http_log_level="DEBUG")

    for name in HTTP_LOGGERS:
        assert logging.getLogger(name).level == logging.DEBUG


def test_console_only_without_log_dir(logging_env) -> None:
    setup_logging(level="INFO")

    assert len(logging.getLogger().handlers) == 1


def test_formatter_output_is_valid_json(logging_env) -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="tests",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="warning text",
        args=None,
        exc_info=None,
    )

    payload = json.loads(formatter.format(record))

    assert payload["level"] == "WARNING"
    assert payload["message"] == "warning text"
