from pydantic import Field, SecretStr, model_validator
from pydantic_settings import SettingsConfigDict

from app.core.settings_paths import ADMIN_ENV_FILE
from app.core.settings_shared import SharedSettings


class AdminSettings(SharedSettings):
    admin_cors_allowed_origins: str = ""
    admin_line_internal_api_base_url: str | None = None
    admin_line_internal_api_bearer_token: SecretStr | None = None
    admin_oidc_enabled: bool = False
    admin_oidc_issuer: str | None = None
    admin_oidc_audience: str | None = None
    admin_oidc_jwks_url: str | None = None
    admin_oidc_algorithms: str = "RS256"
    admin_local_integration_mode: bool = False
    admin_local_integration_scopes: dict[str, str] = Field(default_factory=dict)

    # -- ic（外部業務システム）への接続。staging / production で使う --------------
    # base URL は ic 業務 API の Cloud Run URL。**ID トークンの audience にもなる**
    admin_external_business_base_url: str | None = None
    # service_id → organization_id。ic 側では organization_id が tenant_id
    admin_external_business_scopes: dict[str, str] = Field(default_factory=dict)

    # -- 入口の鍵 ---------------------------------------------------------------
    # APP_ENV=staging は全リクエストを認証なしの Admin ロールとして扱う。
    # これが無いと URL を知る誰でも台帳を操作できる
    admin_static_bearer_token: SecretStr | None = None
    # LINE 窓口 → Admin（本人照合）。職員用とは別のトークン
    admin_line_inbound_bearer_token: SecretStr | None = None
    # 台帳を全消しする POST /admin/demo/reset。**既定は無効**
    admin_allow_demo_reset: bool = False

    # -- Cloud Scheduler → Admin（配信結果の突き合わせ）。両方揃って初めて通す ------
    admin_reconcile_audience: str | None = None
    admin_reconcile_caller: str | None = None

    model_config = SettingsConfigDict(
        env_file=str(ADMIN_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def demo_reset_enabled(self) -> bool:
        """台帳を全消しする `POST /admin/demo/reset` を生かすか。

        local / development / demo は今までどおり使える（フロントの
        `environment-policy.ts` もこの 3 つで reset を表示する）。**外に出る
        staging / production では設定で明示的に許したときだけ。**
        """
        if self.app_env.strip().lower() in {"local", "development", "demo"}:
            return True
        return self.admin_allow_demo_reset

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


admin_settings = AdminSettings()  # type: ignore[call-arg]
