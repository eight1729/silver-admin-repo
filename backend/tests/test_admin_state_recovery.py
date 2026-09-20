"""Offline SQL repository crash/recovery tests. PostgreSQL locking is a manual gate."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert, update, inspect, text

from app.application.admin_line_dispatch import AdminLineOutboxDispatcher, AdminLineResultReconciler
from app.application.admin_notification_runner import AdminNotificationRunner
from app.application.notification_service import NotificationService, OperationNotEditableError
from app.db.admin_notification_repository import SqlAlchemyAdminNotificationRepository
from app.db.admin_notification_provisioning import create_admin_notification_tables, migrate_admin_outbox_recovery
from app.db.admin_tables import admin_notification_outbox as outbox_table
from app.domain.models.admin_notification import NotificationOperationRecord, NotificationAuditEvent
from app.domain.enums.notification_type import NotificationType
from app.domain.errors.admin_notification_repository import RepositoryStateError
from test_admin_line_dispatch import NOW, _outbox, Client, Repo, DeliveryStatus, OperationStatus, NotificationOutboxState
from app.adapter.line_internal_api import LineInternalApiPermanentError, LineInternalApiRetryableError


class Database:
    def __init__(self):
        self.engine = create_engine("sqlite://")
        self.connection = self.engine.connect()
        create_admin_notification_tables(self.connection)
        self.connection.commit()
        self.lock = asyncio.Lock()

    @asynccontextmanager
    async def connect(self):
        yield self

    @asynccontextmanager
    async def begin(self):
        async with self.lock:
            with self.connection.begin_nested():
                yield self

    async def execute(self, statement, *args):
        return self.connection.execute(statement, *args)


@pytest.fixture
def db():
    db = Database()
    yield db
    db.connection.close()
    db.engine.dispose()


async def seed(db, count=1, *, reserved=True):
    now = [NOW]
    repo = SqlAlchemyAdminNotificationRepository(db, clock=lambda: now[0])
    item = _outbox()
    operation = NotificationOperationRecord(
        operation_id=item.operation_id, service_id="svc", job_id="job", job_version="v1",
        notification_type=list(NotificationType)[0], message=item.business_message,
        status=OperationStatus.READY, created_by_staff_id="staff", created_at=NOW, updated_at=NOW)
    await repo.create_operation(operation)
    items = tuple(replace(item, outbox_id=uuid4(), command_id=uuid4(), target_id=uuid4(),
                          external_member_id=f"member-{i}", idempotency_key=f"{item.operation_id}-{i}") for i in range(count))
    deliveries = tuple(replace(Repo(item).delivery, delivery_id=uuid4(), member_id=x.external_member_id) for x in items)
    if reserved:
        await repo.begin_send_attempt("svc", item.operation_id, deliveries, items,
            NotificationAuditEvent(uuid4(), item.operation_id, "send_requested", "staff", {}, NOW), send_requested_at=NOW)
    return repo, now, operation, items


async def dispatch(repo, operation, outcomes):
    client = Client(outcomes)
    await AdminLineOutboxDispatcher(repository=repo, line_client=client).dispatch_operation(
        service_id="svc", operation_id=operation.operation_id)
    return client


@pytest.mark.asyncio
async def test_active_stale_legacy_claim_and_fencing(db):
    repo, now, op, items = await seed(db)
    first, = await repo.claim_outbox_records("svc", op.operation_id)
    assert first.state is NotificationOutboxState.DELIVERING
    assert await repo.claim_outbox_records("svc", op.operation_id) == ()
    now[0] += timedelta(seconds=60)
    second, = await repo.claim_outbox_records("svc", op.operation_id)
    assert second.command_id == first.command_id and second.claim_token != first.claim_token
    await repo.update_outbox_state("svc", op.operation_id, first.outbox_id, NotificationOutboxState.PERMANENT_FAILURE,
                                  claim_token=first.claim_token)
    assert (await repo.get_deliveries("svc", op.operation_id))[0].status is DeliveryStatus.PENDING
    assert (await repo.get_outbox_records("svc", op.operation_id))[0].claim_token == second.claim_token
    db.connection.execute(update(outbox_table).values(lease_expires_at=None, claim_token=None))
    client = await dispatch(repo, op, [None])
    assert client.commands[0].command_id == first.command_id
    assert client.commands[0].idempotency_key == first.idempotency_key


@pytest.mark.asyncio
async def test_two_workers_one_active_submission(db):
    repo, now, op, items = await seed(db)
    started, release = asyncio.Event(), asyncio.Event()
    class Blocking(Client):
        async def submit_notification_command(self, command):
            self.commands.append(command)
            started.set()
            await release.wait()
    client = Blocking([])
    worker = AdminLineOutboxDispatcher(repository=repo, line_client=client)
    first = asyncio.create_task(worker.dispatch_operation(service_id="svc", operation_id=op.operation_id))
    await started.wait()
    await worker.dispatch_operation(service_id="svc", operation_id=op.operation_id)
    release.set()
    await first
    assert len(client.commands) == 1


@pytest.mark.asyncio
async def test_submission_failure_consistency(db):
    repo, now, op, items = await seed(db)
    await dispatch(repo, op, [LineInternalApiRetryableError("private body")])
    assert (await repo.get_outbox_records("svc", op.operation_id))[0].state is NotificationOutboxState.RETRYABLE_FAILURE
    assert (await repo.get_deliveries("svc", op.operation_id))[0].status is DeliveryStatus.PENDING
    assert (await repo.get_operation("svc", op.operation_id)).completed_at is None
    await dispatch(repo, op, [LineInternalApiPermanentError("private body")])
    assert (await repo.get_outbox_records("svc", op.operation_id))[0].state is NotificationOutboxState.PERMANENT_FAILURE
    assert (await repo.get_deliveries("svc", op.operation_id))[0].status is DeliveryStatus.FAILED
    completed = await repo.get_operation("svc", op.operation_id)
    assert completed.status is OperationStatus.COMPLETED_WITH_ERRORS and completed.completed_at == NOW
    assert not (await dispatch(repo, op, [])).commands


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [("sent",DeliveryStatus.SENT), ("failed",DeliveryStatus.FAILED),
    ("unknown",DeliveryStatus.UNKNOWN), ("recipient_not_linked",DeliveryStatus.SKIPPED), ("rejected",DeliveryStatus.FAILED),
    ("pending",DeliveryStatus.PENDING), ("accepted",DeliveryStatus.PENDING)])
async def test_terminal_atomic_idempotent_and_no_poll(db, status, expected):
    repo, now, op, items = await seed(db)
    await dispatch(repo, op, [None])
    class Results:
        calls = 0
        async def get_notification_result(self, command_id):
            self.calls += 1
            return SimpleNamespace(status=status, reason_code="reason", updated_at=NOW)
    client = Results()
    reconciler = AdminLineResultReconciler(repository=repo, line_client=client)
    await reconciler.reconcile_operation(service_id="svc", operation_id=op.operation_id)
    first = await repo.get_operation("svc", op.operation_id)
    audits = await repo.get_audit_events("svc", op.operation_id)
    now[0] += timedelta(days=1)
    await reconciler.reconcile_operation(service_id="svc", operation_id=op.operation_id)
    assert (await repo.get_deliveries("svc", op.operation_id))[0].status is expected
    second = await repo.get_operation("svc", op.operation_id)
    assert first == second
    assert await repo.get_audit_events("svc", op.operation_id) == audits
    terminal = expected is not DeliveryStatus.PENDING
    assert client.calls == (1 if terminal else 2)
    assert second.completed_at == (NOW if terminal else None)
    assert (await repo.get_outbox_records("svc", op.operation_id))[0].state is (
        NotificationOutboxState.RECONCILED if terminal else NotificationOutboxState.ACCEPTED)
    assert second.status is (OperationStatus.SENDING if not terminal else
                            OperationStatus.COMPLETED if status == "sent" else OperationStatus.COMPLETED_WITH_ERRORS)


@pytest.mark.asyncio
async def test_mixed_and_empty_aggregate(db):
    repo, now, op, items = await seed(db, count=2)
    await dispatch(repo, op, [LineInternalApiPermanentError("bad")])
    assert (await repo.get_operation("svc", op.operation_id)).status is OperationStatus.SENDING
    await dispatch(repo, op, [None])
    reconciler = AdminLineResultReconciler(repository=repo, line_client=Client([
        SimpleNamespace(status="sent", reason_code=None, updated_at=NOW)]))
    result = await reconciler.reconcile_operation(service_id="svc", operation_id=op.operation_id)
    assert result.status is OperationStatus.COMPLETED_WITH_ERRORS
    repo, now, op, items = await seed(db, count=0, reserved=False)
    assert (await repo.refresh_delivery_aggregate("svc", op.operation_id)).status is OperationStatus.READY


@pytest.mark.asyncio
async def test_snapshot_freeze_in_repository_and_service(db):
    repo, now, op, items = await seed(db, reserved=False)
    changed = replace(op, message=replace(op.message, note="edited"))
    await repo.update_operation("svc", op.operation_id, changed)
    NotificationService._ensure_editable(changed)
    repo, now, op, items = await seed(db)
    reserved = await repo.get_operation("svc", op.operation_id)
    with pytest.raises(OperationNotEditableError):
        NotificationService._ensure_editable(reserved)
    with pytest.raises(RepositoryStateError):
        await repo.update_operation("svc", op.operation_id, replace(reserved, message_hash="changed"))
    # Stale editor read before reservation must not remove send_requested_at.
    with pytest.raises(RepositoryStateError):
        await repo.update_operation("svc", op.operation_id, op)
    with pytest.raises(RepositoryStateError):
        await repo.replace_targets("svc", op.operation_id, [])
    event = NotificationAuditEvent(uuid4(), op.operation_id, "edit", "staff", {}, NOW)
    with pytest.raises(RepositoryStateError):
        await repo.replace_targets_with_operation_and_audit("svc", op.operation_id, [], reserved, event)
    client = await dispatch(repo, op, [None])
    assert client.commands[0].business_message.note == items[0].business_message.note


@pytest.mark.asyncio
async def test_runner_recovers_crash_and_completes_without_frontend(db):
    repo, now, op, items = await seed(db)
    await repo.claim_outbox_records("svc", op.operation_id)
    now[0] += timedelta(seconds=61)
    client = Client([None, SimpleNamespace(status="sent", reason_code=None, updated_at=NOW)])
    runner = AdminNotificationRunner(repository=repo, service_ids=["svc"],
        dispatcher=AdminLineOutboxDispatcher(repository=repo, line_client=client),
        reconciler=AdminLineResultReconciler(repository=repo, line_client=client), interval_seconds=0.01)
    await runner.start()
    task = runner._task
    await runner.start()
    assert runner._task is task
    for _ in range(100):
        if (await repo.get_operation("svc", op.operation_id)).completed_at:
            break
        await asyncio.sleep(.01)
    await runner.stop()
    assert task.done() and runner._task is None
    assert (await repo.get_operation("svc", op.operation_id)).status is OperationStatus.COMPLETED
    assert client.commands[0].command_id == items[0].command_id
    assert await repo.list_recovery_operations("svc") == ()


def test_legacy_migration_is_additive_and_repeatable():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE admin_notification_outbox (command_id TEXT, state TEXT)"))
        conn.execute(text("INSERT INTO admin_notification_outbox VALUES ('unchanged', 'delivering')"))
        migrate_admin_outbox_recovery(conn)
        migrate_admin_outbox_recovery(conn)
        assert {c["name"] for c in inspect(conn).get_columns("admin_notification_outbox")} == {
            "command_id", "state", "lease_expires_at", "claim_token"}
        row = conn.execute(text("SELECT * FROM admin_notification_outbox")).mappings().one()
        assert dict(row) == dict(command_id="unchanged", state="delivering", lease_expires_at=None, claim_token=None)
    engine.dispose()


@pytest.mark.asyncio
async def test_terminal_transaction_rollback_and_concurrent_reconcile(db, monkeypatch):
    repo, now, op, items = await seed(db)
    await dispatch(repo, op, [None])
    projected = replace((await repo.get_deliveries("svc", op.operation_id))[0], status=DeliveryStatus.SENT, sent_at=NOW)
    aggregate = repo._aggregate
    async def crash(*args): raise RuntimeError("simulated crash before commit")
    monkeypatch.setattr(repo, "_aggregate", crash)
    with pytest.raises(RuntimeError):
        await repo.reconcile_outbox_result("svc", op.operation_id, items[0].outbox_id, projected)
    assert (await repo.get_outbox_records("svc", op.operation_id))[0].state is NotificationOutboxState.ACCEPTED
    assert (await repo.get_deliveries("svc", op.operation_id))[0].status is DeliveryStatus.PENDING
    monkeypatch.setattr(repo, "_aggregate", aggregate)
    await asyncio.gather(*(repo.reconcile_outbox_result("svc", op.operation_id, items[0].outbox_id, projected) for _ in range(2)))
    audits = await repo.get_audit_events("svc", op.operation_id)
    assert sum(event.details.get("status") == "completed" for event in audits) == 1


@pytest.mark.asyncio
async def test_failed_submission_does_not_starve_other_targets(db):
    repo, now, op, items = await seed(db, count=2)
    first = await dispatch(repo, op, [LineInternalApiRetryableError("timeout")])
    second = await dispatch(repo, op, [None])
    assert first.commands[0].command_id != second.commands[0].command_id


@pytest.mark.asyncio
async def test_legacy_permanent_failure_and_missing_completion_repaired(db):
    repo, now, op, items = await seed(db)
    db.connection.execute(update(outbox_table).values(state="permanent_failure"))
    result = await repo.refresh_delivery_aggregate("svc", op.operation_id)
    assert result.status is OperationStatus.COMPLETED_WITH_ERRORS and result.completed_at == NOW
    now[0] += timedelta(days=1)
    assert (await repo.refresh_delivery_aggregate("svc", op.operation_id)).completed_at == NOW


@pytest.mark.asyncio
async def test_runner_pages_and_failure_isolation_and_private_logs(db, caplog):
    repo, now, op, items = await seed(db)
    calls = []
    reconciled = []
    class BrokenDispatcher:
        async def dispatch_operation(self, **kwargs):
            calls.append(kwargs["operation_id"])
            if len(calls) == 1: raise RuntimeError("private message/member/token")
    class Reconciler:
        async def reconcile_operation(self, **kwargs): reconciled.append(kwargs["operation_id"])
    runner = AdminNotificationRunner(repository=repo, dispatcher=BrokenDispatcher(), reconciler=Reconciler(), service_ids=["svc"])
    await runner.run_cycle()
    await runner.run_cycle()  # page exhausted: resets cursor
    await runner.run_cycle()
    assert len(calls) == 2
    assert len(reconciled) == 2
    assert "RuntimeError" in caplog.text and "private message" not in caplog.text
    # SQL selection is bounded and keyset pagination does not revisit the first page.
    for _ in range(3): await seed(db)
    first = await repo.list_recovery_operations("svc", limit=2)
    second = await repo.list_recovery_operations("svc", limit=2, after=first[-1].operation_id)
    assert len(first) == len(second) == 2
    assert not {x.operation_id for x in first} & {x.operation_id for x in second}


@pytest.mark.asyncio
async def test_standard_main_runtime_owns_single_runner_and_cleans_up(db, monkeypatch):
    import httpx
    from pydantic import SecretStr
    from app.core.settings_admin import AdminSettings
    from app.main_admin import create_admin_app
    from app.api.admin_entry_deps import get_admin_application_service
    from app.adapter.current_db_external_business import CurrentDbExternalBusinessGateway
    from test_admin_line_internal_client import _result
    repo, now, op, items = await seed(db)
    requests = []
    command = AdminLineOutboxDispatcher._command(items[0])
    def handler(request):
        requests.append(request.method)
        return httpx.Response(202 if request.method == "POST" else 200,
                              json=_result(command, "accepted" if request.method == "POST" else "unknown"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr("app.runtime.admin_line.get_engine", lambda: db)
        monkeypatch.setattr("app.runtime.admin_line.get_client", lambda: client)
        monkeypatch.setattr("app.db.engine.get_engine", lambda: db)
        settings = AdminSettings(_env_file=None, database_url="postgresql://unused/unused", app_env="production",
            admin_notification_runner_service_ids="svc", admin_internal_api_scopes={"svc":"org"},
            current_db_business_centers={"org":"center"}, admin_line_internal_api_base_url="https://line.internal",
            admin_line_internal_api_bearer_token=SecretStr("offline-test"))
        app = create_admin_app(settings)
        composition = app.state.admin_runtime_composition
        assert isinstance(composition.external_business, CurrentDbExternalBusinessGateway)
        assert app.dependency_overrides[get_admin_application_service]() is composition.application
        boundary = composition.boundary
        assert boundary.runner._repository is boundary.repository is composition.application.notification_service._repository
        boundary.runner._interval = .01
        with pytest.raises(RuntimeError, match="lifespan body"):
            async with app.router.lifespan_context(app):
                task = boundary.runner._task
                for _ in range(100):
                    if (await repo.get_operation("svc", op.operation_id)).completed_at: break
                    await asyncio.sleep(.01)
                assert (await repo.get_operation("svc", op.operation_id)).status is OperationStatus.COMPLETED_WITH_ERRORS
                raise RuntimeError("lifespan body")
        assert task.done() and boundary.runner._task is None
        assert requests == ["POST", "GET"]


def test_reserved_mutation_maps_to_existing_conflict_response():
    from fastapi import HTTPException
    from app.api.routes.admin import _translate
    from app.domain.errors.admin_notification_repository import ReservedNotificationMutationError
    with pytest.raises(HTTPException) as failure:
        _translate(ReservedNotificationMutationError("reserved"))
    assert failure.value.status_code == 409


@pytest.mark.asyncio
async def test_real_service_validation_edits_and_post_reservation_guards(db):
    from app.application.notification_service import (
        UpdateNotificationDraftCommand, ReplaceNotificationTargetsCommand,
        ValidateNotificationOperationCommand, SendNotificationOperationCommand)
    repo, now, op, items = await seed(db, reserved=False)
    service = NotificationService(repository=repo, clock=lambda: NOW)
    edited = await service.update_draft(UpdateNotificationDraftCommand("svc", op.operation_id, "hello", "updated", "note"))
    assert edited.status is OperationStatus.DRAFT and edited.message.introduction == "updated"
    await service.replace_targets(ReplaceNotificationTargetsCommand("svc", op.operation_id, ()))
    result = await service.validate_operation(ValidateNotificationOperationCommand("svc", op.operation_id, "staff", "request"))
    assert not result.can_proceed and result.blocking_reason == "no_selected_targets"
    repo, now, op, items = await seed(db)
    service = NotificationService(repository=repo, clock=lambda: NOW)
    for call, command in (
        (service.update_draft, UpdateNotificationDraftCommand("svc", op.operation_id, "hello", "updated", "note")),
        (service.replace_targets, ReplaceNotificationTargetsCommand("svc", op.operation_id, ())),
        (service.validate_operation, ValidateNotificationOperationCommand("svc", op.operation_id, "staff", "request")),
    ):
        with pytest.raises(OperationNotEditableError): await call(command)
    reserved = await service.send_operation(SendNotificationOperationCommand("svc", op.operation_id, "staff", "again"))
    assert reserved.send_requested_at == NOW
    assert await repo.get_outbox_records("svc", op.operation_id) == items


@pytest.mark.asyncio
async def test_duplicate_reservation_and_rollback_cannot_unfreeze(db):
    from app.domain.errors.admin_notification_repository import SendAttemptAlreadyExistsError
    repo, now, op, items = await seed(db)
    deliveries = await repo.get_deliveries("svc", op.operation_id)
    with pytest.raises(SendAttemptAlreadyExistsError):
        await repo.begin_send_attempt("svc", op.operation_id, deliveries, items,
            NotificationAuditEvent(uuid4(), op.operation_id, "send_requested", "staff", {}, NOW), send_requested_at=NOW)
    with pytest.raises(RepositoryStateError):
        await repo.rollback_send_attempt("svc", op.operation_id, [d.delivery_id for d in deliveries])
    assert (await repo.get_operation("svc", op.operation_id)).send_requested_at == NOW


@pytest.mark.asyncio
async def test_cancelled_is_preserved_and_not_dispatched(db):
    repo, now, op, items = await seed(db)
    reserved = await repo.get_operation("svc", op.operation_id)
    await repo.update_operation("svc", op.operation_id, replace(reserved, status=OperationStatus.CANCELLED))
    assert await repo.claim_outbox_records("svc", op.operation_id) == ()
    assert (await repo.refresh_delivery_aggregate("svc", op.operation_id)).status is OperationStatus.CANCELLED
    assert await repo.list_recovery_operations("svc") == ()


@pytest.mark.asyncio
async def test_shutdown_cancels_inflight_dispatch_leaving_recoverable_claim(db):
    repo, now, op, items = await seed(db)
    started = asyncio.Event()
    class Blocked:
        async def submit_notification_command(self, command):
            started.set()
            await asyncio.Event().wait()
    runner = AdminNotificationRunner(repository=repo, service_ids=["svc"],
        dispatcher=AdminLineOutboxDispatcher(repository=repo, line_client=Blocked()),
        reconciler=AdminLineResultReconciler(repository=repo, line_client=Client([])))
    await runner.start()
    task = runner._task
    await asyncio.wait_for(started.wait(), timeout=1)
    await asyncio.wait_for(runner.stop(), timeout=1)
    assert task.done()
    assert (await repo.get_outbox_records("svc", op.operation_id))[0].state is NotificationOutboxState.DELIVERING
    now[0] += timedelta(seconds=60)
    replay = await dispatch(repo, op, [None])
    assert replay.commands[0].command_id == items[0].command_id
