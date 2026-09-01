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

    from app.adapter.admin_scope import ConfiguredOrganizationServiceScopeResolver

    scope_resolver = ConfiguredOrganizationServiceScopeResolver(
        runtime_settings.admin_local_integration_scopes
    )

    if external_business is None:
        from app.testing.local_integration import build_local_integration_external_business

        external_business = build_local_integration_external_business(
            scope_resolver.scopes
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
    )
    return LocalIntegrationAdminComposition(
        application=application,
        boundary=boundary,
        queue=queue,
        external_business=external_business,
        dispatch=dispatch,
        scope_resolver=scope_resolver,
    )
