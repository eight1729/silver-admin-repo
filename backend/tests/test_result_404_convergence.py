"""Offline Result 404 convergence: MockTransport and in-memory SQLite only."""
from dataclasses import replace
from datetime import timedelta

import httpx
import pytest
from pydantic import SecretStr

from app.adapter.line_internal_api import (
    HttpLineInternalApiClient, LineInternalApiPermanentError,
    LineInternalApiRetryableError, LineNotificationResultNotFoundError,
)
from app.application.admin_line_dispatch import AdminLineOutboxDispatcher, AdminLineResultReconciler
from app.application.admin_notification_runner import AdminNotificationRunner
from app.domain.enums.enums import DeliveryStatus, OperationStatus
from app.domain.models.admin_notification import NotificationOutboxState
from test_admin_state_recovery import db, seed, dispatch
from test_admin_line_internal_client import _command


def client(http):
    return HttpLineInternalApiClient(client=http, base_url="https://line.invalid",
        bearer_token=SecretStr("offline-test"), environment="production")


@pytest.mark.asyncio
async def test_accepted_404_converges_atomically_and_runner_never_reposts(db):
    repo, now, op, items = await seed(db)
    submitted = await dispatch(repo, op, [None])
    calls = []
    def missing(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(404, text="private upstream response")
    async with httpx.AsyncClient(transport=httpx.MockTransport(missing)) as http:
        line = client(http)
        reconciler = AdminLineResultReconciler(repository=repo, line_client=line)
        runner = AdminNotificationRunner(repository=repo, service_ids=["svc"],
            dispatcher=AdminLineOutboxDispatcher(repository=repo, line_client=line), reconciler=reconciler)
        await runner.run_cycle()
        first = await repo.get_operation("svc", op.operation_id)
        result, = await repo.get_deliveries("svc", op.operation_id)
        outbox, = await repo.get_outbox_records("svc", op.operation_id)
        audits = await repo.get_audit_events("svc", op.operation_id)
        assert result.status is DeliveryStatus.FAILED
        assert result.error_code == "line_result_not_found"
        assert result.error_message is None and result.sent_at is None
        assert outbox.state is NotificationOutboxState.RECONCILED
        assert outbox.command_id == items[0].command_id
        assert outbox.idempotency_key == items[0].idempotency_key
        assert first.status is OperationStatus.COMPLETED_WITH_ERRORS
        assert first.completed_at == now[0]
        assert await repo.list_recovery_operations("svc") == ()
        now[0] += timedelta(days=1)
        await reconciler.reconcile_operation(service_id="svc", operation_id=op.operation_id)
        await runner.run_cycle()
        await runner.run_cycle()
        assert await repo.get_operation("svc", op.operation_id) == first
        assert await repo.get_deliveries("svc", op.operation_id) == (result,)
        assert await repo.get_audit_events("svc", op.operation_id) == audits
        assert calls == [("GET", f"/internal/v1/notification-commands/{items[0].command_id}")]
        assert submitted.submit_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("other_status", [DeliveryStatus.SENT, DeliveryStatus.PENDING])
async def test_404_updates_only_its_target_and_preserves_mixed_aggregation(db, other_status):
    repo, now, op, items = await seed(db, count=2)
    await dispatch(repo, op, [None]); await dispatch(repo, op, [None])
    missing_item, other = await repo.get_outbox_records("svc", op.operation_id)
    other_delivery = next(d for d in await repo.get_deliveries("svc", op.operation_id)
                          if d.member_id == other.external_member_id)
    if other_status is DeliveryStatus.SENT:
        other_delivery = replace(other_delivery, status=other_status, sent_at=now[0])
        await repo.reconcile_outbox_result("svc", op.operation_id, other.outbox_id, other_delivery)
    class Results:
        async def get_notification_result(self, command_id):
            if command_id == missing_item.command_id:
                raise LineNotificationResultNotFoundError("not found")
            raise LineInternalApiRetryableError("temporary lookup failure")
    reconciler = AdminLineResultReconciler(repository=repo, line_client=Results())
    result = await reconciler.reconcile_operation(service_id="svc", operation_id=op.operation_id)
    stored = {d.member_id: d for d in await repo.get_deliveries("svc", op.operation_id)}
    assert stored[missing_item.external_member_id].status is DeliveryStatus.FAILED
    assert stored[other.external_member_id] == other_delivery
    assert result.status is (OperationStatus.SENDING if other_status is DeliveryStatus.PENDING
                             else OperationStatus.COMPLETED_WITH_ERRORS)
    assert bool(await repo.list_recovery_operations("svc")) is (other_status is DeliveryStatus.PENDING)


@pytest.mark.asyncio
async def test_404_cannot_overwrite_success_from_a_concurrent_reconciler(db):
    repo, now, op, items = await seed(db)
    await dispatch(repo, op, [None])
    original, = await repo.get_deliveries("svc", op.operation_id)
    sent = replace(original, status=DeliveryStatus.SENT, sent_at=now[0])
    class Results:
        async def get_notification_result(self, command_id):
            await repo.reconcile_outbox_result("svc", op.operation_id, items[0].outbox_id, sent)
            raise LineNotificationResultNotFoundError("not found")
    result = await AdminLineResultReconciler(repository=repo, line_client=Results()).reconcile_operation(
        service_id="svc", operation_id=op.operation_id)
    assert (await repo.get_deliveries("svc", op.operation_id))[0] == sent
    assert result.status is OperationStatus.COMPLETED


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,error_type", [
    (401, LineInternalApiPermanentError), (403, LineInternalApiPermanentError),
    (409, LineInternalApiPermanentError), (422, LineInternalApiPermanentError),
    (500, LineInternalApiRetryableError), (502, LineInternalApiRetryableError),
    (503, LineInternalApiRetryableError), ("timeout", LineInternalApiRetryableError),
    ("connection", LineInternalApiRetryableError), ("schema", LineInternalApiRetryableError),
])
async def test_non_404_mapping_and_accepted_state_are_unchanged(db, outcome, error_type):
    repo, now, op, items = await seed(db)
    await dispatch(repo, op, [None])
    before = await repo.get_deliveries("svc", op.operation_id)
    def respond(request):
        if outcome == "timeout": raise httpx.ReadTimeout("offline timeout", request=request)
        if outcome == "connection": raise httpx.ConnectError("offline connection", request=request)
        if outcome == "schema": return httpx.Response(200, json={})
        return httpx.Response(outcome, text="private body")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        line = client(http)
        with pytest.raises(error_type) as caught:
            await line.get_notification_result(items[0].command_id)
        assert not isinstance(caught.value, LineNotificationResultNotFoundError)
        await AdminLineResultReconciler(repository=repo, line_client=line).reconcile_operation(
            service_id="svc", operation_id=op.operation_id)
    assert (await repo.get_outbox_records("svc", op.operation_id))[0].state is NotificationOutboxState.ACCEPTED
    assert await repo.get_deliveries("svc", op.operation_id) == before


@pytest.mark.asyncio
async def test_only_result_get_404_uses_special_permanent_subclass():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(404, text="private body"))) as http:
        line = client(http)
        with pytest.raises(LineInternalApiPermanentError) as post:
            await line.submit_notification_command(_command())
        assert type(post.value) is LineInternalApiPermanentError
        with pytest.raises(LineNotificationResultNotFoundError) as get:
            await line.get_notification_result(_command().command_id)
        assert isinstance(get.value, LineInternalApiPermanentError)
        assert "private body" not in str(get.value)
