"""Local-only inline orchestration for persisted notification operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Awaitable, Callable
from uuid import UUID

from app.domain.errors.errors import QueueError
from app.domain.models.notification import QueueEnqueueResult


class LocalInlineNotificationQueue:
    """Invoke the registered scoped dispatcher in the current process.

    This adapter owns no notification or delivery state. The persistent Admin
    repository remains the source of truth; its scope checks are performed by
    the registered runtime handler before dispatch.
    """

    def __init__(self) -> None:
        self._handler: Callable[..., Awaitable[None]] | None = None

    def register_handler(self, handler: Callable[..., Awaitable[None]]) -> None:
        self._handler = handler

    async def enqueue_scoped_notification_operation(
        self,
        *,
        service_id: str,
        operation_id: UUID,
        request_id: str,
    ) -> QueueEnqueueResult:
        if not service_id or service_id != service_id.strip():
            raise QueueError("service scope is required for scoped enqueue")
        if self._handler is None:
            raise QueueError("local inline notification handler is not configured")

        await self._handler(
            service_id=service_id,
            operation_id=operation_id,
            request_id=request_id,
        )
        return QueueEnqueueResult(
            task_name=f"notification-operation-{operation_id}",
            enqueued_at=datetime.now(tz=timezone.utc),
        )
