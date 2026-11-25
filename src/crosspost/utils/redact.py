"""Маскирование секретов в строках, структурах и записях логов.

Модуль намеренно не импортирует конфигурацию: список секретов передаётся
параметром. Это исключает цикл ``config -> logging_setup -> config``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence

MASK = "***"

# Порядок шаблонов важен: заголовок Authorization обрабатывается раньше
# одиночного Bearer, иначе в строке остаётся "Authorization: *** <token>".
# Обратный слеш исключён из классов символов намеренно: маскирование не
# должно съедать символ экранирования. Токены обратный слеш не содержат.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(access_token=)[^&\s\"'<>\\]+"), rf"\g<1>{MASK}"),
    (re.compile(r"(?i)\b(bot)(\d{5,}:[A-Za-z0-9_-]{20,})"), rf"\g<1>{MASK}"),
    (
        re.compile(r"(?i)\b(authorization[\"']?\s*[:=]\s*[\"']?(?:bearer\s+)?)[^\s\"',}\\]+"),
        rf"\g<1>{MASK}",
    ),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=:-]{8,}"), rf"\g<1>{MASK}"),
    (re.compile(r"(?i)\b(token=)[^&\s\"'<>\\]+"), rf"\g<1>{MASK}"),
)

_MIN_EXACT_SECRET_LEN = 4

_SCALARS: tuple[type, ...] = (int, float, bool, type(None))


def _mask_exact(text: str, secrets: Sequence[str]) -> str:
    for secret in secrets:
        if len(secret) >= _MIN_EXACT_SECRET_LEN and secret in text:
            text = text.replace(secret, MASK)
    return text


def redact_text(text: str, secrets: Sequence[str] = ()) -> str:
    """Вернуть ``text`` с замаскированными секретами.

    Сначала вырезаются точные значения из ``secrets``, затем применяются
    шаблоны для токенов в URL и заголовках. Функция идемпотентна.
    Применять только к исходному тексту, никогда — к готовому JSON.
    """
    result = _mask_exact(text, secrets)
    for pattern, replacement in _PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def redact_value(value: object, secrets: Sequence[str] = ()) -> object:
    """Рекурсивно замаскировать секреты в произвольной структуре.

    Строки маскируются, ``Mapping``/``list``/``tuple`` обходятся рекурсивно,
    скаляры возвращаются без изменений, прочие объекты приводятся к строке.
    """
    if isinstance(value, str):
        return redact_text(value, secrets)
    if isinstance(value, Mapping):
        return {key: redact_value(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item, secrets) for item in value)
    if isinstance(value, _SCALARS):
        return value
    return redact_text(str(value), secrets)


class RedactFilter(logging.Filter):
    """Фильтр, маскирующий секреты до форматирования записи."""

    def __init__(self, secrets: Sequence[str] = ()) -> None:
        super().__init__()
        self._secrets: tuple[str, ...] = tuple(secret for secret in secrets if secret)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(str(record.msg), self._secrets)
        if record.args:
            record.args = redact_value(record.args, self._secrets)
        return True
