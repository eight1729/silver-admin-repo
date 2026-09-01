"""Async repository port required by the Admin notification application."""

from datetime import datetime
from typing import Iterable, Protocol
from uuid import UUID

from app.domain.models.admin_notification import (
    NotificationAuditEvent,
    NotificationDeliveryRecord,
    NotificationOperationRecord,
    NotificationOutboxRecord,
    NotificationTargetRecord,
)


class AdminNotificationRepository(Protocol):
    async def create_operation_with_audit(
        self, operation: NotificationOperationRecord, event: NotificationAuditEvent
    ) -> NotificationOperationRecord: ...

    async def get_operation(
        self, service_id: str, operation_id: UUID
    ) -> NotificationOperationRecord: ...

    async def resolve_operation_service_id(self, operation_id: UUID) -> str: ...

    async def update_operation_with_audit(
        self,
        service_id: str,
        operation_id: UUID,
        operation: NotificationOperationRecord,
        event: NotificationAuditEvent,
    ) -> NotificationOperationRecord: ...

    async def update_operation(
        self,
        service_id: str,
        operation_id: UUID,
        operation: NotificationOperationRecord,
    ) -> NotificationOperationRecord: ...

    async def list_operations(
        self, service_id: str
    ) -> tuple[NotificationOperationRecord, ...]: ...

    async def replace_targets_with_operation_and_audit(
        self,
        service_id: str,
        operation_id: UUID,
        targets: Iterable[NotificationTargetRecord],
        operation: NotificationOperationRecord,
        event: NotificationAuditEvent,
    ) -> tuple[NotificationOperationRecord, tuple[NotificationTargetRecord, ...]]: ...

    async def get_targets(
        self, service_id: str, operation_id: UUID
    ) -> tuple[NotificationTargetRecord, ...]: ...

    async def begin_send_attempt(
        self,
        service_id: str,
        operation_id: UUID,
        deliveries: Iterable[NotificationDeliveryRecord],
        outbox_records: Iterable[NotificationOutboxRecord],
        event: NotificationAuditEvent,
        *,
        send_requested_at: datetime,
    ) -> tuple[
        NotificationOperationRecord, tuple[NotificationDeliveryRecord, ...]
    ]: ...

    async def get_outbox_records(
        self, service_id: str, operation_id: UUID
    ) -> tuple[NotificationOutboxRecord, ...]: ...

    async def claim_outbox_records(
        self, service_id: str, operation_id: UUID
    ) -> tuple[NotificationOutboxRecord, ...]: ...

    async def update_outbox_state(
        self,
        service_id: str,
        operation_id: UUID,
        outbox_id: UUID,
        state,
    ) -> NotificationOutboxRecord: ...

    async def rollback_send_attempt(
        self,
        service_id: str,
        operation_id: UUID,
        delivery_ids: Iterable[UUID],
    ) -> NotificationOperationRecord: ...

    async def get_deliveries(
        self, service_id: str, operation_id: UUID
    ) -> tuple[NotificationDeliveryRecord, ...]: ...

    async def update_delivery(
        self,
        service_id: str,
        operation_id: UUID,
        delivery_id: UUID,
        delivery: NotificationDeliveryRecord,
    ) -> NotificationDeliveryRecord: ...

    async def append_audit_event(
        self,
        service_id: str,
        operation_id: UUID,
        event: NotificationAuditEvent,
    ) -> NotificationAuditEvent: ...

    async def get_audit_events(
        self, service_id: str, operation_id: UUID
    ) -> tuple[NotificationAuditEvent, ...]: ...
