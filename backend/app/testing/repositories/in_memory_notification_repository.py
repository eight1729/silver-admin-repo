"""Thread-safe in-memory storage for the local notification demo."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from threading import RLock
from typing import Callable, Iterable, TypeVar
from uuid import UUID

from app.domain.enums.enums import DeliveryStatus
from app.domain.errors.admin_notification_repository import (
    AuditEventAlreadyExistsError,
    DeliveryAlreadyExistsError,
    DeliveryNotFoundError,
    OperationAlreadyExistsError,
    OperationNotFoundError,
    RepositoryStateError,
    SendAttemptAlreadyExistsError,
    ServiceScopeViolationError,
)
from app.domain.models.admin_notification import (
    NotificationAuditEvent,
    NotificationDeliveryRecord,
    NotificationOperationRecord,
    NotificationOutboxRecord,
    NotificationOutboxState,
    NotificationTargetRecord,
)

_Record = TypeVar(
    "_Record",
    NotificationOperationRecord,
    NotificationTargetRecord,
    NotificationDeliveryRecord,
    NotificationAuditEvent,
)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RepositoryStateError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _copy(record: _Record) -> _Record:
    return replace(record)


class InMemoryNotificationRepository:
    """Store notification records for one local-demo service.

    This class deliberately performs no workflow or status-transition logic.
    """

    def __init__(
        self,
        *,
        service_id: str = "demo-service",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service_id = service_id
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._operations: dict[UUID, NotificationOperationRecord] = {}
        self._targets: dict[UUID, dict[str, NotificationTargetRecord]] = {}
        self._deliveries: dict[UUID, NotificationDeliveryRecord] = {}
        self._operation_deliveries: dict[UUID, list[UUID]] = {}
        self._audit_events: dict[UUID, NotificationAuditEvent] = {}
        self._operation_audits: dict[UUID, list[UUID]] = {}
        self._outbox: dict[UUID, NotificationOutboxRecord] = {}
        self._outbox_by_operation: dict[UUID, list[UUID]] = {}
        self._lock = RLock()

    def _check_scope(self, service_id: str) -> None:
        if service_id != self._service_id:
            raise ServiceScopeViolationError("service is outside repository scope")

    def _require_operation(
        self, service_id: str, operation_id: UUID
    ) -> NotificationOperationRecord:
        self._check_scope(service_id)
        operation = self._operations.get(operation_id)
        if operation is None:
            raise OperationNotFoundError("notification operation was not found")
        if operation.service_id != service_id:
            raise ServiceScopeViolationError("operation is outside service scope")
        return operation

    def _now(self) -> datetime:
        return _utc(self._clock(), "clock result")

    @staticmethod
    def _normalise_operation(
        operation: NotificationOperationRecord,
    ) -> NotificationOperationRecord:
        return replace(
            operation,
            created_at=_utc(operation.created_at, "created_at"),
            updated_at=_utc(operation.updated_at, "updated_at"),
            validated_at=(
                _utc(operation.validated_at, "validated_at")
                if operation.validated_at is not None
                else None
            ),
            send_requested_at=(
                _utc(operation.send_requested_at, "send_requested_at")
                if operation.send_requested_at is not None
                else None
            ),
            completed_at=(
                _utc(operation.completed_at, "completed_at")
                if operation.completed_at is not None
                else None
            ),
        )

    @staticmethod
    def _normalise_target(target: NotificationTargetRecord) -> NotificationTargetRecord:
        return replace(
            target,
            created_at=_utc(target.created_at, "created_at"),
            updated_at=_utc(target.updated_at, "updated_at"),
        )

    @staticmethod
    def _normalise_delivery(
        delivery: NotificationDeliveryRecord,
    ) -> NotificationDeliveryRecord:
        return replace(
            delivery,
            created_at=_utc(delivery.created_at, "created_at"),
            updated_at=_utc(delivery.updated_at, "updated_at"),
            sent_at=(
                _utc(delivery.sent_at, "sent_at")
                if delivery.sent_at is not None
                else None
            ),
        )

    @staticmethod
    def _normalise_audit(event: NotificationAuditEvent) -> NotificationAuditEvent:
        return replace(event, created_at=_utc(event.created_at, "created_at"))

    def create_operation(
        self, operation: NotificationOperationRecord
    ) -> NotificationOperationRecord:
        with self._lock:
            self._check_scope(operation.service_id)
            if operation.operation_id in self._operations:
                raise OperationAlreadyExistsError(
                    "notification operation already exists"
                )
            stored = self._normalise_operation(operation)
            self._operations[stored.operation_id] = stored
            self._targets[stored.operation_id] = {}
            self._operation_deliveries[stored.operation_id] = []
            self._operation_audits[stored.operation_id] = []
            self._outbox_by_operation[stored.operation_id] = []
            return _copy(stored)

    def _prepare_audit(
        self, operation_id: UUID, event: NotificationAuditEvent
    ) -> NotificationAuditEvent:
        if event.operation_id != operation_id:
            raise RepositoryStateError("audit operation_id does not match")
        if event.audit_id in self._audit_events:
            raise AuditEventAlreadyExistsError("audit event already exists")
        return self._normalise_audit(event)

    def _store_audit(
        self, operation_id: UUID, event: NotificationAuditEvent
    ) -> None:
        self._audit_events[event.audit_id] = event
        self._operation_audits[operation_id].append(event.audit_id)

    def create_operation_with_audit(
        self,
        operation: NotificationOperationRecord,
        event: NotificationAuditEvent,
    ) -> NotificationOperationRecord:
        with self._lock:
            self._check_scope(operation.service_id)
            if operation.operation_id in self._operations:
                raise OperationAlreadyExistsError(
                    "notification operation already exists"
                )
            audit = self._prepare_audit(operation.operation_id, event)
            stored = self._normalise_operation(operation)
            self._operations[stored.operation_id] = stored
            self._targets[stored.operation_id] = {}
            self._operation_deliveries[stored.operation_id] = []
            self._operation_audits[stored.operation_id] = []
            self._outbox_by_operation[stored.operation_id] = []
            self._store_audit(stored.operation_id, audit)
            return _copy(stored)

    def get_operation(
        self, service_id: str, operation_id: UUID
    ) -> NotificationOperationRecord:
        with self._lock:
            return _copy(self._require_operation(service_id, operation_id))

    def update_operation(
        self,
        service_id: str,
        operation_id: UUID,
        operation: NotificationOperationRecord,
    ) -> NotificationOperationRecord:
        with self._lock:
            current = self._require_operation(service_id, operation_id)
            if operation.service_id != service_id:
                raise ServiceScopeViolationError("operation is outside service scope")
            if operation.operation_id != operation_id:
                raise RepositoryStateError("operation_id cannot be changed")
            stored = self._normalise_operation(
                replace(
                    operation,
                    created_at=current.created_at,
                    updated_at=self._now(),
                )
            )
            self._operations[stored.operation_id] = stored
            return _copy(stored)

    def update_operation_with_audit(
        self,
        service_id: str,
        operation_id: UUID,
        operation: NotificationOperationRecord,
        event: NotificationAuditEvent,
    ) -> NotificationOperationRecord:
        with self._lock:
            current = self._require_operation(service_id, operation_id)
            if operation.service_id != service_id:
                raise ServiceScopeViolationError("operation is outside service scope")
            if operation.operation_id != operation_id:
                raise RepositoryStateError("operation_id cannot be changed")
            audit = self._prepare_audit(operation_id, event)
            stored = self._normalise_operation(
                replace(operation, created_at=current.created_at, updated_at=self._now())
            )
            self._operations[operation_id] = stored
            self._store_audit(operation_id, audit)
            return _copy(stored)

    def list_operations(self, service_id: str) -> tuple[NotificationOperationRecord, ...]:
        with self._lock:
            self._check_scope(service_id)
            rows = [
                operation
                for operation in self._operations.values()
                if operation.service_id == service_id
            ]
            rows.sort(key=lambda item: (item.created_at, str(item.operation_id)))
            return tuple(_copy(row) for row in rows)

    def replace_targets(
        self,
        service_id: str,
        operation_id: UUID,
        targets: Iterable[NotificationTargetRecord],
    ) -> tuple[NotificationTargetRecord, ...]:
        with self._lock:
            self._require_operation(service_id, operation_id)
            replacement: dict[str, NotificationTargetRecord] = {}
            for target in targets:
                if target.operation_id != operation_id:
                    raise RepositoryStateError("target operation_id does not match")
                stored = self._normalise_target(target)
                if stored.member_id in replacement:
                    raise RepositoryStateError("duplicate target member_id")
                replacement[stored.member_id] = stored
            self._targets[operation_id] = replacement
            return tuple(_copy(row) for row in replacement.values())

    def replace_targets_with_operation_and_audit(
        self,
        service_id: str,
        operation_id: UUID,
        targets: Iterable[NotificationTargetRecord],
        operation: NotificationOperationRecord,
        event: NotificationAuditEvent,
    ) -> tuple[NotificationOperationRecord, tuple[NotificationTargetRecord, ...]]:
        with self._lock:
            current = self._require_operation(service_id, operation_id)
            if operation.service_id != service_id:
                raise ServiceScopeViolationError("operation is outside service scope")
            if operation.operation_id != operation_id:
                raise RepositoryStateError("operation_id cannot be changed")
            replacement: dict[str, NotificationTargetRecord] = {}
            for target in targets:
                if target.operation_id != operation_id:
                    raise RepositoryStateError("target operation_id does not match")
                stored_target = self._normalise_target(target)
                if stored_target.member_id in replacement:
                    raise RepositoryStateError("duplicate target member_id")
                replacement[stored_target.member_id] = stored_target
            audit = self._prepare_audit(operation_id, event)
            stored_operation = self._normalise_operation(
                replace(operation, created_at=current.created_at, updated_at=self._now())
            )
            self._targets[operation_id] = replacement
            self._operations[operation_id] = stored_operation
            self._store_audit(operation_id, audit)
            return _copy(stored_operation), tuple(
                _copy(row) for row in replacement.values()
            )

    def get_targets(
        self, service_id: str, operation_id: UUID
    ) -> tuple[NotificationTargetRecord, ...]:
        with self._lock:
            self._require_operation(service_id, operation_id)
            rows = sorted(
                self._targets[operation_id].values(), key=lambda item: item.member_id
            )
            return tuple(_copy(row) for row in rows)

    def add_deliveries(
        self,
        service_id: str,
        operation_id: UUID,
        deliveries: Iterable[NotificationDeliveryRecord],
    ) -> tuple[NotificationDeliveryRecord, ...]:
        with self._lock:
            self._require_operation(service_id, operation_id)
            pending: list[NotificationDeliveryRecord] = []
            seen: set[UUID] = set()
            for delivery in deliveries:
                if delivery.operation_id != operation_id:
                    raise RepositoryStateError("delivery operation_id does not match")
                if delivery.delivery_id in self._deliveries or delivery.delivery_id in seen:
                    raise DeliveryAlreadyExistsError("notification delivery already exists")
                seen.add(delivery.delivery_id)
                pending.append(self._normalise_delivery(delivery))
            for delivery in pending:
                self._deliveries[delivery.delivery_id] = delivery
                self._operation_deliveries[operation_id].append(delivery.delivery_id)
            return tuple(_copy(row) for row in pending)

    def begin_send_attempt(
        self,
        service_id: str,
        operation_id: UUID,
        deliveries: Iterable[NotificationDeliveryRecord],
        outbox_records: Iterable[NotificationOutboxRecord],
        event: NotificationAuditEvent,
        *,
        send_requested_at: datetime,
    ) -> tuple[NotificationOperationRecord, tuple[NotificationDeliveryRecord, ...]]:
        """Atomically reserve one operation send and add its deliveries."""
        with self._lock:
            operation = self._require_operation(service_id, operation_id)
            if operation.send_requested_at is not None or self._operation_deliveries[operation_id]:
                raise SendAttemptAlreadyExistsError(
                    "notification operation already has a send attempt"
                )
            pending: list[NotificationDeliveryRecord] = []
            outbox = tuple(outbox_records)
            seen: set[UUID] = set()
            for delivery in deliveries:
                if delivery.operation_id != operation_id:
                    raise RepositoryStateError("delivery operation_id does not match")
                if delivery.delivery_id in self._deliveries or delivery.delivery_id in seen:
                    raise DeliveryAlreadyExistsError("notification delivery already exists")
                seen.add(delivery.delivery_id)
                pending.append(self._normalise_delivery(delivery))
            audit = self._prepare_audit(operation_id, event)
            command_ids = {item.command_id for item in self._outbox.values()}
            idempotency_keys = {item.idempotency_key for item in self._outbox.values()}
            target_ids = {
                item.target_id
                for item in self._outbox.values()
                if item.operation_id == operation_id
            }
            pending_outbox_ids: set[UUID] = set()
            pending_command_ids: set[UUID] = set()
            pending_idempotency_keys: set[str] = set()
            pending_target_ids: set[UUID] = set()
            for item in outbox:
                if item.operation_id != operation_id or item.service_id != service_id:
                    raise RepositoryStateError("outbox scope does not match operation")
                if (
                    item.outbox_id in self._outbox
                    or item.outbox_id in pending_outbox_ids
                    or item.command_id in command_ids
                    or item.command_id in pending_command_ids
                    or item.idempotency_key in idempotency_keys
                    or item.idempotency_key in pending_idempotency_keys
                    or item.target_id in target_ids
                    or item.target_id in pending_target_ids
                ):
                    raise SendAttemptAlreadyExistsError(
                        "notification send intent already exists"
                    )
                pending_outbox_ids.add(item.outbox_id)
                pending_command_ids.add(item.command_id)
                pending_idempotency_keys.add(item.idempotency_key)
                pending_target_ids.add(item.target_id)
            for delivery in pending:
                self._deliveries[delivery.delivery_id] = delivery
                self._operation_deliveries[operation_id].append(delivery.delivery_id)
            for item in outbox:
                self._outbox[item.outbox_id] = item
                self._outbox_by_operation[operation_id].append(item.outbox_id)
            stored_operation = self._normalise_operation(
                replace(
                    operation,
                    send_requested_at=_utc(send_requested_at, "send_requested_at"),
                    updated_at=self._now(),
                )
            )
            self._operations[operation_id] = stored_operation
            self._store_audit(operation_id, audit)
            return _copy(stored_operation), tuple(_copy(row) for row in pending)

    def get_outbox_records(
        self, service_id: str, operation_id: UUID
    ) -> tuple[NotificationOutboxRecord, ...]:
        with self._lock:
            self._require_operation(service_id, operation_id)
            return tuple(
                self._outbox[outbox_id]
                for outbox_id in self._outbox_by_operation[operation_id]
            )

    def claim_outbox_records(self, service_id, operation_id):
        with self._lock:
            self._require_operation(service_id, operation_id)
            claimed = []
            for outbox_id in self._outbox_by_operation[operation_id]:
                item = self._outbox[outbox_id]
                if item.state in (
                    NotificationOutboxState.PENDING,
                    NotificationOutboxState.RETRYABLE_FAILURE,
                ):
                    item = replace(item, state=NotificationOutboxState.DELIVERING)
                    self._outbox[outbox_id] = item
                    claimed.append(item)
            return tuple(claimed)

    def update_outbox_state(self, service_id, operation_id, outbox_id, state):
        with self._lock:
            self._require_operation(service_id, operation_id)
            item = self._outbox.get(outbox_id)
            if item is None or item.operation_id != operation_id:
                raise RepositoryStateError("notification outbox record was not found")
            stored = replace(item, state=state)
            self._outbox[outbox_id] = stored
            return stored

    def rollback_send_attempt(
        self,
        service_id: str,
        operation_id: UUID,
        delivery_ids: Iterable[UUID],
    ) -> NotificationOperationRecord:
        """Remove an unqueued attempt so the operation can safely be retried."""
        with self._lock:
            operation = self._require_operation(service_id, operation_id)
            expected = tuple(delivery_ids)
            current = tuple(self._operation_deliveries[operation_id])
            if current != expected:
                raise RepositoryStateError("send attempt changed before rollback")
            for delivery_id in expected:
                delivery = self._deliveries[delivery_id]
                if delivery.status not in (DeliveryStatus.PENDING, DeliveryStatus.SKIPPED):
                    raise RepositoryStateError("processed delivery cannot be rolled back")
            for delivery_id in expected:
                del self._deliveries[delivery_id]
            self._operation_deliveries[operation_id].clear()
            stored = self._normalise_operation(
                replace(operation, send_requested_at=None, updated_at=self._now())
            )
            self._operations[operation_id] = stored
            return _copy(stored)

    def get_deliveries(
        self, service_id: str, operation_id: UUID
    ) -> tuple[NotificationDeliveryRecord, ...]:
        with self._lock:
            self._require_operation(service_id, operation_id)
            rows = [
                self._deliveries[delivery_id]
                for delivery_id in self._operation_deliveries[operation_id]
            ]
            rows.sort(key=lambda item: (item.created_at, str(item.delivery_id)))
            return tuple(_copy(row) for row in rows)

    def update_delivery(
        self,
        service_id: str,
        operation_id: UUID,
        delivery_id: UUID,
        delivery: NotificationDeliveryRecord,
    ) -> NotificationDeliveryRecord:
        with self._lock:
            self._require_operation(service_id, operation_id)
            current = self._deliveries.get(delivery_id)
            if current is None or current.operation_id != operation_id:
                raise DeliveryNotFoundError("notification delivery was not found")
            if delivery.delivery_id != delivery_id:
                raise RepositoryStateError("delivery_id cannot be changed")
            if delivery.operation_id != operation_id:
                raise RepositoryStateError("delivery operation_id does not match")
            stored = self._normalise_delivery(
                replace(
                    delivery,
                    created_at=current.created_at,
                    updated_at=self._now(),
                )
            )
            self._deliveries[stored.delivery_id] = stored
            return _copy(stored)

    def append_audit_event(
        self,
        service_id: str,
        operation_id: UUID,
        event: NotificationAuditEvent,
    ) -> NotificationAuditEvent:
        with self._lock:
            self._require_operation(service_id, operation_id)
            stored = self._prepare_audit(operation_id, event)
            self._store_audit(operation_id, stored)
            return _copy(stored)

    def get_audit_events(
        self, service_id: str, operation_id: UUID
    ) -> tuple[NotificationAuditEvent, ...]:
        with self._lock:
            self._require_operation(service_id, operation_id)
            rows = [
                self._audit_events[audit_id]
                for audit_id in self._operation_audits[operation_id]
            ]
            rows.sort(key=lambda item: (item.created_at, str(item.audit_id)))
            return tuple(_copy(row) for row in rows)

    def reset(self) -> None:
        with self._lock:
            self._operations.clear()
            self._targets.clear()
            self._deliveries.clear()
            self._operation_deliveries.clear()
            self._audit_events.clear()
            self._operation_audits.clear()
            self._outbox.clear()
            self._outbox_by_operation.clear()
