from fastapi import APIRouter, FastAPI

from app.app_factory import configure_shared_infrastructure, shared_lifespan
from app.api.admin_entry_deps import get_admin_application_service
from app.api.routes.admin import router as admin_router
from app.api.routes.internal_line import router as internal_line_router
from app.api.admin_auth import get_admin_runtime_settings
from app.api.static_bearer import install_static_bearer_guard
from app.core.settings_admin import AdminSettings, admin_settings
from app.db.engine import configure_database_url


def _health_router() -> APIRouter:
    router = APIRouter()
    @router.get("/health", tags=["health"])
    async def health(): return {"status": "ok", "owner": "admin"}
    return router


def create_admin_app(
    runtime_settings: AdminSettings = admin_settings,
    *,
    admin_service_provider=None,
) -> FastAPI:
    configure_database_url(runtime_settings.database_url)
    environment = runtime_settings.app_env.strip().lower()
    if environment not in {"local", "development", "demo", "staging", "production", "test"}:
        raise RuntimeError("unsupported Admin application environment")
    if runtime_settings.admin_local_integration_mode and environment != "local":
        raise RuntimeError("Admin local integration mode requires APP_ENV=local")
    app = FastAPI(
        title="Silver Admin Backend", version="1.0.0", lifespan=shared_lifespan,
        docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json",
    )
    configure_shared_infrastructure(
        app,
        runtime_settings.admin_cors_allowed_origins,
        additional_allowed_headers=("X-Service-ID",),
    )
    app.state.admin_runtime_settings = runtime_settings
    # ★入口の鍵。APP_ENV=staging は全リクエストを認証なしの Admin ロールとして扱うので、
    #   これが無いと URL を知る誰でも台帳を消せる。設定が無ければ何もしない（local / test は現状のまま）
    install_static_bearer_guard(app, runtime_settings)
    app.include_router(_health_router())
    app.include_router(admin_router)
    app.include_router(internal_line_router)
    if admin_service_provider is not None:
        app.dependency_overrides[get_admin_application_service] = admin_service_provider
    elif runtime_settings.admin_local_integration_mode:
        from app.runtime.admin_local_integration import (
            build_local_integration_admin_composition,
        )

        composition = build_local_integration_admin_composition(
            runtime_settings=runtime_settings
        )
        app.state.admin_local_integration = composition
        app.state.admin_composition = composition

        def get_local_admin_application_service():
            return composition.application

        app.dependency_overrides[get_admin_application_service] = (
            get_local_admin_application_service
        )
    elif environment in {"staging", "production"} and _configured(
        runtime_settings.admin_external_business_base_url
    ):
        # ★ic を外部業務システムとして繋ぐ合成。これが無いと画面は 503 のまま
        from app.runtime.admin_production import build_production_admin_composition

        composition = build_production_admin_composition(runtime_settings=runtime_settings)
        app.state.admin_composition = composition

        def get_production_admin_application_service():
            return composition.application

        app.dependency_overrides[get_admin_application_service] = (
            get_production_admin_application_service
        )
    app.dependency_overrides[get_admin_runtime_settings] = lambda: runtime_settings
    return app


def _configured(value: str | None) -> bool:
    return bool(value and value.strip())


app = create_admin_app()
