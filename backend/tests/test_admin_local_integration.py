from types import SimpleNamespace
from datetime import datetime, timezone
import inspect
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.adapter.line_internal_api import HttpLineInternalApiClient
from app.adapter.admin_scope import ConfiguredOrganizationServiceScopeResolver
from app.adapter.local_inline_notification_queue import LocalInlineNotificationQueue
from app.api.admin_entry_deps import (
    get_admin_application_service,
    get_admin_line_send_mode_for_runtime,
)
from app.api.admin_auth import get_staff_authenticator_http
from app.contracts.admin_line_internal_v1 import SendCapabilityResponse
from app.application.admin_line_dispatch import (
    AdminLineOutboxDispatcher,
    AdminLineResultReconciler,
)
from app.core.settings_admin import AdminSettings
from app.db.admin_notification_repository import (
    SqlAlchemyAdminNotificationRepository,
)
from app.db.engine import set_engine
from app.main_admin import create_admin_app
from app.runtime.admin_local_integration import (
    LocalIntegrationAdminComposition,
    build_local_integration_admin_composition,
)
from app.testing.fakes.external_business import FakeExternalBusinessGateway
from app.testing.local_integration import build_local_integration_external_business
from app.adapter.current_db_external_business import CurrentDbExternalBusinessGateway
from app.domain.errors.errors import ExternalBusinessNotConfiguredError
from app.domain.ports.organization_service_scope import (
    OrganizationServiceScopeNotConfiguredError,
)
from app.adapter.staff_auth import DemoStaffAuthenticator


@pytest.fixture(autouse=True)
def _isolate_process_engine():
    set_engine(None)
    yield
    set_engine(None)


def _settings(*, environment="local", enabled=True, scopes=None):
    return AdminSettings(
        _env_file=None,
        database_url="postgresql+asyncpg://unused/unused",
        app_env=environment,
        admin_local_integration_mode=enabled,
        admin_notification_runner_service_ids="service-a,service-b" if enabled else "",
        admin_local_integration_scopes=(
            {"service-a": "organization-a", "service-b": "organization-b"}
            if scopes is None and enabled
            else scopes or {}
        ),
        admin_line_internal_api_base_url="http://line.internal",
        admin_line_internal_api_bearer_token=SecretStr("test-only"),
        current_db_business_centers={"organization-a": "center-a", "organization-b": "center-b"},
    )


def test_default_local_keeps_compatibility_dependency():
    app = create_admin_app(_settings(enabled=False))
    assert get_admin_application_service not in app.dependency_overrides
    assert not hasattr(app.state, "admin_local_integration")


@pytest.mark.asyncio
async def test_default_local_keeps_fake_send_mode(monkeypatch):
    expected = {
        "mode": "fake", "max_recipients": None, "message_prefix": None,
        "live_send_enabled": False, "ready": False, "blocking_reasons": (),
    }
    monkeypatch.setattr(
        "app.api.admin_entry_deps.get_admin_line_send_mode", lambda: expected
    )
    assert await get_admin_line_send_mode_for_runtime(_settings(enabled=False)) == expected


def _readiness_integration(*, ready=True, error=None):
    async def check(request):
        if error:
            raise error
        return SendCapabilityResponse(mode="staging_live",
            ready=ready, live_send_enabled=ready, max_recipients=1,
            message_prefix="【検証通知】", blocking_reasons=() if ready else ("live_send_disabled",),
        )
    return SimpleNamespace(
        scope_resolver=ConfiguredOrganizationServiceScopeResolver(
            {"service-a": "organization-a"}
        ),
        boundary=SimpleNamespace(
            client=SimpleNamespace(check_send_capability=check)
        ),
    )


@pytest.mark.asyncio
async def test_local_integration_uses_line_ready_response():
    mode = await get_admin_line_send_mode_for_runtime(
        _settings(), integration=_readiness_integration(), service_id="service-a"
    )
    assert mode["mode"] == "staging_live"
    assert mode["ready"] is True and mode["max_recipients"] == 1


@pytest.mark.asyncio
async def test_local_integration_reflects_line_not_ready_response():
    mode = await get_admin_line_send_mode_for_runtime(
        _settings(), integration=_readiness_integration(ready=False), service_id="service-a"
    )
    assert mode["mode"] == "staging_live"
    assert mode["ready"] is False and mode["live_send_enabled"] is False


@pytest.mark.asyncio
async def test_local_integration_readiness_failure_is_fail_closed():
    mode = await get_admin_line_send_mode_for_runtime(
        _settings(), integration=_readiness_integration(error=RuntimeError("down")),
        service_id="service-a",
    )
    assert mode == {
        "mode": "unavailable", "max_recipients": None, "message_prefix": None,
        "live_send_enabled": False, "ready": False,
        "blocking_reasons": ("line_capability_unavailable",),
    }


def test_local_integration_uses_phase4_persistent_http_composition():
    external = FakeExternalBusinessGateway()
    queue = LocalInlineNotificationQueue()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(202, json={"status": "accepted"})
        )
    )
    composition = build_local_integration_admin_composition(
        runtime_settings=_settings(),
        engine=object(),
        client=client,
        external_business=external,
        queue=queue,
    )

    assert composition.external_business is external
    assert composition.queue is queue
    assert isinstance(composition.boundary.repository, SqlAlchemyAdminNotificationRepository)
    assert isinstance(composition.boundary.client, HttpLineInternalApiClient)
    assert isinstance(composition.boundary.dispatcher, AdminLineOutboxDispatcher)
    assert isinstance(composition.boundary.reconciler, AdminLineResultReconciler)
    assert composition.application.notification_service._repository is composition.boundary.repository
    assert composition.application.notification_service._line_sender is None
    assert queue._handler is composition.dispatch


def test_default_local_integration_builds_current_db_without_fake():
    composition = build_local_integration_admin_composition(
        runtime_settings=_settings(),
        engine=object(),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(202, json={"status": "accepted"})
            )
        ),
    )
    assert isinstance(composition.external_business, CurrentDbExternalBusinessGateway)
    assert isinstance(composition.queue, LocalInlineNotificationQueue)
    assert composition.application.notification_service._line_sender is None
    assert not hasattr(composition.boundary, "line_sender")


def test_default_local_integration_missing_centers_fails_without_fixture_fallback():
    settings = _settings().model_copy(update={"current_db_business_centers": {}})
    with pytest.raises(ExternalBusinessNotConfiguredError):
        build_local_integration_admin_composition(
            runtime_settings=settings, engine=object(), client=object(),
        )


def test_admin_app_switches_dependency_only_when_integration_is_enabled(monkeypatch):
    application = object()
    sentinel = LocalIntegrationAdminComposition(
        application=application,
        boundary=SimpleNamespace(),
        queue=SimpleNamespace(),
        external_business=SimpleNamespace(),
        dispatch=SimpleNamespace(),
        scope_resolver=SimpleNamespace(),
    )
    monkeypatch.setattr(
        "app.runtime.admin_local_integration.build_local_integration_admin_composition",
        lambda **kwargs: sentinel,
    )
    app = create_admin_app(_settings())
    assert app.state.admin_local_integration is sentinel
    provider = app.dependency_overrides[get_admin_application_service]
    assert len(inspect.signature(provider).parameters) == 0
    assert provider() is application


@pytest.mark.asyncio
async def test_local_integration_jobs_resolves_application_provider_via_asgi(monkeypatch):
    class Application:
        def __init__(self):
            self.calls = []

        async def list_jobs(self, service_id):
            self.calls.append(service_id)
            return ()

    application = Application()
    sentinel = LocalIntegrationAdminComposition(
        application=application,
        boundary=SimpleNamespace(),
        queue=SimpleNamespace(),
        external_business=SimpleNamespace(),
        dispatch=SimpleNamespace(),
        scope_resolver=SimpleNamespace(),
    )
    monkeypatch.setattr(
        "app.runtime.admin_local_integration.build_local_integration_admin_composition",
        lambda **kwargs: sentinel,
    )
    app = create_admin_app(_settings())
    app.dependency_overrides[get_staff_authenticator_http] = (
        lambda: DemoStaffAuthenticator(service_id="service-a")
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/admin/jobs", headers={"X-Service-ID": "service-a"}
        )

    assert response.status_code == 200, response.text
    assert response.json() == []
    assert application.calls == ["service-a"]


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_nonlocal_environment_rejects_local_integration(environment):
    with pytest.raises(ValidationError, match="requires APP_ENV=local"):
        _settings(environment=environment)


def test_composition_rejects_disabled_flag():
    with pytest.raises(RuntimeError, match="not enabled"):
        build_local_integration_admin_composition(
            runtime_settings=_settings(enabled=False),
            engine=object(),
            client=object(),
            external_business=object(),
            queue=object(),
        )


def test_integration_settings_require_at_least_one_scope():
    with pytest.raises(ValidationError, match="requires configured scopes"):
        _settings(scopes={})


def test_scope_resolver_supports_two_scopes_and_fails_closed():
    resolver = ConfiguredOrganizationServiceScopeResolver(
        {"service-a": "organization-a", "service-b": "organization-b"}
    )
    assert resolver.resolve("service-a").model_dump() == {
        "organization_id": "organization-a",
        "service_id": "service-a",
    }
    assert resolver.resolve("service-b").model_dump() == {
        "organization_id": "organization-b",
        "service_id": "service-b",
    }
    with pytest.raises(OrganizationServiceScopeNotConfiguredError):
        resolver.resolve("unknown-service")


@pytest.mark.parametrize(
    "mapping",
    [
        {"": "organization-a"},
        {"service-a": ""},
        {" service-a": "organization-a"},
        {"service-a": "organization-a "},
    ],
)
def test_scope_resolver_rejects_missing_or_noncanonical_identifiers(mapping):
    with pytest.raises(ValueError, match="scope identifiers"):
        ConfiguredOrganizationServiceScopeResolver(mapping)


@pytest.mark.asyncio
async def test_two_services_use_isolated_external_business_organizations():
    composition = build_local_integration_admin_composition(
        runtime_settings=_settings(),
        external_business=build_local_integration_external_business(
            ConfiguredOrganizationServiceScopeResolver(_settings().admin_local_integration_scopes).scopes
        ),
        engine=object(),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(202, json={"status": "accepted"})
            )
        ),
    )
    await composition.application.list_jobs("service-a")
    await composition.application.list_jobs("service-b")
    external = composition.external_business
    assert external.gateways["organization-a"].calls[0].kwargs[
        "external_organization_id"
    ] == "organization-a"
    assert external.gateways["organization-b"].calls[0].kwargs[
        "external_organization_id"
    ] == "organization-b"
    assert external.gateways["organization-a"] is not external.gateways["organization-b"]


def _outbox_for_scope(organization_id, service_id):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        command_id=uuid4(),
        operation_id=uuid4(),
        target_id=uuid4(),
        organization_id=organization_id,
        service_id=service_id,
        external_member_id="member-1",
        job_id="job-1",
        job_version="v1",
        business_message=SimpleNamespace(
            greeting="hello", introduction="job", note="note"
        ),
        message_version=1,
        message_hash="a" * 64,
        idempotency_key=str(uuid4()),
        correlation_id="request-1",
        requested_at=now,
    )


def test_outbox_commands_preserve_each_scope_without_crossing():
    command_a = AdminLineOutboxDispatcher._command(
        _outbox_for_scope("organization-a", "service-a")
    )
    command_b = AdminLineOutboxDispatcher._command(
        _outbox_for_scope("organization-b", "service-b")
    )
    assert command_a.scope.organization_id == "organization-a"
    assert command_a.scope.service_id == "service-a"
    assert command_b.scope.organization_id == "organization-b"
    assert command_b.scope.service_id == "service-b"
    assert command_a.scope != command_b.scope


@pytest.mark.asyncio
async def test_same_runtime_dispatches_two_persisted_services_without_cross_scope(
    monkeypatch,
):
    composition = build_local_integration_admin_composition(
        runtime_settings=_settings(),
        engine=object(),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(202, json={"status": "accepted"})
            )
        ),
        external_business=FakeExternalBusinessGateway(),
        queue=LocalInlineNotificationQueue(),
    )
    operation_a, operation_b, operation_unknown = uuid4(), uuid4(), uuid4()
    persisted = {
        operation_a: "service-a",
        operation_b: "service-b",
        operation_unknown: "unknown-service",
    }
    dispatched = []

    async def resolve_service(operation_id):
        return persisted[operation_id]

    async def dispatch_operation(*, service_id, operation_id):
        dispatched.append((service_id, operation_id))

    monkeypatch.setattr(
        composition.boundary.repository,
        "resolve_operation_service_id",
        resolve_service,
    )
    monkeypatch.setattr(
        composition.boundary.dispatcher,
        "dispatch_operation",
        dispatch_operation,
    )

    await composition.queue.enqueue_scoped_notification_operation(
        service_id="service-a", operation_id=operation_a, request_id="a"
    )
    await composition.queue.enqueue_scoped_notification_operation(
        service_id="service-b", operation_id=operation_b, request_id="b"
    )
    assert dispatched == [
        ("service-a", operation_a),
        ("service-b", operation_b),
    ]

    with pytest.raises(RuntimeError, match="does not match persistence"):
        await composition.queue.enqueue_scoped_notification_operation(
            service_id="service-b", operation_id=operation_a, request_id="cross"
        )

    with pytest.raises(OrganizationServiceScopeNotConfiguredError):
        await composition.queue.enqueue_scoped_notification_operation(
            service_id="unknown-service",
            operation_id=operation_unknown,
            request_id="unknown",
        )
