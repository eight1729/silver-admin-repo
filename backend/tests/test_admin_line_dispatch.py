import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.adapter.line_internal_api import (
    LineInternalApiPermanentError,
    LineInternalApiRetryableError,
)
from app.application.admin_line_dispatch import AdminLineOutboxDispatcher, AdminLineResultReconciler
from app.domain.enums.enums import DeliveryStatus, OperationStatus
from app.domain.models.admin_notification import (
    NotificationDeliveryRecord, NotificationMessage, NotificationOutboxRecord,
    NotificationOutboxState,
)
from app.contracts.admin_line_internal_v1 import NotificationCommandStatus


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _outbox():
    return NotificationOutboxRecord(
        outbox_id=uuid4(), command_id=uuid4(), operation_id=uuid4(), target_id=uuid4(),
        organization_id="org", service_id="svc", external_member_id="member",
        job_id="job", job_version="v1",
        business_message=NotificationMessage("hello", "intro", "note"),
        message_version=3, message_hash="a" * 64, idempotency_key="idem",
        correlation_id="corr", requested_at=NOW, created_at=NOW,
    )


class Repo:
    def __init__(self, item):
        self.item = item
        self.lock = asyncio.Lock()
        self.delivery = NotificationDeliveryRecord(
            delivery_id=uuid4(), operation_id=item.operation_id, member_id="member",
            status=DeliveryStatus.PENDING, request_id="corr", line_request_id=None,
            error_code=None, error_message=None, created_at=NOW, updated_at=NOW,
        )
        self.operation = FakeOperation(status=OperationStatus.READY)
    async def claim_outbox_records(self, service_id, operation_id):
        async with self.lock:
            if self.item.state not in (NotificationOutboxState.PENDING, NotificationOutboxState.RETRYABLE_FAILURE): return ()
            self.item = replace(self.item, state=NotificationOutboxState.DELIVERING)
            return (self.item,)
    async def update_outbox_state(self, service_id, operation_id, outbox_id, state, *, claim_token=None):
        self.item = replace(self.item, state=state); return self.item
    async def get_outbox_records(self, service_id, operation_id): return (self.item,)
    async def get_deliveries(self, service_id, operation_id): return (self.delivery,)
    async def update_delivery(self, service_id, operation_id, delivery_id, delivery): self.delivery = delivery; return delivery
    async def get_operation(self, service_id, operation_id): return self.operation
    async def update_operation(self, service_id, operation_id, operation): self.operation = operation; return operation
    async def reconcile_outbox_result(self, service_id, operation_id, outbox_id, delivery):
        self.delivery = delivery
        self.item = replace(self.item, state=NotificationOutboxState.RECONCILED)
    async def refresh_delivery_aggregate(self, service_id, operation_id): return self.operation


class Client:
    def __init__(self, outcomes): self.outcomes=list(outcomes); self.commands=[]; self.submit_calls=0
    async def submit_notification_command(self, command):
        self.submit_calls += 1; self.commands.append(command)
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(outcome, Exception): raise outcome
        return outcome
    async def get_notification_result(self, command_id): return self.outcomes[0]


@dataclass(frozen=True)
class FakeOperation:
    status: OperationStatus


@pytest.mark.asyncio
async def test_dispatch_uses_exact_outbox_command_and_marks_accepted():
    item=_outbox(); repo=Repo(item); client=Client([SimpleNamespace()])
    await AdminLineOutboxDispatcher(repository=repo, line_client=client).dispatch_operation(service_id="svc", operation_id=item.operation_id)
    sent=client.commands[0]
    assert repo.item.state is NotificationOutboxState.ACCEPTED
    assert sent.command_id == item.command_id and sent.idempotency_key == item.idempotency_key
    assert sent.message_hash == item.message_hash and sent.external_member_id == "member"
    assert "line_subject" not in sent.model_dump()


@pytest.mark.asyncio
async def test_post_timeout_remains_retryable_and_replays_same_command():
    item=_outbox(); repo=Repo(item); client=Client([LineInternalApiRetryableError("timeout"), SimpleNamespace()])
    dispatcher=AdminLineOutboxDispatcher(repository=repo, line_client=client)
    await dispatcher.dispatch_operation(service_id="svc", operation_id=item.operation_id)
    assert repo.item.state is NotificationOutboxState.RETRYABLE_FAILURE
    await dispatcher.dispatch_operation(service_id="svc", operation_id=item.operation_id)
    assert repo.item.state is NotificationOutboxState.ACCEPTED
    assert client.commands[0] == client.commands[1]


@pytest.mark.asyncio
async def test_contract_conflict_is_permanent_and_not_reclaimed():
    item=_outbox(); repo=Repo(item); client=Client([LineInternalApiPermanentError("conflict")])
    dispatcher=AdminLineOutboxDispatcher(repository=repo, line_client=client)
    await dispatcher.dispatch_operation(service_id="svc", operation_id=item.operation_id)
    await dispatcher.dispatch_operation(service_id="svc", operation_id=item.operation_id)
    assert repo.item.state is NotificationOutboxState.PERMANENT_FAILURE
    assert client.submit_calls == 1


@pytest.mark.asyncio
async def test_concurrent_dispatch_claims_once():
    item=_outbox(); repo=Repo(item); client=Client([SimpleNamespace()])
    dispatcher=AdminLineOutboxDispatcher(repository=repo, line_client=client)
    await asyncio.gather(
        dispatcher.dispatch_operation(service_id="svc", operation_id=item.operation_id),
        dispatcher.dispatch_operation(service_id="svc", operation_id=item.operation_id),
    )
    assert client.submit_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "contract_status,business_status", [
        ("accepted", DeliveryStatus.PENDING), ("pending", DeliveryStatus.PENDING),
        ("sent", DeliveryStatus.SENT), ("failed", DeliveryStatus.FAILED),
        ("recipient_not_linked", DeliveryStatus.SKIPPED),
        ("unknown", DeliveryStatus.UNKNOWN),
    ]
)
async def test_reconciliation_projects_contract_status_idempotently(contract_status, business_status):
    item=replace(_outbox(), state=NotificationOutboxState.ACCEPTED); repo=Repo(item)
    result=SimpleNamespace(status=NotificationCommandStatus(contract_status), reason_code="reason", updated_at=NOW)
    client=Client([result]); reconciler=AdminLineResultReconciler(repository=repo, line_client=client)
    await reconciler.reconcile_operation(service_id="svc", operation_id=item.operation_id)
    await reconciler.reconcile_operation(service_id="svc", operation_id=item.operation_id)
    assert repo.delivery.status is business_status
    assert repo.delivery.line_request_id is None
    assert client.submit_calls == 0


@pytest.mark.asyncio
async def test_provider_unknown_never_resubmits_command():
    item=replace(_outbox(), state=NotificationOutboxState.ACCEPTED); repo=Repo(item)
    result=SimpleNamespace(status=NotificationCommandStatus.UNKNOWN, reason_code="unknown_result", updated_at=NOW)
    client=Client([result]); reconciler=AdminLineResultReconciler(repository=repo, line_client=client)
    await reconciler.reconcile_operation(service_id="svc", operation_id=item.operation_id)
    assert repo.delivery.status is DeliveryStatus.UNKNOWN
    assert repo.item.state is NotificationOutboxState.RECONCILED
    assert client.submit_calls == 0
