from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.settings_paths import ROOT_ENV_FILE


class Settings(BaseSettings):

    app_env: str = "local"

    database_url: str

    # Admin-owned client configuration for the Admin -> LINE repository boundary.
    admin_line_internal_api_base_url: str | None = None
    admin_line_internal_api_bearer_token: SecretStr | None = None

    model_config = SettingsConfigDict(
        env_file=str(ROOT_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]
