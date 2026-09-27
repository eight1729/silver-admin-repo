"""Offline log allowlist and unchanged notification outcomes."""
import logging
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.adapter.line_internal_api import HttpLineInternalApiClient, LineNotificationResultNotFoundError
from app.application.admin_line_dispatch import AdminLineOutboxDispatcher, AdminLineResultReconciler
from app.application.notification_service import (
    NotificationService, CreateNotificationOperationCommand, NotificationTargetInput,
    ReplaceNotificationTargetsCommand, SendNotificationOperationCommand, OperationNotSendableError,
)
from app.application.admin_send_capability import AdminSendCapabilityGuard
from app.adapter.local_inline_notification_queue import LocalInlineNotificationQueue
from app.domain.enums.notification_type import NotificationType
from app.domain.enums.enums import DeliveryStatus
from app.domain.models.admin_notification import NotificationMessage, NotificationOutboxState
from app.testing.local_integration import _build_external_business_fake
from test_admin_line_dispatch import _outbox, Repo
from test_admin_line_internal_client import _result
from test_admin_state_recovery import db, seed, dispatch, NOW
from test_admin_send_capability import capability, Client, composition

PRIVATE = "Authorization Bearer access-token-secret line-subject-secret external_member_id private-member-name private-email private-phone private-body private-url idempotency-secret"


def records(caplog):
    # httpx's own request diagnostics are not application observability records.
    return [r for r in caplog.records if r.name.startswith("app.")]


def assert_safe(caplog):
    for record in records(caplog):
        text = record.getMessage() + repr(record.args)
        assert not any(value in text for value in PRIVATE.split())
        assert record.exc_info is None and record.stack_info is None


def line_client(http):
    return HttpLineInternalApiClient(client=http, base_url="https://line.invalid", bearer_token=SecretStr("access-token-secret"), environment="production")


def responder(item, outcome, success_code):
    def respond(request):
        if outcome == "timeout": raise httpx.ReadTimeout(PRIVATE, request=request)
        if outcome == "connection": raise httpx.ConnectError(PRIVATE, request=request)
        if isinstance(outcome, int): return httpx.Response(outcome, text=PRIVATE)
        if outcome == "contract": return httpx.Response(success_code, json={"private": PRIVATE})
        body = _result(item, outcome if outcome in {"pending", "sent", "failed"} else "accepted")
        if outcome == "identity": body["target_id"] = str(uuid4())
        return httpx.Response(success_code, json=body)
    return respond


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,category,state", [
    ("accepted", None, NotificationOutboxState.ACCEPTED),
    ("timeout", "dispatch_timeout", NotificationOutboxState.RETRYABLE_FAILURE),
    ("connection", "dispatch_connection", NotificationOutboxState.RETRYABLE_FAILURE),
    (503, "dispatch_http", NotificationOutboxState.RETRYABLE_FAILURE),
    (401, "dispatch_http", NotificationOutboxState.PERMANENT_FAILURE),
    ("contract", "dispatch_contract", NotificationOutboxState.RETRYABLE_FAILURE),
    ("identity", "response_identity_mismatch", NotificationOutboxState.RETRYABLE_FAILURE),
])
async def test_dispatch_safe_classification(caplog, outcome, category, state):
    caplog.set_level(logging.INFO)
    item = replace(_outbox(), external_member_id="external_member_id", business_message=NotificationMessage(PRIVATE, PRIVATE, PRIVATE), idempotency_key="idempotency-secret")
    repo = Repo(item)
    async with httpx.AsyncClient(transport=httpx.MockTransport(responder(item, outcome, 202))) as http:
        await AdminLineOutboxDispatcher(repository=repo, line_client=line_client(http)).dispatch_operation(service_id="svc", operation_id=item.operation_id)
    assert repo.item.state is state
    log, = records(caplog)
    message = log.getMessage()
    for value in (item.command_id, item.operation_id, item.target_id): assert str(value) in message
    assert "stage=dispatch" in message
    assert ("event=accepted" if category is None else f"reason_category={category}") in message
    if isinstance(outcome, int): assert f"http_status={outcome}" in message
    assert_safe(caplog)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,category,status", [
    ("pending", None, DeliveryStatus.PENDING), ("sent", None, DeliveryStatus.SENT),
    ("failed", None, DeliveryStatus.FAILED), (404, "result_poll_not_found", DeliveryStatus.FAILED),
    ("timeout", "result_poll_timeout", DeliveryStatus.PENDING),
    ("connection", "result_poll_connection", DeliveryStatus.PENDING),
    (503, "result_poll_http", DeliveryStatus.PENDING),
    ("contract", "result_poll_contract", DeliveryStatus.PENDING),
    ("identity", "response_identity_mismatch", DeliveryStatus.PENDING),
])
async def test_poll_and_committed_terminal_logs(db, caplog, outcome, category, status):
    caplog.set_level(logging.INFO)
    repo, _, op, items = await seed(db)
    await dispatch(repo, op, [None])
    caplog.clear()
    async with httpx.AsyncClient(transport=httpx.MockTransport(responder(items[0], outcome, 200))) as http:
        reconciler = AdminLineResultReconciler(repository=repo, line_client=line_client(http))
        await reconciler.reconcile_operation(service_id="svc", operation_id=op.operation_id)
        delivery, = await repo.get_deliveries("svc", op.operation_id)
        assert delivery.status is status
        if outcome == "sent": assert delivery.sent_at == NOW
        logs = records(caplog)
        if outcome == "pending": assert logs == []
        for log in logs:
            for value in (items[0].command_id, op.operation_id, items[0].target_id): assert str(value) in log.getMessage()
        if category: assert any(f"reason_category={category}" in log.getMessage() for log in logs)
        assert_safe(caplog)
        if status is not DeliveryStatus.PENDING:
            terminal = [log for log in logs if "stage=reconcile" in log.getMessage()]
            assert len(terminal) == 1 and f"status={status.value}" in terminal[0].getMessage()
            caplog.clear()
            await reconciler.reconcile_operation(service_id="svc", operation_id=op.operation_id)
            assert records(caplog) == []
    assert_safe(caplog)


@pytest.mark.asyncio
@pytest.mark.parametrize("value,members,reason,mode", [
    (capability("production_live", False), ("M001",), "line_send_not_ready", "production_live"),
    (capability("staging_live", True, 1), ("M001", "M002"), "line_recipient_limit_exceeded", "staging_live"),
    (RuntimeError(PRIVATE), ("M001",), "line_capability_unavailable", "unavailable"),
])
async def test_capability_rejection_is_correlated_without_changing_reservation(db, caplog, value, members, reason, mode):
    caplog.set_level(logging.INFO)
    repo, _, _, _ = await seed(db, reserved=False)
    client = Client(value)
    service = NotificationService(repository=repo, external_business_gateway=_build_external_business_fake(),
        queue_gateway=LocalInlineNotificationQueue(), clock=lambda: NOW,
        organization_id_resolver=lambda _: "org-fake-silver-001", persist_line_subjects=False,
        reservation_guard=AdminSendCapabilityGuard(client=client, scope_resolver=composition(client).scope_resolver))
    op = await service.create_operation(CreateNotificationOperationCommand(service_id="svc", job_id="JOB-001", job_version="v1",
        notification_type=NotificationType.NEW_JOB_MATCH, greeting=PRIVATE, introduction=PRIVATE, note=PRIVATE, created_by_staff_id="staff"))
    await service.replace_targets(ReplaceNotificationTargetsCommand("svc", op.operation_id,
        tuple(NotificationTargetInput(member, True, True, None, None) for member in members)))
    with pytest.raises(OperationNotSendableError, match=reason):
        await service.send_operation(SendNotificationOperationCommand("svc", op.operation_id, "staff", "request"))
    assert await repo.get_deliveries("svc", op.operation_id) == ()
    assert await repo.get_outbox_records("svc", op.operation_id) == ()
    log, = records(caplog)
    for text in ("stage=capability", "event=rejected", str(op.operation_id), f"reason_category={reason}", f"capability_mode={mode}"):
        assert text in log.getMessage()
    assert all(member not in log.getMessage() for member in members)
    assert_safe(caplog)


@pytest.mark.asyncio
async def test_concurrent_terminal_winner_is_only_committed_terminal_log(db, caplog):
    caplog.set_level(logging.INFO)
    repo, _, op, items = await seed(db)
    await dispatch(repo, op, [None])
    original, = await repo.get_deliveries("svc", op.operation_id)
    sent = replace(original, status=DeliveryStatus.SENT, sent_at=NOW)
    class Results:
        async def get_notification_result(self, command_id):
            await repo.reconcile_outbox_result("svc", op.operation_id, items[0].outbox_id, sent)
            raise LineNotificationResultNotFoundError(PRIVATE)
    caplog.clear()
    await AdminLineResultReconciler(repository=repo, line_client=Results()).reconcile_operation(service_id="svc", operation_id=op.operation_id)
    terminal = [log for log in records(caplog) if "stage=reconcile" in log.getMessage()]
    assert len(terminal) == 1 and "status=sent" in terminal[0].getMessage()
    assert (await repo.get_deliveries("svc", op.operation_id))[0] == sent
    assert_safe(caplog)
