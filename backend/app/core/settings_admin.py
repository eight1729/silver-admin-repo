from pydantic import Field, SecretStr, model_validator
from pydantic_settings import SettingsConfigDict

from app.core.settings_paths import ADMIN_ENV_FILE
from app.core.settings_shared import SharedSettings


class AdminSettings(SharedSettings):
    admin_cors_allowed_origins: str = ""
    admin_internal_api_bearer_token: SecretStr | None = None
    admin_internal_api_scopes: dict[str, str] = Field(default_factory=dict)
    current_db_business_centers: dict[str, str] = Field(default_factory=dict)
    admin_line_internal_api_base_url: str | None = None
    admin_line_internal_api_bearer_token: SecretStr | None = None
    admin_oidc_enabled: bool = False
    admin_oidc_issuer: str | None = None
    admin_oidc_audience: str | None = None
    admin_oidc_jwks_url: str | None = None
    admin_oidc_algorithms: str = "RS256"
    admin_local_integration_mode: bool = False
    admin_local_integration_scopes: dict[str, str] = Field(default_factory=dict)
    admin_notification_runner_service_ids: str = ""

    model_config = SettingsConfigDict(
        env_file=str(ADMIN_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def local_integration_is_local_only(self):
        if (
            self.admin_local_integration_mode
            and self.app_env.strip().lower() != "local"
        ):
            raise ValueError("Admin local integration mode requires APP_ENV=local")
        if (
            self.admin_local_integration_mode
            and not self.admin_local_integration_scopes
        ):
            raise ValueError(
                "Admin local integration mode requires configured scopes"
            )
        return self

    @property
    def notification_runner_service_ids(self) -> tuple[str, ...]:
        values = tuple(item.strip() for item in self.admin_notification_runner_service_ids.split(",") if item.strip())
        if len(values) != len(set(values)):
            raise ValueError("ADMIN_NOTIFICATION_RUNNER_SERVICE_IDS contains duplicates")
        return values


admin_settings = AdminSettings()  # type: ignore[call-arg]
