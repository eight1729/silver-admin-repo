from types import SimpleNamespace
from dataclasses import replace

import httpx
import pytest
from pydantic import SecretStr

from app.adapter.admin_scope import ConfiguredOrganizationServiceScopeResolver
from app.adapter.line_internal_api import HttpLineInternalApiClient
from app.api.admin_entry_deps import get_admin_line_send_mode_for_runtime
from app.application.admin_send_capability import AdminSendCapabilityGuard
from app.application.notification_service import (
    NotificationService, CreateNotificationOperationCommand, NotificationTargetInput,
    ReplaceNotificationTargetsCommand, SendNotificationOperationCommand, OperationNotSendableError,
)
from app.contracts.admin_line_internal_v1 import SendCapabilityResponse
from app.domain.enums.notification_type import NotificationType
from app.adapter.local_inline_notification_queue import LocalInlineNotificationQueue
from app.testing.local_integration import _build_external_business_fake
from test_admin_state_recovery import db, seed, NOW


def capability(mode="production_live", ready=True, limit=None):
    return SendCapabilityResponse(mode=mode, live_send_enabled=mode != "disabled",
        ready=ready, max_recipients=limit,
        message_prefix="【検証】" if mode == "staging_live" else None,
        blocking_reasons=() if ready else ("live_send_disabled",))


class Client:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    async def check_send_capability(self, request):
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def composition(client):
    return SimpleNamespace(boundary=SimpleNamespace(client=client),
        scope_resolver=ConfiguredOrganizationServiceScopeResolver({"svc": "org-fake-silver-001"}))


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,ready,limit", [
    ("disabled", False, None), ("staging_live", True, 1), ("staging_live", False, 1),
    ("production_live", True, None), ("production_live", False, None),
])
async def test_metadata_uses_line_capability_not_admin_environment(mode, ready, limit):
    expected = capability(mode, ready, limit)
    result = await get_admin_line_send_mode_for_runtime(
        SimpleNamespace(app_env="production", admin_local_integration_mode=False),
        integration=composition(Client(expected)), service_id="svc")
    assert result == expected.model_dump()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["timeout", "network", "auth", "server", "malformed"])
async def test_transport_and_schema_failures_block_metadata_and_send(outcome):
    def handler(request):
        assert request.headers["authorization"] == "Bearer offline-secret"
        assert request.url.path == "/internal/v1/send-capability:check"
        if outcome == "timeout": raise httpx.ReadTimeout("private-url-secret")
        if outcome == "network": raise httpx.ConnectError("private-url-secret")
        if outcome == "auth": return httpx.Response(401, text="private-url-secret")
        if outcome == "server": return httpx.Response(503, text="private-url-secret")
        return httpx.Response(200, json={"ready": True, "mode": "fake", "blocking_reasons": ["private-url-secret"]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = HttpLineInternalApiClient(client=http, base_url="https://line.test", bearer_token=SecretStr("offline-secret"), environment="production")
        comp = composition(client)
        result = await get_admin_line_send_mode_for_runtime(SimpleNamespace(), integration=comp, service_id="svc")
        assert result["mode"] == "unavailable" and result["ready"] is False
        assert "private-url-secret" not in str(result)
        with pytest.raises(OperationNotSendableError, match="^line_capability_unavailable$"):
            await AdminSendCapabilityGuard(client=client, scope_resolver=comp.scope_resolver)("svc", 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("value,members,allowed,pending", [
    (capability("staging_live", True, 1), ("M001", "M002"), False, 0),
    (capability("staging_live", True, 1), ("M001", "M005"), True, 1),
    (capability("production_live"), ("M001", "M002"), True, 2),
    (capability("production_live", False), ("M001",), False, 0),
    (capability("staging_live", False, 1), ("M001",), False, 0),
    (capability("disabled", False), ("M001",), False, 0),
    (RuntimeError("private"), ("M001",), False, 0),
])
async def test_guard_before_atomic_reservation_counts_only_sendable(db, value, members, allowed, pending):
    repo, _, _, _ = await seed(db, reserved=False)
    external = _build_external_business_fake()
    client = Client(value)
    comp = composition(client)
    guard = AdminSendCapabilityGuard(client=client, scope_resolver=comp.scope_resolver)
    async def checked_guard(service_id, count):
        # Guard observes send-time validation, before any durable delivery/outbox.
        assert any(call.method == "validate_notification_targets" for call in external.calls)
        assert await repo.get_deliveries("svc", op.operation_id) == ()
        assert await repo.get_outbox_records("svc", op.operation_id) == ()
        await guard(service_id, count)
    service = NotificationService(repository=repo, external_business_gateway=external,
        queue_gateway=LocalInlineNotificationQueue(), clock=lambda: NOW,
        organization_id_resolver=lambda _: "org-fake-silver-001", persist_line_subjects=False,
        reservation_guard=checked_guard)
    op = await service.create_operation(CreateNotificationOperationCommand(
        service_id="svc", job_id="JOB-001", job_version="v1", notification_type=NotificationType.NEW_JOB_MATCH,
        greeting="hello", introduction="job", note="note", created_by_staff_id="staff"))
    await service.replace_targets(ReplaceNotificationTargetsCommand("svc", op.operation_id,
        tuple(NotificationTargetInput(member, True, member != "M005", None, None) for member in members)))
    command = SendNotificationOperationCommand("svc", op.operation_id, "staff", "request")
    if allowed:
        await service.send_operation(command)
        assert len(await repo.get_outbox_records("svc", op.operation_id)) == pending
        before = await repo.get_deliveries("svc", op.operation_id)
        await service.send_operation(command)
        assert await repo.get_deliveries("svc", op.operation_id) == before
        assert client.calls == 1
    else:
        with pytest.raises(OperationNotSendableError): await service.send_operation(command)
        assert await repo.get_deliveries("svc", op.operation_id) == ()
        assert await repo.get_outbox_records("svc", op.operation_id) == ()
        assert (await repo.get_operation("svc", op.operation_id)).send_requested_at is None


@pytest.mark.asyncio
async def test_edit_during_capability_call_cannot_reserve_stale_operation(db):
    from app.domain.errors.admin_notification_repository import ReservedNotificationMutationError
    repo, _, _, _ = await seed(db, reserved=False)
    class EditingClient(Client):
        async def check_send_capability(self, request):
            current = await repo.get_operation("svc", op.operation_id)
            await repo.update_operation("svc", op.operation_id, replace(current, message_hash="concurrent-edit"))
            return capability()
    client = EditingClient(None)
    service = NotificationService(repository=repo, external_business_gateway=_build_external_business_fake(),
        queue_gateway=LocalInlineNotificationQueue(), clock=lambda: NOW,
        organization_id_resolver=lambda _: "org-fake-silver-001", persist_line_subjects=False,
        reservation_guard=AdminSendCapabilityGuard(client=client, scope_resolver=composition(client).scope_resolver))
    op = await service.create_operation(CreateNotificationOperationCommand(
        service_id="svc", job_id="JOB-001", job_version="v1", notification_type=NotificationType.NEW_JOB_MATCH,
        greeting="hello", introduction="job", note="note", created_by_staff_id="staff"))
    await service.replace_targets(ReplaceNotificationTargetsCommand("svc", op.operation_id,
        (NotificationTargetInput("M001", True, True, None, None),)))
    with pytest.raises(ReservedNotificationMutationError):
        await service.send_operation(SendNotificationOperationCommand("svc", op.operation_id, "staff", "request"))
    assert await repo.get_deliveries("svc", op.operation_id) == ()
    assert await repo.get_outbox_records("svc", op.operation_id) == ()


@pytest.mark.asyncio
async def test_standard_runtime_route_uses_owned_composition(monkeypatch):
    from fastapi import FastAPI
    from app.api.routes.admin import router
    from app.api.admin_auth import require_admin_viewer
    client = Client(capability())
    app = FastAPI()
    app.include_router(router)
    app.state.admin_runtime_settings = SimpleNamespace(app_env="production", admin_local_integration_mode=False)
    app.state.admin_runtime_composition = composition(client)
    app.dependency_overrides[require_admin_viewer] = lambda: SimpleNamespace(service_id="svc")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://admin.test") as http:
        response = await http.get("/admin/line-send-mode")
    assert response.status_code == 200
    assert response.json()["mode"] == "production_live"
    assert client.calls == 1


def test_consumer_schema_matches_checked_in_capability_contract():
    import json
    from pathlib import Path
    from fastapi import FastAPI
    artifact = json.loads((Path(__file__).parents[1] / "contracts/line-internal-api-v1.openapi.json").read_text(encoding="utf-8"))
    app = FastAPI()
    @app.get("/capability", response_model=SendCapabilityResponse)
    def response(): pass
    assert artifact["components"]["schemas"]["SendCapabilityResponse"] == app.openapi()["components"]["schemas"]["SendCapabilityResponse"]
