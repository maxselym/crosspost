from pathlib import Path

from pydantic import AnyHttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    vk_access_token: SecretStr
    vk_group_id: int
    vk_group_domain: str
    vk_api_version: str

    tg_bot_token: SecretStr
    tg_chat_id: int

    max_bot_token: SecretStr
    max_chat_id: int
    max_api_url: AnyHttpUrl
    max_ca_file: Path | None = None

    http_timeout_seconds: float = 20.0
    upload_timeout_seconds: float = 300.0

    @field_validator("vk_access_token", "tg_bot_token", "max_bot_token")
    @classmethod
    def validate_non_empty_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("Token must not be empty")
        return value

    @field_validator("vk_group_id")
    @classmethod
    def validate_positive_group_id(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("vk_group_id must be positive")
        return value

    @field_validator("tg_chat_id", "max_chat_id")
    @classmethod
    def validate_non_zero_chat_id(cls, value: int) -> int:
        if value == 0:
            raise ValueError("Chat ID must not be zero")
        return value

    @field_validator("max_ca_file")
    @classmethod
    def validate_ca_file(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_file():
            raise ValueError(f"CA file not found: {value}")
        return value

    @field_validator("http_timeout_seconds")
    @classmethod
    def validate_positive_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("http_timeout_seconds must be positive")
        return value

    @field_validator("upload_timeout_seconds")
    @classmethod
    def validate_positive_upload_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("upload_timeout_seconds must be positive")
        return value


settings = Settings()
