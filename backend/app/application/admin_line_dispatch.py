"""Admin Outbox dispatch and business-result reconciliation via LINE API."""

from dataclasses import replace
from uuid import UUID

from app.adapter.line_internal_api import (
    LineInternalApiPermanentError,
    LineInternalApiRetryableError,
)
from app.domain.enums.enums import DeliveryStatus, OperationStatus
from app.domain.models.admin_notification import NotificationOutboxState
from app.contracts.admin_line_internal_v1 import (
    BusinessNotificationMessage,
    NotificationCommand,
    NotificationCommandStatus,
    ServiceOrganizationScope,
)


class AdminLineOutboxDispatcher:
    def __init__(self, *, repository, line_client) -> None:
        self._repository = repository
        self._line_client = line_client

    async def dispatch_operation(self, *, service_id: str, operation_id: UUID) -> None:
        claimed = await self._repository.claim_outbox_records(
            service_id, operation_id
        )
        for item in claimed:
            try:
                await self._line_client.submit_notification_command(
                    self._command(item)
                )
            except LineInternalApiRetryableError:
                state = NotificationOutboxState.RETRYABLE_FAILURE
            except LineInternalApiPermanentError:
                state = NotificationOutboxState.PERMANENT_FAILURE
            else:
                state = NotificationOutboxState.ACCEPTED
            await self._repository.update_outbox_state(
                service_id, operation_id, item.outbox_id, state
            )

    @staticmethod
    def _command(item) -> NotificationCommand:
        return NotificationCommand(
            command_id=item.command_id,
            operation_id=item.operation_id,
            target_id=item.target_id,
            scope=ServiceOrganizationScope(
                organization_id=item.organization_id,
                service_id=item.service_id,
            ),
            external_member_id=item.external_member_id,
            job_id=item.job_id,
            job_version=item.job_version,
            business_message=BusinessNotificationMessage(
                greeting=item.business_message.greeting,
                introduction=item.business_message.introduction,
                note=item.business_message.note,
            ),
            message_version=str(item.message_version),
            message_hash=item.message_hash,
            idempotency_key=item.idempotency_key,
            correlation_id=item.correlation_id,
            requested_at=item.requested_at,
        )


class AdminLineResultReconciler:
    def __init__(self, *, repository, line_client) -> None:
        self._repository = repository
        self._line_client = line_client

    async def reconcile_operation(self, *, service_id: str, operation_id: UUID):
        outbox = await self._repository.get_outbox_records(service_id, operation_id)
        accepted = tuple(
            item for item in outbox
            if item.state is NotificationOutboxState.ACCEPTED
        )
        deliveries = list(
            await self._repository.get_deliveries(service_id, operation_id)
        )
        by_member = {item.member_id: item for item in deliveries}
        for item in accepted:
            result = await self._line_client.get_notification_result(item.command_id)
            delivery = by_member.get(item.external_member_id)
            if delivery is None:
                continue
            projected = self._project(delivery, result)
            if projected != delivery:
                stored = await self._repository.update_delivery(
                    service_id, operation_id, delivery.delivery_id, projected
                )
                by_member[stored.member_id] = stored

        current = tuple(by_member.values())
        operation = await self._repository.get_operation(service_id, operation_id)
        pending = any(item.status is DeliveryStatus.PENDING for item in current)
        if pending:
            status = OperationStatus.SENDING
        elif any(item.status in (DeliveryStatus.FAILED, DeliveryStatus.UNKNOWN, DeliveryStatus.SKIPPED) for item in current):
            status = OperationStatus.COMPLETED_WITH_ERRORS
        else:
            status = OperationStatus.COMPLETED
        if operation.status is not status:
            operation = await self._repository.update_operation(
                service_id, operation_id, replace(operation, status=status)
            )
        return operation

    @staticmethod
    def _project(delivery, result):
        # Accept an enum generated independently from the same artifact.
        status = getattr(result.status, "value", result.status)
        if status in ("accepted", "pending"):
            return delivery
        if status == "sent":
            return replace(
                delivery, status=DeliveryStatus.SENT, error_code=None,
                error_message=None, sent_at=result.updated_at,
            )
        if status == "failed":
            return replace(
                delivery, status=DeliveryStatus.FAILED,
                error_code=result.reason_code, error_message=None,
            )
        if status == "recipient_not_linked":
            return replace(
                delivery, status=DeliveryStatus.SKIPPED,
                error_code="recipient_not_linked", error_message=None,
            )
        if status == "unknown":
            return replace(
                delivery, status=DeliveryStatus.UNKNOWN,
                error_code=result.reason_code, error_message=None,
            )
        return replace(
            delivery, status=DeliveryStatus.FAILED,
            error_code=result.reason_code or "command_rejected", error_message=None,
        )
