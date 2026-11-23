from pydantic import SecretStr, field_validator
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

    @field_validator("vk_access_token")
    @classmethod
    def validate_access_token(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("VK_ACCESS_TOKEN must not be empty")
        return value
