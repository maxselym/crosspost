import logging

import pytest

from crosspost.utils.redact import MASK, RedactFilter, redact_text, redact_value

VK_URLS = [
    "https://api.vk.com/method/wall.get?owner_id=-227892646&access_token=VKSECRET123&v=5.199",
    "https://api.vk.com/method/wall.get?access_token=VKSECRET123",
    "https://api.vk.com/method/wall.get?ACCESS_TOKEN=VKSECRET123&v=5.199",
]

TG_URLS = [
    "https://api.telegram.org/bot123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw/getMe",
    "https://api.telegram.org/bot123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw/sendMessage",
]

TG_TOKEN = "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
SECRET_URL = "https://api.vk.com/method/wall.get?access_token=VKSECRET123"


def make_record(msg: str, args: object = None) -> logging.LogRecord:
    return logging.LogRecord(
        name="tests",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


@pytest.mark.parametrize("url", VK_URLS)
def test_vk_access_token_masked(url: str) -> None:
    result = redact_text(url)

    assert "VKSECRET123" not in result
    assert "access_token=***" in result.lower()


@pytest.mark.parametrize("url", TG_URLS)
def test_telegram_bot_token_masked(url: str) -> None:
    result = redact_text(url)

    assert TG_TOKEN not in result
    assert "bot***" in result


def test_authorization_header_masked() -> None:
    with_bearer = redact_text("Authorization: Bearer TGTOKEN123456789")
    without_bearer = redact_text("Authorization: MAXTOKEN123456789")

    assert "TGTOKEN123456789" not in with_bearer
    assert "MAXTOKEN123456789" not in without_bearer
    assert with_bearer == "Authorization: Bearer ***"


def test_standalone_bearer_masked() -> None:
    result = redact_text("header=Bearer ABCDEFGHIJKLMN")

    assert "ABCDEFGHIJKLMN" not in result
    assert "Bearer ***" in result


def test_query_token_masked() -> None:
    result = redact_text("https://example.com/cb?token=ABC123SECRET&x=1")

    assert "ABC123SECRET" not in result
    assert "token=***" in result


@pytest.mark.parametrize(
    ("text", "secrets"),
    [
        ("value VKSECRET123 here", ("VKSECRET123",)),
        ("a VKSECRET123 b MAXSECRET456 c", ("VKSECRET123", "MAXSECRET456")),
    ],
)
def test_exact_secret_masked(text: str, secrets: tuple[str, ...]) -> None:
    result = redact_text(text, secrets)

    for secret in secrets:
        assert secret not in result


def test_empty_secrets_leave_text_unchanged() -> None:
    text = "plain text without secrets"

    assert redact_text(text) == text


def test_redaction_is_idempotent() -> None:
    once = redact_text(VK_URLS[0])
    twice = redact_text(once)

    assert once == twice


def test_benign_text_unchanged() -> None:
    text = "tokenizer processed 42 items in 3 steps"

    assert redact_text(text) == text


def test_backslash_in_escaped_json_not_consumed() -> None:
    # Регрессия: маскирование не должно съедать обратный слеш экранирования.
    escaped = 'RuntimeError(\\"failed with access_token=VKSECRET123\\")'

    result = redact_text(escaped)

    assert "VKSECRET123" not in result
    assert '\\"' in result


def test_redact_value_mapping() -> None:
    value = {"url": SECRET_URL, "attempt": 1}

    result = redact_value(value)

    assert isinstance(result, dict)
    assert "VKSECRET123" not in str(result)
    assert result["attempt"] == 1


def test_redact_value_nested() -> None:
    value = {"request": {"url": SECRET_URL}, "ids": [1, 2], "pair": (SECRET_URL, 5)}

    result = redact_value(value)

    assert "VKSECRET123" not in str(result)
    assert result["ids"] == [1, 2]
    assert result["pair"][1] == 5


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, 1),
        (1.5, 1.5),
        (True, True),
        (None, None),
        (["a", "b"], ["a", "b"]),
    ],
)
def test_redact_value_scalars_and_lists(value: object, expected: object) -> None:
    assert redact_value(value) == expected


def test_filter_masks_string_args() -> None:
    record = make_record("GET %s", (SECRET_URL,))

    assert RedactFilter().filter(record) is True
    assert "VKSECRET123" not in record.getMessage()


def test_filter_masks_mapping_args() -> None:
    # Проверка идёт через Logger.info: stdlib сам упаковывает dict в кортеж и
    # распаковывает в record.args. Прямая передача dict в LogRecord недопустима
    # (logging/__init__.py: args[0] -> KeyError).
    captured: list[logging.LogRecord] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    logger = logging.getLogger("crosspost.test.mapping")
    handler = CaptureHandler()
    handler.addFilter(RedactFilter())
    saved_level = logger.level
    saved_propagate = logger.propagate

    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        logger.info("GET %(url)s", {"url": SECRET_URL})
    finally:
        logger.removeHandler(handler)
        logger.setLevel(saved_level)
        logger.propagate = saved_propagate

    assert len(captured) == 1
    assert isinstance(captured[0].args, dict)
    assert "VKSECRET123" not in captured[0].getMessage()


def test_filter_masks_nested_structures() -> None:
    # Кортеж из двух аргументов: stdlib не распаковывает args, рекурсия идёт
    # по кортежу -> dict -> строка.
    payload = {"request": {"url": SECRET_URL}}
    record = make_record("attempt=%d payload=%s", (1, payload))

    assert RedactFilter().filter(record) is True
    assert "VKSECRET123" not in record.getMessage()


def test_filter_keeps_non_string_args() -> None:
    record = make_record("processed %d posts", (5,))

    assert RedactFilter().filter(record) is True
    assert record.args == (5,)
    assert record.getMessage() == "processed 5 posts"


def test_mask_constant_used_in_output() -> None:
    assert redact_text("access_token=VKSECRET123").endswith(MASK)
