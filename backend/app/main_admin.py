from fastapi import APIRouter, FastAPI

from app.app_factory import configure_shared_infrastructure, shared_lifespan
from app.api.admin_entry_deps import get_admin_application_service
from app.api.routes.admin import router as admin_router
from app.api.routes.admin_internal import router as admin_internal_router
from app.api.admin_auth import get_admin_runtime_settings
from app.core.settings_admin import AdminSettings, admin_settings
from app.db.engine import configure_database_url


def _external_business_from_settings(runtime_settings: AdminSettings, environment: str):
    """Build the HTTP provider when a business API URL is configured, else None.

    Returning None leaves both the Internal API and the production composition on
    the Current DB Adapter, so behaviour is unchanged until the setting is added.
    """
    base_url = (runtime_settings.admin_external_business_base_url or "").strip()
    if not base_url:
        return None
    from app.adapter.external_business_http import HttpExternalBusinessGateway
    from app.services.http_client import get_client

    return HttpExternalBusinessGateway(
        # The shared client is closed by the app lifespan; a private one is not.
        client=get_client(),
        base_url=base_url,
        audience=runtime_settings.admin_external_business_audience,
        environment=environment,
    )


def _health_router() -> APIRouter:
    router = APIRouter()
    @router.get("/health", tags=["health"])
    async def health(): return {"status": "ok", "owner": "admin"}
    return router


def create_admin_app(
    runtime_settings: AdminSettings = admin_settings,
    *,
    admin_service_provider=None,
    external_business_gateway=None,
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
    # Build the external business provider once and hand the same instance to
    # both the Internal API (app.state) and the production composition. Wiring
    # only one of them splits the app: staff screens would read one provider
    # while the Internal API reads another. An explicitly injected gateway
    # (tests) wins; otherwise it is built from settings.
    injected_external_business = external_business_gateway is not None
    if external_business_gateway is None:
        external_business_gateway = _external_business_from_settings(
            runtime_settings, environment
        )
    app.state.admin_internal_business_gateway = external_business_gateway
    app.include_router(_health_router())
    app.include_router(admin_router)
    # Distributed separately as the Admin-owned internal contract artifact.
    app.include_router(admin_internal_router, include_in_schema=False)
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
    elif not injected_external_business and runtime_settings.notification_runner_service_ids:
        # Canonical production-shaped composition. Runner ownership is a
        # dedicated setting, separate from Internal API authorization scopes.
        from app.runtime.admin_local_integration import build_admin_composition

        missing_scopes = set(runtime_settings.notification_runner_service_ids) - set(runtime_settings.admin_internal_api_scopes)
        if missing_scopes:
            raise RuntimeError("notification runner service scope is not configured")
        composition = build_admin_composition(
            runtime_settings=runtime_settings,
            scopes={service_id: runtime_settings.admin_internal_api_scopes[service_id]
                    for service_id in runtime_settings.notification_runner_service_ids
                    if service_id in runtime_settings.admin_internal_api_scopes},
            runner_service_ids=runtime_settings.notification_runner_service_ids,
            # None makes build_admin_composition fall back to the Current DB.
            external_business=external_business_gateway,
        )
        app.state.admin_runtime_composition = composition

        def get_runtime_admin_application_service():
            return composition.application

        app.dependency_overrides[get_admin_application_service] = (
            get_runtime_admin_application_service
        )
    app.dependency_overrides[get_admin_runtime_settings] = lambda: runtime_settings
    return app


app = create_admin_app()
