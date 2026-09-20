"""SQLAlchemy Core persistent adapter for Admin-owned notification data."""

from dataclasses import replace
from datetime import datetime, timezone, timedelta
from typing import Iterable, Mapping
from uuid import UUID, uuid4

from sqlalchemy import delete, insert, select, update, and_, or_
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.exc import IntegrityError

from app.db.admin_tables import (
    admin_notification_audit_events,
    admin_notification_deliveries,
    admin_notification_operations,
    admin_notification_outbox,
    admin_notification_targets,
)
from app.domain.enums.enums import DeliveryStatus, NotificationEligibilityReason, OperationStatus
from app.domain.enums.notification_type import NotificationType
from app.domain.errors.admin_notification_repository import (
    AuditEventAlreadyExistsError,
    DeliveryAlreadyExistsError,
    DeliveryNotFoundError,
    OperationAlreadyExistsError,
    OperationNotFoundError,
    RepositoryStateError,
    ReservedNotificationMutationError,
    SendAttemptAlreadyExistsError,
    ServiceScopeViolationError,
)
from app.domain.models.admin_notification import (
    NotificationAuditEvent,
    NotificationDeliveryRecord,
    NotificationMessage,
    NotificationOperationRecord,
    NotificationOutboxRecord,
    NotificationOutboxState,
    NotificationTargetRecord,
)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RepositoryStateError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _loaded_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _optional_utc(value: datetime | None, field_name: str) -> datetime | None:
    return _utc(value, field_name) if value is not None else None


def _plain_json(value):
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    return value


class SqlAlchemyAdminNotificationRepository:
    """Async adapter with operation-row locks for reservation and projection."""

    def __init__(self, engine: AsyncEngine, *, clock=None) -> None:
        self._engine = engine
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        return _utc(self._clock(), "clock result")

    @staticmethod
    def _guard_snapshot(current, proposed):
        if current.send_requested_at is not None:
            fields = ("message", "message_version", "message_hash", "job_id", "job_version",
                      "notification_type", "validation_snapshot", "validated_at", "send_requested_at")
            if any(getattr(current, name) != getattr(proposed, name) for name in fields):
                raise ReservedNotificationMutationError("reserved notification snapshot is immutable")

    @staticmethod
    def _guard_targets(operation):
        if operation.send_requested_at is not None:
            raise ReservedNotificationMutationError("reserved notification targets are immutable")

    @staticmethod
    def _operation_values(operation: NotificationOperationRecord) -> dict:
        return {
            "operation_id": str(operation.operation_id),
            "service_id": operation.service_id,
            "job_id": operation.job_id,
            "job_version": operation.job_version,
            "notification_type": operation.notification_type.value,
            "message_greeting": operation.message.greeting,
            "message_introduction": operation.message.introduction,
            "message_note": operation.message.note,
            "message_version": operation.message_version,
            "message_hash": operation.message_hash,
            "validation_snapshot": (
                _plain_json(operation.validation_snapshot)
                if operation.validation_snapshot is not None
                else None
            ),
            "status": operation.status.value,
            "created_by_staff_id": operation.created_by_staff_id,
            "created_at": _utc(operation.created_at, "created_at"),
            "updated_at": _utc(operation.updated_at, "updated_at"),
            "validated_at": _optional_utc(operation.validated_at, "validated_at"),
            "send_requested_at": _optional_utc(
                operation.send_requested_at, "send_requested_at"
            ),
            "completed_at": _optional_utc(operation.completed_at, "completed_at"),
        }

    @staticmethod
    def _operation(row) -> NotificationOperationRecord:
        return NotificationOperationRecord(
            operation_id=UUID(row["operation_id"]),
            service_id=row["service_id"],
            job_id=row["job_id"],
            job_version=row["job_version"],
            notification_type=NotificationType(row["notification_type"]),
            message=NotificationMessage(
                row["message_greeting"],
                row["message_introduction"],
                row["message_note"],
            ),
            status=OperationStatus(row["status"]),
            created_by_staff_id=row["created_by_staff_id"],
            created_at=_loaded_utc(row["created_at"]),
            updated_at=_loaded_utc(row["updated_at"]),
            validated_at=_loaded_utc(row["validated_at"]),
            send_requested_at=_loaded_utc(row["send_requested_at"]),
            completed_at=_loaded_utc(row["completed_at"]),
            message_version=row["message_version"],
            message_hash=row["message_hash"],
            validation_snapshot=row["validation_snapshot"],
        )

    @staticmethod
    async def _require_operation(
        conn: AsyncConnection, service_id: str, operation_id: UUID, *, lock: bool = False
    ) -> NotificationOperationRecord:
        stmt = select(admin_notification_operations).where(
            admin_notification_operations.c.operation_id == str(operation_id)
        )
        if lock:
            stmt = stmt.with_for_update()
        row = (await conn.execute(stmt)).mappings().first()
        if row is None:
            raise OperationNotFoundError("notification operation was not found")
        operation = SqlAlchemyAdminNotificationRepository._operation(row)
        if operation.service_id != service_id:
            raise ServiceScopeViolationError("operation is outside service scope")
        return operation

    async def create_operation(self, operation):
        values = self._operation_values(operation)
        try:
            async with self._engine.begin() as conn:
                await conn.execute(insert(admin_notification_operations).values(**values))
        except IntegrityError as exc:
            raise OperationAlreadyExistsError("notification operation already exists") from exc
        return await self.get_operation(operation.service_id, operation.operation_id)

    async def resolve_operation_service_id(self, operation_id: UUID) -> str:
        """Resolve the persisted scope for an opaque queue operation ID."""
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(admin_notification_operations.c.service_id).where(
                        admin_notification_operations.c.operation_id
                        == str(operation_id)
                    )
                )
            ).first()
        if row is None:
            raise OperationNotFoundError("notification operation was not found")
        return row.service_id

    @staticmethod
    async def _insert_audit(conn, operation_id, event) -> None:
        if event.operation_id != operation_id:
            raise RepositoryStateError("audit operation_id does not match")
        await conn.execute(
            insert(admin_notification_audit_events).values(
                audit_id=str(event.audit_id),
                operation_id=str(operation_id),
                event_type=event.event_type,
                staff_id=event.staff_id,
                details=_plain_json(event.details),
                created_at=_utc(event.created_at, "created_at"),
            )
        )

    async def create_operation_with_audit(self, operation, event):
        try:
            async with self._engine.begin() as conn:
                await conn.execute(
                    insert(admin_notification_operations).values(
                        **self._operation_values(operation)
                    )
                )
                await self._insert_audit(conn, operation.operation_id, event)
        except IntegrityError as exc:
            raise OperationAlreadyExistsError(
                "notification operation or audit event already exists"
            ) from exc
        return operation

    async def get_operation(self, service_id, operation_id):
        async with self._engine.connect() as conn:
            return await self._require_operation(conn, service_id, operation_id)

    async def update_operation(self, service_id, operation_id, operation):
        async with self._engine.begin() as conn:
            current = await self._require_operation(conn, service_id, operation_id, lock=True)
            self._guard_snapshot(current, operation)
            if operation.operation_id != operation_id:
                raise RepositoryStateError("operation_id cannot be changed")
            if operation.service_id != service_id:
                raise ServiceScopeViolationError("operation is outside service scope")
            stored = replace(operation, created_at=current.created_at, updated_at=self._now())
            values = self._operation_values(stored)
            values.pop("operation_id")
            await conn.execute(
                update(admin_notification_operations)
                .where(admin_notification_operations.c.operation_id == str(operation_id))
                .values(**values)
            )
        return stored

    async def update_operation_with_audit(
        self, service_id, operation_id, operation, event
    ):
        try:
            async with self._engine.begin() as conn:
                current = await self._require_operation(
                    conn, service_id, operation_id, lock=True
                )
                self._guard_snapshot(current, operation)
                if operation.operation_id != operation_id:
                    raise RepositoryStateError("operation_id cannot be changed")
                if operation.service_id != service_id:
                    raise ServiceScopeViolationError(
                        "operation is outside service scope"
                    )
                stored = replace(
                    operation, created_at=current.created_at, updated_at=self._now()
                )
                values = self._operation_values(stored)
                values.pop("operation_id")
                await conn.execute(
                    update(admin_notification_operations)
                    .where(
                        admin_notification_operations.c.operation_id
                        == str(operation_id)
                    )
                    .values(**values)
                )
                await self._insert_audit(conn, operation_id, event)
        except IntegrityError as exc:
            raise AuditEventAlreadyExistsError("audit event already exists") from exc
        return stored

    async def list_operations(self, service_id):
        async with self._engine.connect() as conn:
            rows = (await conn.execute(
                select(admin_notification_operations)
                .where(admin_notification_operations.c.service_id == service_id)
                .order_by(admin_notification_operations.c.created_at, admin_notification_operations.c.operation_id)
            )).mappings().all()
        return tuple(self._operation(row) for row in rows)

    async def replace_targets(self, service_id, operation_id, targets):
        pending = tuple(targets)
        seen = set()
        for target in pending:
            if target.operation_id != operation_id:
                raise RepositoryStateError("target operation_id does not match")
            if target.member_id in seen:
                raise RepositoryStateError("duplicate target member_id")
            seen.add(target.member_id)
            _utc(target.created_at, "created_at")
            _utc(target.updated_at, "updated_at")
        async with self._engine.begin() as conn:
            current = await self._require_operation(conn, service_id, operation_id, lock=True)
            self._guard_targets(current)
            await conn.execute(delete(admin_notification_targets).where(admin_notification_targets.c.operation_id == str(operation_id)))
            if pending:
                await conn.execute(insert(admin_notification_targets), [
                    {
                        "operation_id": str(item.operation_id),
                        "member_id": item.member_id,
                        "selected": item.selected,
                        "line_linked": item.line_linked,
                        "eligibility": item.eligibility.value if item.eligibility else None,
                        "reason": item.reason,
                        "created_at": item.created_at,
                        "updated_at": item.updated_at,
                    }
                    for item in pending
                ])
        return await self.get_targets(service_id, operation_id)

    async def replace_targets_with_operation_and_audit(
        self, service_id, operation_id, targets, operation, event
    ):
        pending = tuple(targets)
        seen = set()
        for target in pending:
            if target.operation_id != operation_id:
                raise RepositoryStateError("target operation_id does not match")
            if target.member_id in seen:
                raise RepositoryStateError("duplicate target member_id")
            seen.add(target.member_id)
            _utc(target.created_at, "created_at")
            _utc(target.updated_at, "updated_at")
        try:
            async with self._engine.begin() as conn:
                current = await self._require_operation(
                    conn, service_id, operation_id, lock=True
                )
                self._guard_targets(current)
                self._guard_snapshot(current, operation)
                if operation.operation_id != operation_id:
                    raise RepositoryStateError("operation_id cannot be changed")
                if operation.service_id != service_id:
                    raise ServiceScopeViolationError(
                        "operation is outside service scope"
                    )
                await conn.execute(
                    delete(admin_notification_targets).where(
                        admin_notification_targets.c.operation_id
                        == str(operation_id)
                    )
                )
                if pending:
                    await conn.execute(
                        insert(admin_notification_targets),
                        [
                            {
                                "operation_id": str(item.operation_id),
                                "member_id": item.member_id,
                                "selected": item.selected,
                                "line_linked": item.line_linked,
                                "eligibility": (
                                    item.eligibility.value
                                    if item.eligibility
                                    else None
                                ),
                                "reason": item.reason,
                                "created_at": _utc(item.created_at, "created_at"),
                                "updated_at": _utc(item.updated_at, "updated_at"),
                            }
                            for item in pending
                        ],
                    )
                stored = replace(
                    operation, created_at=current.created_at, updated_at=self._now()
                )
                values = self._operation_values(stored)
                values.pop("operation_id")
                await conn.execute(
                    update(admin_notification_operations)
                    .where(
                        admin_notification_operations.c.operation_id
                        == str(operation_id)
                    )
                    .values(**values)
                )
                await self._insert_audit(conn, operation_id, event)
        except IntegrityError as exc:
            raise AuditEventAlreadyExistsError("atomic target update failed") from exc
        return stored, tuple(
            replace(item, line_subject=None) for item in pending
        )

    async def get_targets(self, service_id, operation_id):
        async with self._engine.connect() as conn:
            await self._require_operation(conn, service_id, operation_id)
            rows = (await conn.execute(
                select(admin_notification_targets)
                .where(admin_notification_targets.c.operation_id == str(operation_id))
                .order_by(admin_notification_targets.c.member_id)
            )).mappings().all()
        return tuple(NotificationTargetRecord(
            operation_id=UUID(row["operation_id"]), member_id=row["member_id"],
            selected=row["selected"], line_linked=row["line_linked"],
            eligibility=NotificationEligibilityReason(row["eligibility"]) if row["eligibility"] else None,
            reason=row["reason"], created_at=_loaded_utc(row["created_at"]), updated_at=_loaded_utc(row["updated_at"]),
            line_subject=None,
        ) for row in rows)

    @staticmethod
    def _delivery_values(delivery, sequence):
        return {
            "delivery_id": str(delivery.delivery_id), "operation_id": str(delivery.operation_id),
            "member_id": delivery.member_id, "sequence": sequence,
            "status": delivery.status.value, "request_id": delivery.request_id,
            "error_code": delivery.error_code, "error_message": delivery.error_message,
            "created_at": _utc(delivery.created_at, "created_at"),
            "updated_at": _utc(delivery.updated_at, "updated_at"),
            "sent_at": _optional_utc(delivery.sent_at, "sent_at"),
        }

    @staticmethod
    def _delivery(row):
        return NotificationDeliveryRecord(
            delivery_id=UUID(row["delivery_id"]), operation_id=UUID(row["operation_id"]),
            member_id=row["member_id"], status=DeliveryStatus(row["status"]),
            request_id=row["request_id"], line_request_id=None,
            error_code=row["error_code"], error_message=row["error_message"],
            created_at=_loaded_utc(row["created_at"]), updated_at=_loaded_utc(row["updated_at"]), sent_at=_loaded_utc(row["sent_at"]),
            line_subject=None,
        )

    async def _add_deliveries(self, conn, operation_id, deliveries):
        pending = tuple(deliveries)
        seen = set()
        for item in pending:
            if item.operation_id != operation_id:
                raise RepositoryStateError("delivery operation_id does not match")
            if item.delivery_id in seen:
                raise DeliveryAlreadyExistsError("notification delivery already exists")
            seen.add(item.delivery_id)
        existing_count = (await conn.execute(select(admin_notification_deliveries.c.delivery_id).where(admin_notification_deliveries.c.operation_id == str(operation_id)))).all()
        try:
            if pending:
                await conn.execute(insert(admin_notification_deliveries), [self._delivery_values(item, len(existing_count) + index) for index, item in enumerate(pending)])
        except IntegrityError as exc:
            raise DeliveryAlreadyExistsError("notification delivery already exists") from exc
        return pending

    async def add_deliveries(self, service_id, operation_id, deliveries):
        async with self._engine.begin() as conn:
            await self._require_operation(conn, service_id, operation_id, lock=True)
            pending = await self._add_deliveries(conn, operation_id, deliveries)
        return tuple(
            replace(item, line_subject=None, line_request_id=None) for item in pending
        )

    @staticmethod
    def _outbox_values(item):
        return {
            "outbox_id": str(item.outbox_id),
            "command_id": str(item.command_id),
            "operation_id": str(item.operation_id),
            "target_id": str(item.target_id),
            "organization_id": item.organization_id,
            "service_id": item.service_id,
            "external_member_id": item.external_member_id,
            "job_id": item.job_id,
            "job_version": item.job_version,
            "message_greeting": item.business_message.greeting,
            "message_introduction": item.business_message.introduction,
            "message_note": item.business_message.note,
            "message_version": item.message_version,
            "message_hash": item.message_hash,
            "idempotency_key": item.idempotency_key,
            "correlation_id": item.correlation_id,
            "requested_at": _utc(item.requested_at, "requested_at"),
            "created_at": _utc(item.created_at, "created_at"),
            "state": item.state.value,
            "lease_expires_at": _optional_utc(item.lease_expires_at, "lease_expires_at"),
            "claim_token": str(item.claim_token) if item.claim_token else None,
        }

    @staticmethod
    def _outbox(row):
        return NotificationOutboxRecord(
            outbox_id=UUID(row["outbox_id"]),
            command_id=UUID(row["command_id"]),
            operation_id=UUID(row["operation_id"]),
            target_id=UUID(row["target_id"]),
            organization_id=row["organization_id"],
            service_id=row["service_id"],
            external_member_id=row["external_member_id"],
            job_id=row["job_id"],
            job_version=row["job_version"],
            business_message=NotificationMessage(
                row["message_greeting"],
                row["message_introduction"],
                row["message_note"],
            ),
            message_version=row["message_version"],
            message_hash=row["message_hash"],
            idempotency_key=row["idempotency_key"],
            correlation_id=row["correlation_id"],
            requested_at=_loaded_utc(row["requested_at"]),
            created_at=_loaded_utc(row["created_at"]),
            state=NotificationOutboxState(row["state"]),
            lease_expires_at=_loaded_utc(row["lease_expires_at"]),
            claim_token=UUID(row["claim_token"]) if row["claim_token"] else None,
        )

    async def begin_send_attempt(
        self,
        service_id,
        operation_id,
        deliveries,
        outbox_records,
        event,
        *,
        send_requested_at,
        expected_operation=None,
    ):
        send_requested_at = _utc(send_requested_at, "send_requested_at")
        outbox = tuple(outbox_records)
        try:
            async with self._engine.begin() as conn:
                operation = await self._require_operation(conn, service_id, operation_id, lock=True)
                has_delivery = (await conn.execute(select(admin_notification_deliveries.c.delivery_id).where(admin_notification_deliveries.c.operation_id == str(operation_id)).limit(1))).first()
                if operation.send_requested_at is not None or has_delivery:
                    raise SendAttemptAlreadyExistsError("notification operation already has a send attempt")
                if expected_operation is not None and operation != expected_operation:
                    raise ReservedNotificationMutationError("operation changed before send reservation")
                if any(item.operation_id != operation_id or item.service_id != service_id for item in outbox):
                    raise RepositoryStateError("outbox scope does not match operation")
                pending = await self._add_deliveries(conn, operation_id, deliveries)
                if outbox:
                    await conn.execute(
                        insert(admin_notification_outbox),
                        [self._outbox_values(item) for item in outbox],
                    )
                stored = replace(operation, send_requested_at=send_requested_at, updated_at=self._now())
                values = self._operation_values(stored); values.pop("operation_id")
                await conn.execute(update(admin_notification_operations).where(admin_notification_operations.c.operation_id == str(operation_id)).values(**values))
                await self._insert_audit(conn, operation_id, event)
        except IntegrityError as exc:
            raise SendAttemptAlreadyExistsError(
                "notification send intent already exists"
            ) from exc
        return stored, tuple(replace(item, line_subject=None, line_request_id=None) for item in pending)

    async def get_outbox_records(self, service_id, operation_id):
        async with self._engine.connect() as conn:
            await self._require_operation(conn, service_id, operation_id)
            rows = (await conn.execute(
                select(admin_notification_outbox)
                .where(admin_notification_outbox.c.operation_id == str(operation_id))
                .order_by(admin_notification_outbox.c.created_at, admin_notification_outbox.c.outbox_id)
            )).mappings().all()
        return tuple(self._outbox(row) for row in rows)

    async def claim_outbox_records(self, service_id, operation_id):
        claimable = (
            NotificationOutboxState.PENDING.value,
            NotificationOutboxState.RETRYABLE_FAILURE.value,
        )
        async with self._engine.begin() as conn:
            operation = await self._require_operation(conn, service_id, operation_id, lock=True)
            if operation.status is OperationStatus.CANCELLED:
                return ()
            now = self._now()
            token = uuid4()
            expires = now + timedelta(seconds=60)
            rows = (await conn.execute(
                select(admin_notification_outbox)
                .where(
                    admin_notification_outbox.c.operation_id == str(operation_id),
                    or_(admin_notification_outbox.c.state.in_(claimable), and_(
                        admin_notification_outbox.c.state == NotificationOutboxState.DELIVERING.value,
                        or_(admin_notification_outbox.c.lease_expires_at.is_(None),
                            admin_notification_outbox.c.lease_expires_at <= now))),
                )
                .order_by(
                    admin_notification_outbox.c.lease_expires_at.asc().nullsfirst(),
                    admin_notification_outbox.c.created_at,
                    admin_notification_outbox.c.outbox_id,
                )
                .limit(1).with_for_update()
            )).mappings().all()
            ids = tuple(row["outbox_id"] for row in rows)
            if ids:
                await conn.execute(
                    update(admin_notification_outbox)
                    .where(
                        admin_notification_outbox.c.outbox_id.in_(ids),
                    )
                    .values(state=NotificationOutboxState.DELIVERING.value,
                            lease_expires_at=expires, claim_token=str(token))
                )
        return tuple(
            replace(
                self._outbox(row), state=NotificationOutboxState.DELIVERING,
                lease_expires_at=expires, claim_token=token
            )
            for row in rows
        )

    async def update_outbox_state(
        self, service_id, operation_id, outbox_id, state, *, claim_token=None
    ):
        async with self._engine.begin() as conn:
            operation = await self._require_operation(conn, service_id, operation_id, lock=True)
            row = (await conn.execute(
                select(admin_notification_outbox).where(
                    admin_notification_outbox.c.outbox_id == str(outbox_id),
                    admin_notification_outbox.c.operation_id == str(operation_id),
                ).with_for_update()
            )).mappings().first()
            if row is None:
                raise RepositoryStateError("notification outbox record was not found")
            if (row["state"] != NotificationOutboxState.DELIVERING.value
                    or claim_token is None or row["claim_token"] != str(claim_token)):
                return self._outbox(row)
            if state not in (NotificationOutboxState.ACCEPTED, NotificationOutboxState.RETRYABLE_FAILURE,
                             NotificationOutboxState.PERMANENT_FAILURE):
                raise RepositoryStateError("invalid submission outcome")
            await conn.execute(
                update(admin_notification_outbox)
                .where(admin_notification_outbox.c.outbox_id == str(outbox_id))
                .values(state=state.value, claim_token=None,
                        lease_expires_at=self._now() if state is NotificationOutboxState.RETRYABLE_FAILURE else None)
            )
            if state is NotificationOutboxState.PERMANENT_FAILURE:
                await self._fail_submission(conn, row)
            await self._aggregate(conn, operation)
        return replace(self._outbox(row), state=state, claim_token=None,
                       lease_expires_at=self._now() if state is NotificationOutboxState.RETRYABLE_FAILURE else None)

    async def _fail_submission(self, conn, row):
        await conn.execute(update(admin_notification_deliveries).where(
            admin_notification_deliveries.c.operation_id == row["operation_id"],
            admin_notification_deliveries.c.member_id == row["external_member_id"],
            admin_notification_deliveries.c.status == DeliveryStatus.PENDING.value,
        ).values(status=DeliveryStatus.FAILED.value, error_code="line_submission_permanent_failure",
                 error_message=None, updated_at=self._now()))

    async def _aggregate(self, conn, operation):
        statuses = (await conn.execute(select(admin_notification_deliveries.c.status).where(
            admin_notification_deliveries.c.operation_id == str(operation.operation_id)
        ))).scalars().all()
        if not statuses or operation.send_requested_at is None or operation.status is OperationStatus.CANCELLED:
            return operation
        if DeliveryStatus.PENDING.value in statuses:
            status = OperationStatus.SENDING
        elif all(value == DeliveryStatus.SENT.value for value in statuses):
            status = OperationStatus.COMPLETED
        else:
            status = OperationStatus.COMPLETED_WITH_ERRORS
        completed = operation.completed_at
        if status in (OperationStatus.COMPLETED, OperationStatus.COMPLETED_WITH_ERRORS):
            completed = completed or self._now()
        if operation.status is status and operation.completed_at == completed:
            return operation
        stored = replace(operation, status=status, completed_at=completed, updated_at=self._now())
        await conn.execute(update(admin_notification_operations).where(
            admin_notification_operations.c.operation_id == str(operation.operation_id)
        ).values(status=status.value, completed_at=completed, updated_at=stored.updated_at))
        await self._insert_audit(conn, operation.operation_id, NotificationAuditEvent(
            audit_id=uuid4(), operation_id=operation.operation_id, event_type="delivery_aggregate_updated",
            staff_id=None, details={"status": status.value}, created_at=stored.updated_at))
        return stored

    async def refresh_delivery_aggregate(self, service_id, operation_id):
        async with self._engine.begin() as conn:
            operation = await self._require_operation(conn, service_id, operation_id, lock=True)
            # Repair pre-migration permanent failures without another submission.
            rows = (await conn.execute(select(admin_notification_outbox).where(
                admin_notification_outbox.c.operation_id == str(operation_id),
                admin_notification_outbox.c.state == NotificationOutboxState.PERMANENT_FAILURE.value
            ))).mappings().all()
            for row in rows:
                await self._fail_submission(conn, row)
            return await self._aggregate(conn, operation)

    async def reconcile_outbox_result(self, service_id, operation_id, outbox_id, delivery):
        async with self._engine.begin() as conn:
            operation = await self._require_operation(conn, service_id, operation_id, lock=True)
            row = (await conn.execute(select(admin_notification_outbox).where(
                admin_notification_outbox.c.operation_id == str(operation_id),
                admin_notification_outbox.c.outbox_id == str(outbox_id)
            ).with_for_update())).mappings().first()
            if row is None:
                raise RepositoryStateError("notification outbox record was not found")
            if row["state"] != NotificationOutboxState.ACCEPTED.value:
                return operation
            if delivery.status is DeliveryStatus.PENDING:
                return operation
            current = (await conn.execute(select(admin_notification_deliveries).where(
                admin_notification_deliveries.c.operation_id == str(operation_id),
                admin_notification_deliveries.c.member_id == row["external_member_id"],
                admin_notification_deliveries.c.delivery_id == str(delivery.delivery_id)
            ))).mappings().one()
            if current["status"] == DeliveryStatus.PENDING.value:
                values = self._delivery_values(replace(delivery, updated_at=self._now()), current["sequence"])
                await conn.execute(update(admin_notification_deliveries).where(
                    admin_notification_deliveries.c.delivery_id == current["delivery_id"]
                ).values(**values))
            await conn.execute(update(admin_notification_outbox).where(
                admin_notification_outbox.c.outbox_id == str(outbox_id)
            ).values(state=NotificationOutboxState.RECONCILED.value, lease_expires_at=None, claim_token=None))
            return await self._aggregate(conn, operation)

    async def list_recovery_operations(self, service_id, *, after=None, limit=50):
        op = admin_notification_operations.c
        outbox = admin_notification_outbox.c
        active = select(outbox.outbox_id).where(outbox.operation_id == op.operation_id,
            outbox.state.not_in((NotificationOutboxState.RECONCILED.value,
                                NotificationOutboxState.PERMANENT_FAILURE.value))).exists()
        stmt = select(admin_notification_operations).where(
            op.service_id == service_id, op.send_requested_at.is_not(None),
            op.status != OperationStatus.CANCELLED.value,
            or_(active, op.completed_at.is_(None)))
        if after is not None:
            stmt = stmt.where(op.operation_id > str(after))
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt.order_by(op.operation_id).limit(limit))).mappings().all()
        return tuple(self._operation(row) for row in rows)

    async def rollback_send_attempt(self, service_id, operation_id, delivery_ids):
        expected = tuple(delivery_ids)
        async with self._engine.begin() as conn:
            operation = await self._require_operation(conn, service_id, operation_id, lock=True)
            has_outbox = (await conn.execute(select(admin_notification_outbox.c.outbox_id).where(
                admin_notification_outbox.c.operation_id == str(operation_id)).limit(1))).first()
            if has_outbox:
                raise ReservedNotificationMutationError("durable outbox reservation cannot be rolled back")
            rows = (await conn.execute(select(admin_notification_deliveries).where(admin_notification_deliveries.c.operation_id == str(operation_id)).order_by(admin_notification_deliveries.c.sequence))).mappings().all()
            if tuple(UUID(row["delivery_id"]) for row in rows) != expected:
                raise RepositoryStateError("send attempt changed before rollback")
            if any(DeliveryStatus(row["status"]) not in (DeliveryStatus.PENDING, DeliveryStatus.SKIPPED) for row in rows):
                raise RepositoryStateError("processed delivery cannot be rolled back")
            await conn.execute(delete(admin_notification_deliveries).where(admin_notification_deliveries.c.operation_id == str(operation_id)))
            stored = replace(operation, send_requested_at=None, updated_at=self._now())
            values = self._operation_values(stored); values.pop("operation_id")
            await conn.execute(update(admin_notification_operations).where(admin_notification_operations.c.operation_id == str(operation_id)).values(**values))
        return stored

    async def get_deliveries(self, service_id, operation_id):
        async with self._engine.connect() as conn:
            await self._require_operation(conn, service_id, operation_id)
            rows = (await conn.execute(select(admin_notification_deliveries).where(admin_notification_deliveries.c.operation_id == str(operation_id)).order_by(admin_notification_deliveries.c.sequence))).mappings().all()
        return tuple(self._delivery(row) for row in rows)

    async def update_delivery(self, service_id, operation_id, delivery_id, delivery):
        async with self._engine.begin() as conn:
            await self._require_operation(conn, service_id, operation_id, lock=True)
            row = (await conn.execute(select(admin_notification_deliveries).where(admin_notification_deliveries.c.delivery_id == str(delivery_id)).with_for_update())).mappings().first()
            if row is None or row["operation_id"] != str(operation_id):
                raise DeliveryNotFoundError("notification delivery was not found")
            if delivery.delivery_id != delivery_id or delivery.operation_id != operation_id:
                raise RepositoryStateError("delivery identity cannot be changed")
            stored = replace(delivery, created_at=row["created_at"], updated_at=self._now(), line_subject=None, line_request_id=None)
            values = self._delivery_values(stored, row["sequence"]); values.pop("delivery_id"); values.pop("operation_id")
            await conn.execute(update(admin_notification_deliveries).where(admin_notification_deliveries.c.delivery_id == str(delivery_id)).values(**values))
        return stored

    async def append_audit_event(self, service_id, operation_id, event):
        if event.operation_id != operation_id:
            raise RepositoryStateError("audit operation_id does not match")
        try:
            async with self._engine.begin() as conn:
                await self._require_operation(conn, service_id, operation_id)
                await self._insert_audit(conn, operation_id, event)
        except IntegrityError as exc:
            raise AuditEventAlreadyExistsError("audit event already exists") from exc
        return event

    async def get_audit_events(self, service_id, operation_id):
        async with self._engine.connect() as conn:
            await self._require_operation(conn, service_id, operation_id)
            rows = (await conn.execute(select(admin_notification_audit_events).where(admin_notification_audit_events.c.operation_id == str(operation_id)).order_by(admin_notification_audit_events.c.created_at, admin_notification_audit_events.c.audit_id))).mappings().all()
        return tuple(NotificationAuditEvent(
            audit_id=UUID(row["audit_id"]), operation_id=UUID(row["operation_id"]),
            event_type=row["event_type"], staff_id=row["staff_id"], details=row["details"], created_at=_loaded_utc(row["created_at"]),
        ) for row in rows)

    async def reset(self) -> None:
        """Test/demo convenience; not part of the production repository port."""
        async with self._engine.begin() as conn:
            await conn.execute(delete(admin_notification_outbox))
            await conn.execute(delete(admin_notification_audit_events))
            await conn.execute(delete(admin_notification_deliveries))
            await conn.execute(delete(admin_notification_targets))
            await conn.execute(delete(admin_notification_operations))
