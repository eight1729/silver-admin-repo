"""Admin timestamp boundary checks without network or real DB access."""
from datetime import timedelta

import httpx
import pytest
from pydantic import SecretStr

from app.adapter.line_internal_api import HttpLineInternalApiClient, LineInternalApiRetryableError
from app.application.admin_line_dispatch import AdminLineResultReconciler
from app.domain.enums.enums import DeliveryStatus
from app.domain.models.admin_notification import NotificationOutboxState
from test_admin_state_recovery import db, seed, dispatch
from test_admin_line_dispatch import NOW, _result
from test_admin_line_internal_client import _command, _result as wire_result


@pytest.mark.asyncio
async def test_sent_uses_provider_time_not_result_update_and_terminal_is_immutable(db):
    repo, now, op, items = await seed(db)
    await dispatch(repo, op, [None])
    t1, t2, t3 = NOW + timedelta(seconds=10), NOW + timedelta(seconds=12), NOW + timedelta(seconds=20)
    now[0] = t3
    item = items[0]
    payload = dict(command_id=str(item.command_id), operation_id=str(item.operation_id),
        target_id=str(item.target_id), external_member_id=item.external_member_id,
        status="sent", accepted_at=NOW.isoformat(), sent_at=t1.isoformat(), updated_at=t2.isoformat())
    calls = []
    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, json=payload)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = HttpLineInternalApiClient(client=http, base_url="https://line.invalid",
            bearer_token=SecretStr("offline"), environment="production")
        reconciler = AdminLineResultReconciler(repository=repo, line_client=client)
        await reconciler.reconcile_operation(service_id="svc", operation_id=op.operation_id)
        delivery, = await repo.get_deliveries("svc", op.operation_id)
        assert delivery.status is DeliveryStatus.SENT and delivery.sent_at == t1
        assert delivery.updated_at == t3
        now[0] += timedelta(days=1)
        payload["sent_at"] = now[0].isoformat()
        for _ in range(3):
            await reconciler.reconcile_operation(service_id="svc", operation_id=op.operation_id)
        assert await repo.get_deliveries("svc", op.operation_id) == (delivery,)
        assert calls == ["GET"]


@pytest.mark.asyncio
@pytest.mark.parametrize("sent_at", [None, "missing", "2026-01-01T00:00:00", "invalid"])
async def test_invalid_sent_timestamp_fails_closed_without_updated_at_fallback(db, sent_at):
    repo, now, op, items = await seed(db)
    await dispatch(repo, op, [None])
    item = items[0]
    before = await repo.get_deliveries("svc", op.operation_id)
    payload = dict(command_id=str(item.command_id), operation_id=str(item.operation_id),
        target_id=str(item.target_id), external_member_id=item.external_member_id,
        status="sent", updated_at=NOW.isoformat())
    if sent_at != "missing": payload["sent_at"] = sent_at
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as http:
        client = HttpLineInternalApiClient(client=http, base_url="https://line.invalid",
            bearer_token=SecretStr("offline"), environment="production")
        with pytest.raises(LineInternalApiRetryableError):
            await client.get_notification_result(item.command_id)
        reconciler = AdminLineResultReconciler(repository=repo, line_client=client)
        await reconciler.reconcile_operation(service_id="svc", operation_id=op.operation_id)
    assert await repo.get_deliveries("svc", op.operation_id) == before
    assert before[0].sent_at is None
    assert (await repo.get_outbox_records("svc", op.operation_id))[0].state is NotificationOutboxState.ACCEPTED


@pytest.mark.asyncio
async def test_reconciler_also_rejects_invalid_sent_from_non_http_client(db):
    repo, now, op, items = await seed(db)
    await dispatch(repo, op, [None])
    class Results:
        async def get_notification_result(self, command_id):
            return _result(items[0], status="sent", sent_at=None, updated_at=NOW)
    await AdminLineResultReconciler(repository=repo, line_client=Results()).reconcile_operation(
        service_id="svc", operation_id=op.operation_id)
    delivery, = await repo.get_deliveries("svc", op.operation_id)
    assert delivery.status is DeliveryStatus.PENDING and delivery.sent_at is None


@pytest.mark.parametrize("status", ["failed", "recipient_not_linked", "unknown", "rejected", "accepted", "pending"])
def test_non_sent_projection_never_creates_sent_at(status):
    from test_admin_line_dispatch import Repo, _outbox
    item = _outbox()
    delivery = Repo(item).delivery
    result = _result(item, status=status, sent_at=None, updated_at=NOW + timedelta(hours=1), reason_code=None)
    assert AdminLineResultReconciler._project(delivery, result).sent_at is None


@pytest.mark.asyncio
async def test_post_sent_without_timestamp_is_invalid_not_accepted():
    command = _command()
    payload = wire_result(command, status="sent")
    payload["sent_at"] = None
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(202, json=payload))) as http:
        client = HttpLineInternalApiClient(client=http, base_url="https://line.invalid",
            bearer_token=SecretStr("offline"), environment="production")
        with pytest.raises(LineInternalApiRetryableError):
            await client.submit_notification_command(command)
