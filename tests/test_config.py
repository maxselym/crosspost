from pathlib import Path

import pytest
from pydantic import ValidationError

from crosspost.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"

VALID_PARAMS: dict[str, object] = {
    "vk_access_token": "vk-test-token",
    "vk_group_id": 1,
    "vk_group_domain": "test_group",
    "vk_api_version": "5.199",
    "tg_bot_token": "tg-test-token",
    "tg_chat_id": -1001234567890,
    "max_bot_token": "max-test-token",
    "max_chat_id": -100,
    "max_api_url": "https://max.example.com",
}


def build_settings(**overrides: object) -> Settings:
    params: dict[str, object] = {**VALID_PARAMS, **overrides}
    return Settings(_env_file=None, **params)


def read_env_example() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def test_valid_settings_apply_defaults() -> None:
    settings = build_settings()

    assert settings.http_timeout_seconds == 20.0
    assert settings.max_ca_file is None


def test_secrets_are_not_rendered_in_repr() -> None:
    settings = build_settings()

    assert settings.vk_access_token.get_secret_value() == "vk-test-token"
    assert "vk-test-token" not in repr(settings)


@pytest.mark.parametrize("timeout", [0, -1, -0.5])
def test_http_timeout_must_be_positive(timeout: float) -> None:
    with pytest.raises(ValidationError):
        build_settings(http_timeout_seconds=timeout)


@pytest.mark.parametrize("group_id", [0, -1])
def test_vk_group_id_must_be_positive(group_id: int) -> None:
    with pytest.raises(ValidationError):
        build_settings(vk_group_id=group_id)


@pytest.mark.parametrize("field_name", ["tg_chat_id", "max_chat_id"])
def test_chat_id_must_not_be_zero(field_name: str) -> None:
    with pytest.raises(ValidationError):
        build_settings(**{field_name: 0})


@pytest.mark.parametrize("token_field", ["vk_access_token", "tg_bot_token", "max_bot_token"])
@pytest.mark.parametrize("blank", ["", "   "])
def test_empty_token_rejected(token_field: str, blank: str) -> None:
    with pytest.raises(ValidationError):
        build_settings(**{token_field: blank})


def test_missing_ca_file_rejected(tmp_path: Path) -> None:
    missing = tmp_path / "absent.pem"

    with pytest.raises(ValidationError):
        build_settings(max_ca_file=missing)


def test_existing_ca_file_accepted(tmp_path: Path) -> None:
    ca = tmp_path / "chain.pem"
    ca.write_text("test", encoding="utf-8")

    settings = build_settings(max_ca_file=ca)

    assert settings.max_ca_file == ca


def test_env_example_has_no_unknown_keys() -> None:
    known_fields = {name.upper() for name in Settings.model_fields}

    assert set(read_env_example()) <= known_fields


def test_env_example_values_are_parseable() -> None:
    values = read_env_example()

    for key in ("VK_GROUP_ID", "TG_CHAT_ID", "MAX_CHAT_ID"):
        raw = values.get(key, "")
        if raw:
            assert int(raw) != 0, key

    assert float(values["HTTP_TIMEOUT_SECONDS"]) > 0


def test_upload_timeout_default() -> None:
    settings = build_settings()

    assert settings.upload_timeout_seconds == 300.0


@pytest.mark.parametrize("timeout", [0, -1, -0.5])
def test_upload_timeout_must_be_positive(timeout: float) -> None:
    with pytest.raises(ValidationError):
        build_settings(upload_timeout_seconds=timeout)
