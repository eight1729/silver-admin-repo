"""Admin Outbox dispatch and business-result reconciliation via LINE API."""

from dataclasses import replace
import asyncio
import logging
from uuid import UUID

from app.adapter.line_internal_api import (
    LineInternalApiPermanentError,
    LineInternalApiRetryableError,
)
from app.domain.enums.enums import DeliveryStatus
from app.domain.models.admin_notification import NotificationOutboxState
from app.contracts.admin_line_internal_v1 import (
    BusinessNotificationMessage,
    NotificationCommand,
    ServiceOrganizationScope,
)

logger = logging.getLogger(__name__)


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
                await asyncio.wait_for(self._line_client.submit_notification_command(
                    self._command(item)
                ), timeout=30)
            except (LineInternalApiRetryableError, asyncio.TimeoutError):
                state = NotificationOutboxState.RETRYABLE_FAILURE
            except LineInternalApiPermanentError:
                state = NotificationOutboxState.PERMANENT_FAILURE
            else:
                state = NotificationOutboxState.ACCEPTED
            await self._repository.update_outbox_state(
                service_id, operation_id, item.outbox_id, state, claim_token=item.claim_token
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
        self._cursors = {}

    async def reconcile_operation(self, *, service_id: str, operation_id: UUID):
        outbox = await self._repository.get_outbox_records(service_id, operation_id)
        accepted = tuple(
            item for item in outbox
            if item.state is NotificationOutboxState.ACCEPTED
        )
        cursor = self._cursors.get(operation_id, "")
        accepted = tuple(sorted(accepted, key=lambda item: str(item.outbox_id)))
        page = tuple(item for item in accepted if str(item.outbox_id) > cursor)[:50]
        if not page:
            page = accepted[:50]
        if page:
            self._cursors[operation_id] = str(page[-1].outbox_id)
        else:
            self._cursors.pop(operation_id, None)
        deliveries = list(
            await self._repository.get_deliveries(service_id, operation_id)
        )
        by_member = {item.member_id: item for item in deliveries}
        for item in page:
            try:
                result = await asyncio.wait_for(self._line_client.get_notification_result(item.command_id), timeout=30)
            except Exception as error:
                logger.warning("Admin result polling failed: %s", type(error).__name__)
                continue
            delivery = by_member.get(item.external_member_id)
            if delivery is None:
                continue
            projected = self._project(delivery, result)
            if getattr(result.status, "value", result.status) not in ("accepted", "pending"):
                await self._repository.reconcile_outbox_result(
                    service_id, operation_id, item.outbox_id, projected)

        operation = await self._repository.refresh_delivery_aggregate(service_id, operation_id)
        if getattr(operation, "completed_at", None) is not None:
            self._cursors.pop(operation_id, None)
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
