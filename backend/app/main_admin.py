from fastapi import APIRouter, FastAPI

from app.app_factory import configure_shared_infrastructure, shared_lifespan
from app.api.admin_entry_deps import get_admin_application_service
from app.api.routes.admin import router as admin_router
from app.api.admin_auth import get_admin_runtime_settings
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
    app.include_router(_health_router())
    app.include_router(admin_router)
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

        def get_local_admin_application_service():
            return composition.application

        app.dependency_overrides[get_admin_application_service] = (
            get_local_admin_application_service
        )
    app.dependency_overrides[get_admin_runtime_settings] = lambda: runtime_settings
    return app


app = create_admin_app()
