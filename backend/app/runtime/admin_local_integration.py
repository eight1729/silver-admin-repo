"""Explicit local wiring for the pre-split Admin-to-LINE HTTP boundary."""

from dataclasses import dataclass

from app.adapter.local_inline_notification_queue import LocalInlineNotificationQueue
from app.application.admin_service import AdminApplicationService
from app.core.settings_admin import AdminSettings
from app.runtime.admin_line import (
    AdminLineRuntime,
    build_production_admin_application,
)


@dataclass(frozen=True)
class LocalIntegrationAdminComposition:
    application: AdminApplicationService
    boundary: AdminLineRuntime
    queue: object
    external_business: object
    dispatch: object
    scope_resolver: object


def build_local_integration_admin_composition(
    *,
    runtime_settings: AdminSettings,
    engine=None,
    client=None,
    external_business=None,
    queue=None,
) -> LocalIntegrationAdminComposition:
    if runtime_settings.app_env.strip().lower() != "local":
        raise RuntimeError("Admin local integration mode requires APP_ENV=local")
    if not runtime_settings.admin_local_integration_mode:
        raise RuntimeError("Admin local integration mode is not enabled")
    return build_admin_composition(
        runtime_settings=runtime_settings,
        scopes=runtime_settings.admin_local_integration_scopes,
        runner_service_ids=runtime_settings.notification_runner_service_ids,
        engine=engine, client=client, external_business=external_business, queue=queue,
    )


def build_admin_composition(*, runtime_settings, scopes, runner_service_ids, engine=None, client=None,
                            external_business=None, queue=None) -> LocalIntegrationAdminComposition:

    if not scopes or not runner_service_ids or set(runner_service_ids) - set(scopes):
        raise RuntimeError("notification runner service scope is not configured")

    from app.adapter.admin_scope import ConfiguredOrganizationServiceScopeResolver

    scope_resolver = ConfiguredOrganizationServiceScopeResolver(
        scopes
    )

    if external_business is None:
        from app.adapter.current_db_external_business import CurrentDbExternalBusinessGateway
        from app.db.engine import get_engine

        external_business = CurrentDbExternalBusinessGateway(
            engine if engine is not None else get_engine(),
            runtime_settings.current_db_business_centers,
        )
    if queue is None:
        queue = LocalInlineNotificationQueue()

    application, boundary, dispatch = build_production_admin_application(
        external_business_gateway=external_business,
        queue_gateway=queue,
        scope_resolver=scope_resolver,
        engine=engine,
        client=client,
        runtime_settings=runtime_settings,
        runner_service_ids=runner_service_ids,
    )
    return LocalIntegrationAdminComposition(
        application=application,
        boundary=boundary,
        queue=queue,
        external_business=external_business,
        dispatch=dispatch,
        scope_resolver=scope_resolver,
    )
