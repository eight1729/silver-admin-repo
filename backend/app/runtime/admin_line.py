"""Production-capable Admin composition for the LINE repository boundary."""

from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapter.line_internal_api import HttpLineInternalApiClient
from app.application.admin_line_dispatch import (
    AdminLineOutboxDispatcher,
    AdminLineResultReconciler,
)
from app.application.admin_notification_runner import AdminNotificationRunner
from app.application.admin_service import AdminApplicationService
from app.application.notification_service import NotificationService
from app.core.settings_admin import AdminSettings, admin_settings
from app.db.admin_notification_repository import SqlAlchemyAdminNotificationRepository
from app.db.engine import get_engine
from app.services.http_client import get_client
from app.domain.ports.organization_service_scope import (
    OrganizationServiceScopeResolver,
)


@dataclass
class AdminLineRuntime:
    client: HttpLineInternalApiClient
    repository: SqlAlchemyAdminNotificationRepository
    dispatcher: AdminLineOutboxDispatcher
    reconciler: AdminLineResultReconciler
    runner: AdminNotificationRunner | None = None


def build_admin_line_runtime(
    *,
    engine: AsyncEngine | None = None,
    client: httpx.AsyncClient | None = None,
    runtime_settings: AdminSettings = admin_settings,
) -> AdminLineRuntime:
    shared_engine = engine if engine is not None else get_engine()
    shared_client = client if client is not None else get_client()
    repository = SqlAlchemyAdminNotificationRepository(shared_engine)
    line_client = HttpLineInternalApiClient(
        client=shared_client,
        base_url=runtime_settings.admin_line_internal_api_base_url,
        bearer_token=runtime_settings.admin_line_internal_api_bearer_token,
        environment=runtime_settings.app_env,
    )
    return AdminLineRuntime(
        client=line_client,
        repository=repository,
        dispatcher=AdminLineOutboxDispatcher(
            repository=repository, line_client=line_client
        ),
        reconciler=AdminLineResultReconciler(
            repository=repository, line_client=line_client
        ),
    )


def build_production_admin_application(
    *,
    external_business_gateway,
    queue_gateway,
    service_id: str | None = None,
    organization_id: str | None = None,
    runner_service_ids,
    scope_resolver: OrganizationServiceScopeResolver | None = None,
    engine: AsyncEngine | None = None,
    client: httpx.AsyncClient | None = None,
    runtime_settings: AdminSettings = admin_settings,
):
    """Compose Admin without any LINE sender, identity, credential or payload."""
    boundary = build_admin_line_runtime(
        engine=engine, client=client, runtime_settings=runtime_settings
    )
    if scope_resolver is None:
        from app.adapter.admin_scope import (
            ConfiguredOrganizationServiceScopeResolver,
        )

        if service_id is None or organization_id is None:
            raise RuntimeError("Admin business scope resolver is required")
        scope_resolver = ConfiguredOrganizationServiceScopeResolver({service_id: organization_id})

    boundary.runner = AdminNotificationRunner(
        repository=boundary.repository,
        dispatcher=boundary.dispatcher,
        reconciler=boundary.reconciler,
        service_ids=runner_service_ids,
    )

    def organization(requested_service: str) -> str:
        return scope_resolver.resolve(requested_service).organization_id
    notifications = NotificationService(
        repository=boundary.repository,
        external_business_gateway=external_business_gateway,
        line_sender=None,
        queue_gateway=queue_gateway,
        organization_id_resolver=organization,
        external_business_organization_id_resolver=organization,
        require_scoped_queue=True,
        persist_line_subjects=False,
    )
    application = AdminApplicationService(
        notification_service=notifications,
        external_business_gateway=external_business_gateway,
        demo_service_id=service_id,
        line_linked_member_ids=frozenset(),
        expose_line_subjects=False,
        line_internal_client=boundary.client,
        organization_id_resolver=organization,
        external_business_organization_id_resolver=organization,
        scope_resolver=scope_resolver,
    )

    async def dispatch(*, service_id, operation_id, request_id) -> None:
        persisted_service_id = await boundary.repository.resolve_operation_service_id(
            operation_id
        )
        if persisted_service_id != service_id:
            raise RuntimeError("queued operation service scope does not match persistence")
        scope_resolver.resolve(service_id)
        await boundary.dispatcher.dispatch_operation(
            service_id=service_id, operation_id=operation_id
        )

    register_handler = getattr(queue_gateway, "register_handler", None)
    if callable(register_handler):
        register_handler(dispatch)

    return application, boundary, dispatch
