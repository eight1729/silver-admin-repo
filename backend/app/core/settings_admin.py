import os

from pydantic import Field, SecretStr
from pydantic_settings import SettingsConfigDict

from app.core.environment import application_environment
from app.core.settings_paths import ADMIN_ENV_FILE
from app.core.settings_shared import SharedSettings


class AdminSettings(SharedSettings):
    admin_cors_allowed_origins: str = ""
    admin_internal_api_bearer_token: SecretStr | None = None
    admin_internal_api_scopes: dict[str, str] = Field(default_factory=dict)
    current_db_business_centers: dict[str, str] = Field(default_factory=dict)
    admin_line_internal_api_base_url: str | None = None
    admin_line_internal_api_bearer_token: SecretStr | None = None
    # External business API. Unset keeps the Current DB Adapter.
    admin_external_business_base_url: str | None = None
    # ID token audience. Unset uses the base URL.
    admin_external_business_audience: str | None = None
    admin_oidc_enabled: bool = False
    admin_oidc_issuer: str | None = None
    admin_oidc_audience: str | None = None
    admin_oidc_jwks_url: str | None = None
    admin_oidc_algorithms: str = "RS256"
    admin_notification_runner_service_ids: str = ""

    model_config = SettingsConfigDict(
        # Source selection must precede construction of the eager dotenv source.
        env_file=None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    def __init__(self, **values):
        process_environment = next((value for key, value in os.environ.items()
                                    if key.lower() == "app_env"), None)
        environment = application_environment(values.get("app_env", process_environment))
        env_file = values.pop("_env_file", ADMIN_ENV_FILE)
        values["app_env"] = environment
        super().__init__(_env_file=env_file if environment == "local" else None, **values)

    def validate_runtime(self) -> None:
        """Fail before serving requests, without DB/JWKS/LINE network calls."""
        from app.adapter.admin_scope import ConfiguredOrganizationServiceScopeResolver
        from app.adapter.line_internal_api import HttpLineInternalApiClient
        from app.adapter.oidc_staff_auth import OidcTokenValidator

        if not self.database_url.strip():
            raise ValueError("DATABASE_URL is required")
        if not self.admin_oidc_enabled:
            raise ValueError("ADMIN_OIDC_ENABLED must be true")
        OidcTokenValidator(
            issuer=self.admin_oidc_issuer or "", audience=self.admin_oidc_audience or "",
            jwks_url=self.admin_oidc_jwks_url or "",
            algorithms=tuple(item.strip() for item in self.admin_oidc_algorithms.split(",") if item.strip()),
            client=None,
        )
        if self.app_env == "production":
            from urllib.parse import urlsplit
            if urlsplit(self.admin_oidc_jwks_url or "").scheme != "https":
                raise ValueError("production OIDC JWKS URL requires HTTPS")
        resolver = ConfiguredOrganizationServiceScopeResolver(self.admin_internal_api_scopes)
        if not self.notification_runner_service_ids:
            raise ValueError("ADMIN_NOTIFICATION_RUNNER_SERVICE_IDS is required")
        for service_id in self.notification_runner_service_ids:
            resolver.resolve(service_id)
        import re
        token = self.admin_internal_api_bearer_token
        if token is None or not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", token.get_secret_value()):
            raise ValueError("ADMIN_INTERNAL_API_BEARER_TOKEN is required and must be a Bearer credential")
        HttpLineInternalApiClient(client=None, base_url=self.admin_line_internal_api_base_url,
                                  bearer_token=self.admin_line_internal_api_bearer_token,
                                  environment=self.app_env)
        if not self.admin_external_business_base_url:
            from app.adapter.current_db_external_business import CurrentDbExternalBusinessGateway
            gateway = CurrentDbExternalBusinessGateway(None, self.current_db_business_centers)
            for organization in self.admin_internal_api_scopes.values():
                gateway._center(organization)

    @property
    def notification_runner_service_ids(self) -> tuple[str, ...]:
        values = tuple(item.strip() for item in self.admin_notification_runner_service_ids.split(",") if item.strip())
        if len(values) != len(set(values)):
            raise ValueError("ADMIN_NOTIFICATION_RUNNER_SERVICE_IDS contains duplicates")
        return values


admin_settings = AdminSettings()  # type: ignore[call-arg]
