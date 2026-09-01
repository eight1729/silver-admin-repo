from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.settings_paths import ROOT_ENV_FILE


class Settings(BaseSettings):

    app_env: str = "local"

    cors_allowed_origins: str = ""

    enable_dev_routes: bool = False

    database_url: str

    line_login_channel_id: str | None = None

    line_messaging_channel_access_token: str | None = None

    liff_url: str | None = None

    # LINE-owned canonical LIFF entry bases, keyed by organization then service.
    # Values are supplied as a JSON object by deployment configuration.
    line_canonical_liff_entry_bases: dict[str, dict[str, str]] = Field(
        default_factory=dict
    )

    # LINE-owned Command sender credentials, keyed by organization then service.
    line_command_messaging_access_tokens: dict[
        str, dict[str, SecretStr]
    ] = Field(default_factory=dict)

    # Backend-to-backend credential for the LINE-owned internal API.  This is
    # intentionally distinct from organization/service Messaging credentials.
    line_internal_api_bearer_token: SecretStr | None = None

    # Admin-owned client configuration for the Admin -> LINE repository boundary.
    admin_line_internal_api_base_url: str | None = None
    admin_line_internal_api_bearer_token: SecretStr | None = None

    enable_staging_line_send: bool = False

    staging_line_allowed_member_id: str = ""

    staging_line_max_recipients: int = 1

    staging_line_message_prefix: str = "\u3010\u691c\u8a3c\u901a\u77e5\u3011"

    model_config = SettingsConfigDict(
        env_file=str(ROOT_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]
